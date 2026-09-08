from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from api.app.core.config import API_VERSION, get_settings
from api.app.database.health import current_database_revision
from api.app.database.session import dispose_engine, get_engine
from api.app.deployment import docker_control
from api.app.deployment.exceptions import RollbackNotAllowedError
from api.app.deployment.models import DeploymentState, DeploymentStatus
from api.app.deployment.service import DeploymentOrchestrator
from api.app.deployment.state_store import DeploymentStateStore
from api.app.health.smoke import SmokeTestRunner
from api.tests._docker_test_support import dev_postgres_network, docker_available
from api.tests._migration_test_support import TEST_DATABASE_URL, integration_enabled
from scripts.build_release_image import build_image, resolve_build_time, resolve_commit_sha

_SKIP = "Exige Docker + o Postgres de desenvolvimento (controle_producao_postgres_dev) + POSTGRES_TEST_DATABASE_URL/APP_ENV=test (mesmo guard das Fases 04-07)."


def _network_database_url() -> str:
    return TEST_DATABASE_URL.replace("127.0.0.1:55432", "postgres:5432")


def _swap_env() -> dict[str, str | None]:
    """Mesmo padrao de api/tests/test_health_smoke_integration.py: aponta
    DATABASE_URL para o banco de teste descartavel (nunca para producao) e
    limpa os caches do engine/settings, que sao @lru_cache."""
    previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV")}
    os.environ["APP_ENV"] = "test"
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    get_settings.cache_clear()
    get_engine.cache_clear()
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    get_settings.cache_clear()
    get_engine.cache_clear()


def _real_current_revision() -> str | None:
    async def _inner() -> str | None:
        try:
            return await current_database_revision()
        finally:
            await dispose_engine()

    return asyncio.run(_inner())


