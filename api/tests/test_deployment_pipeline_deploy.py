from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from api.app.backup.models import BackupResult, BackupStatus, ValidationStatus
from api.app.deployment.models import DeploymentStatus
from api.app.deployment.service import DeploymentOrchestrator
from api.app.deployment.state_store import DeploymentStateStore
from api.tests._deployment_test_support import FakeDocker
from scripts.deployment.metadata import DeploymentMetadata
from scripts.deployment.run_deploy import DeployFailedError, run_deploy


def _backup_result(*, valid: bool = True, backup_id: str = "predeploy_20260811T120000Z_ok") -> BackupResult:
    if valid:
        return BackupResult(
            status=BackupStatus.SUCCESS, backup_id=backup_id, created_at_utc=datetime.now(timezone.utc),
            database_name="controle_producao", server_version="1.0.0", validation_status=ValidationStatus.VALID,
        )
    return BackupResult(
        status=BackupStatus.FAILED, backup_id=backup_id, created_at_utc=datetime.now(timezone.utc),
        database_name="controle_producao", server_version="1.0.0", validation_status=ValidationStatus.INVALID,
        error_code="PG_DUMP_FAILED", error_message="falha simulada",
    )


class _FakeBackupService:
    def __init__(self, result: BackupResult):
        self._result = result

    def run(self, **kwargs) -> BackupResult:
        return self._result


class DeployPipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        self.store = DeploymentStateStore(self.state_dir)
        self.docker = FakeDocker(pulled_digest="sha256:" + "a" * 64)
        self.orchestrator = DeploymentOrchestrator(
            state_store=self.store, lock_path=self.state_dir / ".lock", lock_timeout_seconds=60,
            container_name="controle_producao_api", network="fake-net", health_base_url="http://127.0.0.1:8000",
            docker=self.docker,
        )
        self.deployment = self.orchestrator.begin_deployment(
            target_version="1.0.0", target_image_ref="ghcr.io/owner/api:1.0.0",
            target_image_digest="sha256:" + "a" * 64, database_revision_before="20260810_0015",
        )
        self.metadata = DeploymentMetadata(
            deployment_id=self.deployment.deployment_id, release_version="1.0.0", git_commit_sha="abc1234",
            image_repository="ghcr.io/owner/api", image_tag="1.0.0", image_digest="sha256:" + "a" * 64,
            api_contract_version="v1", expected_database_schema="20260810_0015",
        )

    def _run(self, **overrides):
        kwargs = dict(
            metadata=self.metadata, container_name="controle_producao_api", network="fake-net",
            container_env={"DATABASE_URL": "postgresql+asyncpg://x"},
            orchestrator=self.orchestrator, backup_service=_FakeBackupService(_backup_result()),
            docker=self.docker, current_revision_fn=lambda: "20260810_0015",
        )
        kwargs.update(overrides)
        return run_deploy(**kwargs)

    def test_successful_deploy_reaches_validating_and_swaps_container(self):
        self._run()
        state = self.store.load(self.metadata.deployment_id)
        self.assertEqual(state.status, DeploymentStatus.VALIDATING)
        self.assertEqual(state.backup_id, "predeploy_20260811T120000Z_ok")
        self.assertEqual(self.docker.run_args[-1]["image_ref"], "ghcr.io/owner/api:1.0.0")

    def test_invalid_backup_blocks_deploy_before_touching_docker(self):
        with self.assertRaises(DeployFailedError) as ctx:
            self._run(backup_service=_FakeBackupService(_backup_result(valid=False)))
        self.assertEqual(ctx.exception.failed_stage, "BACKUP")
        state = self.store.load(self.metadata.deployment_id)
        self.assertEqual(state.status, DeploymentStatus.FAILED)
        self.assertEqual(state.failed_stage, "BACKUP")
        self.assertEqual(len(self.docker.calls), 0, "nenhuma acao Docker deve ocorrer quando o backup e invalido")

    def test_digest_mismatch_after_pull_blocks_deploy(self):
        mismatched_docker = FakeDocker(pulled_digest="sha256:" + "f" * 64)
        with self.assertRaises(DeployFailedError) as ctx:
            self._run(docker=mismatched_docker)
        self.assertEqual(ctx.exception.failed_stage, "PULL")
        state = self.store.load(self.metadata.deployment_id)
        self.assertEqual(state.failed_stage, "PULL")
        self.assertEqual(mismatched_docker.stopped, [], "nao deve trocar o container se o digest divergir")

    def test_migration_failure_blocks_deploy_before_container_swap(self):
        failing_docker = FakeDocker(pulled_digest="sha256:" + "a" * 64, ephemeral_returncode=1, ephemeral_stderr="alembic upgrade falhou")
        with self.assertRaises(DeployFailedError) as ctx:
            self._run(docker=failing_docker)
        self.assertEqual(ctx.exception.failed_stage, "MIGRATION")
        self.assertEqual(failing_docker.stopped, [])

    def test_revision_mismatch_after_migration_blocks_promotion(self):
        docker = FakeDocker(pulled_digest="sha256:" + "a" * 64)
        # 1a chamada (preflight/antes) == revisao esperada; 2a chamada (pos-migration) diverge.
        calls = iter(["20260810_0015", "20260803_0013"])
        with self.assertRaises(DeployFailedError) as ctx:
            self._run(docker=docker, current_revision_fn=lambda: next(calls))
        self.assertEqual(ctx.exception.failed_stage, "MIGRATION")
        self.assertEqual(docker.stopped, [])


if __name__ == "__main__":
    unittest.main()
