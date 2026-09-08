from __future__ import annotations

import unittest
from datetime import datetime, timezone

from api.app.deployment.models import DeploymentState, DeploymentStatus
from scripts.deployment.summarize import build_deployment_result

NOW = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)


def _state(**overrides) -> DeploymentState:
    base = dict(
        deployment_id="deploy_1", started_at_utc=NOW, target_version="1.0.0",
        target_image_ref="ghcr.io/owner/api:1.0.0", status=DeploymentStatus.HEALTHY, source="github-actions",
    )
    base.update(overrides)
    return DeploymentState(**base)


class BuildDeploymentResultTests(unittest.TestCase):
    def test_healthy_deployment_is_success(self):
        deployment = _state(status=DeploymentStatus.HEALTHY, backup_id="predeploy_1", database_revision_after="rev2")
        result = build_deployment_result(deployment, None)
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.backup_id, "predeploy_1")
        self.assertEqual(result.database_schema_after, "rev2")

    def test_failed_deployment_without_rollback_is_failed(self):
        deployment = _state(status=DeploymentStatus.FAILED, failed_stage="SMOKE", error_message="smoke falhou")
        result = build_deployment_result(deployment, None)
        self.assertEqual(result.status, "FAILED")
        self.assertEqual(result.failed_stage, "SMOKE")
        self.assertIsNone(result.rollback_result)

    def test_failed_deployment_with_successful_rollback_is_rolled_back(self):
        deployment = _state(status=DeploymentStatus.FAILED, failed_stage="READINESS")
        rollback = _state(deployment_id="rollback_1", status=DeploymentStatus.ROLLED_BACK, target_version="0.9.0")
        result = build_deployment_result(deployment, rollback)
        self.assertEqual(result.status, "ROLLED_BACK")
        self.assertEqual(result.rollback_result, "ROLLED_BACK")

    def test_manual_intervention_on_deployment_takes_precedence(self):
        deployment = _state(status=DeploymentStatus.MANUAL_INTERVENTION_REQUIRED, rollback_allowed=False)
        result = build_deployment_result(deployment, None)
        self.assertEqual(result.status, "MANUAL_INTERVENTION")

    def test_manual_intervention_on_rollback_propagates(self):
        deployment = _state(status=DeploymentStatus.FAILED, failed_stage="SMOKE")
        rollback = _state(deployment_id="rollback_1", status=DeploymentStatus.MANUAL_INTERVENTION_REQUIRED)
        result = build_deployment_result(deployment, rollback)
        self.assertEqual(result.status, "MANUAL_INTERVENTION")

    def test_markdown_contains_key_fields(self):
        deployment = _state(status=DeploymentStatus.HEALTHY, previous_version="0.9.0", backup_id="predeploy_1")
        result = build_deployment_result(deployment, None)
        markdown = result.to_markdown()
        self.assertIn("SUCCESS", markdown)
        self.assertIn("0.9.0", markdown)
        self.assertIn("predeploy_1", markdown)


if __name__ == "__main__":
    unittest.main()