@unittest.skipUnless(docker_available() and integration_enabled() and dev_postgres_network() is not None, _SKIP)
class RollbackRealDockerTests(unittest.TestCase):
    """Fase 08, Secao 27: builda a imagem real (Fase 07), sobe/reativa containers
    de verdade via docker_control e valida com o SmokeTestRunner real (Fase 06)
    -- nenhum mock de subprocess/HTTP nesta classe."""

    @classmethod
    def setUpClass(cls):
        cls.previous_env = _swap_env()
        cls.image_ref = f"controle-producao-api-rollback-test:{uuid.uuid4().hex[:10]}"
        build_image(image_ref=cls.image_ref, server_version=API_VERSION, commit_sha=resolve_commit_sha(), build_time=resolve_build_time())
        cls.network = dev_postgres_network()

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["docker", "image", "rm", "-f", cls.image_ref], capture_output=True)
        _restore_env(cls.previous_env)

    def setUp(self):
        self.container_name = f"rollback-test-{uuid.uuid4().hex[:8]}"
        self.port = 18300 + (int(uuid.uuid4().hex[:4], 16) % 500)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        self.store = DeploymentStateStore(self.state_dir)
        self.orchestrator = DeploymentOrchestrator(
            state_store=self.store,
            lock_path=self.state_dir / ".deployment.lock",
            lock_timeout_seconds=60,
            container_name=self.container_name,
            network=self.network,
            health_base_url=f"http://127.0.0.1:{self.port}",
            validation_timeout_seconds=60.0,
        )
        self.addCleanup(lambda: docker_control.stop_and_remove_container(self.container_name))

    def _container_env(self) -> dict[str, str]:
        return {
            "DATABASE_URL": _network_database_url(),
            "SECRET_KEY": "rollback-integration-test-secret-32chars",
            "APP_ENV": "test",
            "OPERATIONAL_COMPANY_CODE": "rollback-integration",
            "OPERATIONAL_COMPANY_NAME": "Rollback Integration",
            "OPERATIONAL_ENVIRONMENT_TYPE": "production",
        }

    def _deploy_healthy(self, *, database_revision: str | None) -> DeploymentState:
        state = self.orchestrator.begin_deployment(
            target_version=API_VERSION, target_image_ref=self.image_ref,
            database_revision_before=database_revision, source="integration-test",
        )
        state = self.orchestrator.mark_deploying(state.deployment_id)
        docker_control.run_container(
            name=self.container_name, image_ref=self.image_ref, network=self.network,
            env=self._container_env(), port=self.port,
        )
        self.assertTrue(docker_control.wait_for_healthy(self.container_name, timeout_seconds=60.0), "container inicial nao ficou healthy")
        state = self.orchestrator.mark_validating(state.deployment_id)
        report = SmokeTestRunner(base_url=f"http://127.0.0.1:{self.port}", expected_server_version=API_VERSION).run()
        self.assertEqual(report.status.value, "PASS", [s.to_dict() for s in report.steps])
        return self.orchestrator.mark_healthy(state.deployment_id, database_revision_after=database_revision)

    def test_deploy_then_rollback_reactivates_previous_image_and_passes_validation(self):
        current_revision = _real_current_revision()
        self.assertIsNotNone(current_revision, "banco de teste sem revisao aplicada")
        healthy = self._deploy_healthy(database_revision=current_revision)
        self.assertEqual(healthy.status, DeploymentStatus.HEALTHY)

        rolled_back = self.orchestrator.rollback_to_previous_healthy_release(
            current_database_revision=current_revision, reason="teste de integracao", container_env=self._container_env(),
        )
        self.assertEqual(rolled_back.status, DeploymentStatus.ROLLED_BACK)
        self.assertEqual(rolled_back.target_image_ref, self.image_ref)

        report = SmokeTestRunner(base_url=f"http://127.0.0.1:{self.port}", expected_server_version=API_VERSION).run()
        self.assertEqual(report.status.value, "PASS")

        # o rollback nunca toca o PostgreSQL: a revisao do banco de teste
        # continua exatamente a mesma antes e depois (Secao 6).
        self.assertEqual(_real_current_revision(), current_revision)

    def test_repeated_rollback_is_idempotent_and_does_not_recreate_the_container(self):
        current_revision = _real_current_revision()
        self._deploy_healthy(database_revision=current_revision)

        self.orchestrator.rollback_to_previous_healthy_release(
            current_database_revision=current_revision, reason="primeiro rollback", container_env=self._container_env(),
        )
        container_id_after_first = subprocess.run(
            ["docker", "inspect", "--format", "{{.Id}}", self.container_name], capture_output=True, text=True,
        ).stdout.strip()

        second = self.orchestrator.rollback_to_previous_healthy_release(
            current_database_revision=current_revision, reason="rollback repetido", container_env=self._container_env(),
        )
        container_id_after_second = subprocess.run(
            ["docker", "inspect", "--format", "{{.Id}}", self.container_name], capture_output=True, text=True,
        ).stdout.strip()

        self.assertEqual(second.status, DeploymentStatus.ROLLED_BACK)
        self.assertEqual(container_id_after_first, container_id_after_second, "container nao deveria ser recriado num rollback idempotente")

    def test_rollback_blocked_when_destructive_migration_applied_since_previous_release(self):
        # Simula uma release anterior saudavel registrada com database_revision_after
        # ANTES da migration real classificada DESTRUCTIVE (20260807_0014, Fase 04);
        # o "banco atual" informado ja avancou alem dela.
        self.store.save(DeploymentState(
            deployment_id="prev-healthy-before-destructive",
            started_at_utc=datetime.now(timezone.utc),
            target_version="0.7.0",
            target_image_ref=self.image_ref,
            status=DeploymentStatus.HEALTHY,
            source="integration-test",
            database_revision_after="20260803_0013",
        ))
        with self.assertRaises(RollbackNotAllowedError):
            self.orchestrator.rollback_to_previous_healthy_release(
                current_database_revision="20260810_0015", reason="deveria ser bloqueado", container_env=self._container_env(),
            )
        self.assertFalse(docker_control.container_exists(self.container_name), "nenhum container deve ser criado quando o rollback e negado")


if __name__ == "__main__":
    unittest.main()
