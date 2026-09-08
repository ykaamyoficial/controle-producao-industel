"""Fase 14, Secao 19/20/21: integracao do Maintenance Mode com o pipeline de
deploy (PRECHECK -> DRAINING/ACTIVE, VERIFY -> RECOVERY/finish, ROLLBACK ->
so libera OFF apos verificacao aprovada). Cada script permanece testavel via
injecao de dependencia, mesmo padrao do proprio DeploymentOrchestrator/docker.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from api.app.core.config import API_VERSION
from api.app.database.health import DatabaseCheck
from api.app.deployment.models import DeploymentStatus
from api.app.deployment.service import DeploymentOrchestrator
from api.app.deployment.state_store import DeploymentStateStore
from api.app.health.models import SmokeStatus
from api.app.maintenance.models import MaintenanceStateName
from api.app.maintenance.service import MaintenanceService
from api.app.maintenance.store import MaintenanceStateStore
from api.tests._deployment_test_support import FakeDocker, fake_smoke_runner_factory
from scripts.deployment.metadata import DeploymentMetadata
from scripts.deployment.precheck import run_precheck
from scripts.deployment.run_verify import VerifyFailedError, run_verify


class _PipelineHarness(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        self.deployment_store = DeploymentStateStore(self.state_dir / "deployments")
        self.docker = FakeDocker()
        self.orchestrator = DeploymentOrchestrator(
            state_store=self.deployment_store, lock_path=self.state_dir / ".deployment.lock", lock_timeout_seconds=60,
            container_name="controle_producao_api", network="fake-net", health_base_url="http://127.0.0.1:8000",
            docker=self.docker,
        )
        self.maintenance_service = MaintenanceService(
            store=MaintenanceStateStore(self.state_dir / "maintenance.json"),
            lock_path=self.state_dir / ".maintenance.lock",
            lock_timeout_seconds=5,
        )
        self.connected = DatabaseCheck(status="connected", revision="20260810_0015", revision_status="compatible")

    def _precheck(self) -> DeploymentMetadata:
        return run_precheck(
            target_version=API_VERSION,
            image_repository="ghcr.io/owner/controle-producao-api",
            image_tag=API_VERSION,
            image_digest="sha256:" + "a" * 64,
            git_commit_sha="abc1234",
            docker=FakeDocker(docker_is_available=True),
            database_state_fn=lambda: self.connected,
            disk_usage_fn=lambda path: type("Usage", (), {"free": 10 * 1024 * 1024 * 1024})(),
            orchestrator=self.orchestrator,
            maintenance_service=self.maintenance_service,
            draining_window_seconds=0,
        )


class PrecheckOpensMaintenanceWindowTests(_PipelineHarness):
    def test_precheck_transitions_off_to_draining_to_active(self):
        self.assertEqual(self.maintenance_service.get_state().state, MaintenanceStateName.OFF)
        self._precheck()
        self.assertEqual(self.maintenance_service.get_state().state, MaintenanceStateName.ACTIVE)

    def test_precheck_failure_before_begin_deployment_never_touches_maintenance(self):
        with self.assertRaises(Exception):
            run_precheck(
                target_version="9.9.9",  # diverge de API_VERSION -> PrecheckFailedError antes do begin_deployment
                image_repository="ghcr.io/owner/controle-producao-api",
                image_tag="9.9.9",
                image_digest=None,
                git_commit_sha="abc1234",
                docker=FakeDocker(docker_is_available=True),
                database_state_fn=lambda: self.connected,
                disk_usage_fn=lambda path: type("Usage", (), {"free": 10 * 1024 * 1024 * 1024})(),
                orchestrator=self.orchestrator,
                maintenance_service=self.maintenance_service,
                draining_window_seconds=0,
            )
        self.assertEqual(self.maintenance_service.get_state().state, MaintenanceStateName.OFF)


class VerifyReleasesMaintenanceOnlyAfterApprovalTests(_PipelineHarness):
    def _verify_kwargs(self, metadata: DeploymentMetadata, **overrides):
        kwargs = dict(
            metadata=metadata, container_name="controle_producao_api", base_url="http://127.0.0.1:18000",
            orchestrator=self.orchestrator, docker=self.docker,
            runner_factory=fake_smoke_runner_factory(SmokeStatus.PASS),
            current_revision_fn=lambda: "20260810_0015",
            maintenance_service=self.maintenance_service,
        )
        kwargs.update(overrides)
        return kwargs

    def test_successful_verify_moves_maintenance_through_recovery_to_off(self):
        metadata = self._precheck()
        self.orchestrator.mark_deploying(metadata.deployment_id)
        self.orchestrator.mark_validating(metadata.deployment_id)

        run_verify(**self._verify_kwargs(metadata))

        self.assertEqual(self.maintenance_service.get_state().state, MaintenanceStateName.OFF)

    def test_readiness_failure_keeps_maintenance_active_never_off(self):
        metadata = self._precheck()
        self.orchestrator.mark_deploying(metadata.deployment_id)
        self.orchestrator.mark_validating(metadata.deployment_id)
        unhealthy_docker = FakeDocker(healthy_after_run=False)

        with self.assertRaises(VerifyFailedError):
            run_verify(**self._verify_kwargs(metadata, docker=unhealthy_docker))

        # Falhou antes de chegar em RECOVERY (Secao 20: "manter ACTIVE ou
        # RECOVERY conforme o ponto da falha") -- aqui, permanece ACTIVE.
        self.assertEqual(self.maintenance_service.get_state().state, MaintenanceStateName.ACTIVE)

    def test_smoke_failure_leaves_maintenance_in_recovery_not_off(self):
        metadata = self._precheck()
        self.orchestrator.mark_deploying(metadata.deployment_id)
        self.orchestrator.mark_validating(metadata.deployment_id)

        with self.assertRaises(VerifyFailedError):
            run_verify(**self._verify_kwargs(metadata, runner_factory=fake_smoke_runner_factory(SmokeStatus.FAIL)))

        # Ja tinha entrado em RECOVERY antes do smoke test rodar -- fica ali,
        # nunca volta para ACTIVE nem cai para OFF por pressao.
        self.assertEqual(self.maintenance_service.get_state().state, MaintenanceStateName.RECOVERY)

    def test_verify_without_maintenance_mode_in_use_is_a_pure_noop_for_it(self):
        # VERIFY chamado fora do fluxo de Maintenance Mode (estado OFF desde
        # o inicio) nao deve tentar nenhuma transicao nem falhar por isso.
        deployment = self.orchestrator.begin_deployment(
            target_version="1.0.0", target_image_ref="ghcr.io/owner/api:1.0.0", database_revision_before="20260810_0015",
        )
        self.orchestrator.mark_deploying(deployment.deployment_id)
        self.orchestrator.mark_validating(deployment.deployment_id)
        metadata = DeploymentMetadata(
            deployment_id=deployment.deployment_id, release_version="1.0.0", git_commit_sha="abc1234",
            image_repository="ghcr.io/owner/api", image_tag="1.0.0", api_contract_version="v1",
            expected_database_schema="20260810_0015",
        )

        run_verify(**self._verify_kwargs(metadata))

        self.assertEqual(self.maintenance_service.get_state().state, MaintenanceStateName.OFF)
        self.assertEqual(self.deployment_store.load(deployment.deployment_id).status, DeploymentStatus.HEALTHY)


if __name__ == "__main__":
    unittest.main()
