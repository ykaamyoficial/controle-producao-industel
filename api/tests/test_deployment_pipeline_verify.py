from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from api.app.deployment.models import DeploymentStatus
from api.app.deployment.service import DeploymentOrchestrator
from api.app.deployment.state_store import DeploymentStateStore
from api.app.health.models import SmokeStatus
from api.tests._deployment_test_support import FakeDocker, fake_smoke_runner_factory
from scripts.deployment.metadata import DeploymentMetadata
from scripts.deployment.run_verify import VerifyFailedError, run_verify


class VerifyPipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        self.store = DeploymentStateStore(self.state_dir)
        self.docker = FakeDocker()
        self.orchestrator = DeploymentOrchestrator(
            state_store=self.store, lock_path=self.state_dir / ".lock", lock_timeout_seconds=60,
            container_name="controle_producao_api", network="fake-net", health_base_url="http://127.0.0.1:8000",
            docker=self.docker,
        )
        deployment = self.orchestrator.begin_deployment(
            target_version="1.0.0", target_image_ref="ghcr.io/owner/api:1.0.0", database_revision_before="20260810_0015",
        )
        self.orchestrator.mark_deploying(deployment.deployment_id)
        self.orchestrator.mark_validating(deployment.deployment_id)
        self.metadata = DeploymentMetadata(
            deployment_id=deployment.deployment_id, release_version="1.0.0", git_commit_sha="abc1234",
            image_repository="ghcr.io/owner/api", image_tag="1.0.0", api_contract_version="v1",
            expected_database_schema="20260810_0015",
        )

    def _run(self, **overrides):
        kwargs = dict(
            metadata=self.metadata, container_name="controle_producao_api", base_url="http://127.0.0.1:18000",
            orchestrator=self.orchestrator, docker=self.docker,
            runner_factory=fake_smoke_runner_factory(SmokeStatus.PASS),
            current_revision_fn=lambda: "20260810_0015",
        )
        kwargs.update(overrides)
        return run_verify(**kwargs)

    def test_successful_verify_marks_healthy(self):
        self._run()
        state = self.store.load(self.metadata.deployment_id)
        self.assertEqual(state.status, DeploymentStatus.HEALTHY)
        self.assertEqual(state.database_revision_after, "20260810_0015")

    def test_readiness_never_achieved_marks_failed_readiness_stage(self):
        unhealthy_docker = FakeDocker(healthy_after_run=False)
        with self.assertRaises(VerifyFailedError) as ctx:
            self._run(docker=unhealthy_docker)
        self.assertEqual(ctx.exception.failed_stage, "READINESS")
        state = self.store.load(self.metadata.deployment_id)
        self.assertEqual(state.status, DeploymentStatus.FAILED)
        self.assertEqual(state.failed_stage, "READINESS")

    def test_smoke_failure_marks_failed_smoke_stage(self):
        with self.assertRaises(VerifyFailedError) as ctx:
            self._run(runner_factory=fake_smoke_runner_factory(SmokeStatus.FAIL))
        self.assertEqual(ctx.exception.failed_stage, "SMOKE")

    def test_version_mismatch_marks_failed_smoke_stage(self):
        with self.assertRaises(VerifyFailedError) as ctx:
            self._run(runner_factory=fake_smoke_runner_factory(SmokeStatus.PASS, actual_version_override="0.9.9"))
        self.assertEqual(ctx.exception.failed_stage, "SMOKE")


if __name__ == "__main__":
    unittest.main()
