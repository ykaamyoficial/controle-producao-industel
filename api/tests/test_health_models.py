from __future__ import annotations

import unittest
from datetime import datetime, timezone

from api.app.health.models import (
    HealthCheckResult,
    HealthReport,
    HealthStatus,
    OverallStatus,
    SmokeStatus,
    SmokeStepResult,
    SmokeTestReport,
)


def _check(name="database", status=HealthStatus.PASS, critical=True) -> HealthCheckResult:
    return HealthCheckResult(name=name, status=status, critical=critical, duration_ms=5, message="ok")


class HealthReportTests(unittest.TestCase):
    def test_is_ready_true_for_healthy_and_degraded(self):
        for overall in (OverallStatus.HEALTHY, OverallStatus.DEGRADED):
            report = HealthReport(
                overall_status=overall, checked_at_utc=datetime.now(timezone.utc),
                server_version="0.8.0", api_contract_version="v1", database_revision="rev",
                checks=[_check()],
            )
            self.assertTrue(report.is_ready)

    def test_is_ready_false_for_unhealthy(self):
        report = HealthReport(
            overall_status=OverallStatus.UNHEALTHY, checked_at_utc=datetime.now(timezone.utc),
            server_version="0.8.0", api_contract_version="v1", database_revision=None,
            checks=[_check(status=HealthStatus.FAIL)],
        )
        self.assertFalse(report.is_ready)

    def test_to_dict_serializes_enums_as_plain_strings(self):
        report = HealthReport(
            overall_status=OverallStatus.HEALTHY, checked_at_utc=datetime.now(timezone.utc),
            server_version="0.8.0", api_contract_version="v1", database_revision="20260810_0015",
            checks=[_check()],
        )
        payload = report.to_dict()
        self.assertEqual(payload["overall_status"], "HEALTHY")
        self.assertEqual(payload["checks"][0]["status"], "PASS")
        self.assertIsInstance(payload["checked_at_utc"], str)


class SmokeTestReportTests(unittest.TestCase):
    def test_exit_code_zero_only_on_pass(self):
        base = dict(started_at_utc=datetime.now(timezone.utc), completed_at_utc=datetime.now(timezone.utc), target_base_url="http://x", actual_server_version="0.8.0")
        passed = SmokeTestReport(status=SmokeStatus.PASS, steps=[], **base)
        failed = SmokeTestReport(status=SmokeStatus.FAIL, steps=[], **base)
        self.assertEqual(passed.exit_code, 0)
        self.assertEqual(failed.exit_code, 1)

    def test_to_dict_includes_all_steps(self):
        step = SmokeStepResult(name="health_live", status=SmokeStatus.PASS, duration_ms=3, http_status=200, message="OK")
        report = SmokeTestReport(
            status=SmokeStatus.PASS, started_at_utc=datetime.now(timezone.utc), completed_at_utc=datetime.now(timezone.utc),
            target_base_url="http://x", actual_server_version="0.8.0", steps=[step],
        )
        payload = report.to_dict()
        self.assertEqual(len(payload["steps"]), 1)
        self.assertEqual(payload["steps"][0]["name"], "health_live")


if __name__ == "__main__":
    unittest.main()
