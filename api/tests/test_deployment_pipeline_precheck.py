from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from api.app.core.config import API_VERSION
from api.app.database.health import DatabaseCheck
from api.app.deployment.service import DeploymentOrchestrator
from api.app.deployment.state_store import DeploymentStateStore
from api.app.maintenance.models import MaintenanceStateName
from api.app.maintenance.service import MaintenanceService
from api.app.maintenance.store import MaintenanceStateStore
from api.tests._deployment_test_support import FakeDocker
from scripts.deployment.precheck import PrecheckFailedError, run_precheck


class PrecheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        self.store = DeploymentStateStore(self.state_dir)
        self.orchestrator = DeploymentOrchestrator(
            state_store=self.store, lock_path=self.state_dir / ".lock", lock_timeout_seconds=60,
            container_name="controle_producao_api", network="fake-net", health_base_url="http://127.0.0.1:8000",
            docker=FakeDocker(),
        )
        # Fase 14: PRECHECK agora ativa DRAINING->ACTIVE -- servico apontado
        # para um diretorio temporario proprio, nunca o data/system_state/
        # real do repositorio, e janela zero para o teste nao dormir.
        self.maintenance_service = MaintenanceService(
            store=MaintenanceStateStore(self.state_dir / "maintenance.json"),
            lock_path=self.state_dir / ".maintenance.lock",
            lock_timeout_seconds=5,
        )
        self._connected = DatabaseCheck(status="connected", revision="20260810_0015", revision_status="compatible")

    def _run(self, **overrides):
        kwargs = dict(
            target_version=API_VERSION,
            image_repository="ghcr.io/owner/controle-producao-api",
            image_tag=API_VERSION,
            image_digest="sha256:" + "a" * 64,
            git_commit_sha="abc1234",
            docker=FakeDocker(docker_is_available=True),
            database_state_fn=lambda: self._connected,
            disk_usage_fn=lambda path: type("Usage", (), {"free": 10 * 1024 * 1024 * 1024})(),
            orchestrator=self.orchestrator,
            maintenance_service=self.maintenance_service,
            draining_window_seconds=0,
        )
        kwargs.update(overrides)
        return run_precheck(**kwargs)

    def test_success_produces_metadata_with_deployment_id(self):
        metadata = self._run()
        self.assertTrue(metadata.deployment_id)
        self.assertEqual(metadata.release_version, API_VERSION)
        self.assertEqual(metadata.image_digest, "sha256:" + "a" * 64)
        saved = self.store.load(metadata.deployment_id)
        self.assertIsNotNone(saved)

    def test_success_activates_maintenance_mode(self):
        metadata = self._run()
        state = self.maintenance_service.get_state()
        self.assertEqual(state.state, MaintenanceStateName.ACTIVE)
        self.assertEqual(state.maintenance_id, metadata.maintenance_id)

    def test_target_version_diverging_from_api_version_is_rejected(self):
        with self.assertRaises(PrecheckFailedError):
            self._run(target_version="9.9.9")

    def test_docker_unavailable_is_rejected(self):
        with self.assertRaises(PrecheckFailedError):
            self._run(docker=FakeDocker(docker_is_available=False))

    def test_database_unavailable_is_rejected(self):
        unavailable = DatabaseCheck(status="unavailable", revision=None, revision_status="unavailable")
        with self.assertRaises(PrecheckFailedError):
            self._run(database_state_fn=lambda: unavailable)

    def test_insufficient_disk_space_is_rejected(self):
        with self.assertRaises(PrecheckFailedError):
            self._run(disk_usage_fn=lambda path: type("Usage", (), {"free": 1024})(), min_free_space_mb=500)

    def test_concurrent_pending_deployment_is_rejected(self):
        self._run()
        with self.assertRaises(PrecheckFailedError):
            self._run()


if __name__ == "__main__":
    unittest.main()
