from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from api.app.database.health import DatabaseCheck
from api.app.health.models import HealthStatus, OverallStatus
from api.app.health.service import HealthService, _overall_status
from api.app.health.models import HealthCheckResult


def _check(status: HealthStatus, *, critical: bool, name: str = "x") -> HealthCheckResult:
    return HealthCheckResult(name=name, status=status, critical=critical, duration_ms=1, message="m")


class OverallStatusTests(unittest.TestCase):
    def test_all_pass_is_healthy(self):
        self.assertEqual(_overall_status([_check(HealthStatus.PASS, critical=True), _check(HealthStatus.PASS, critical=False)]), OverallStatus.HEALTHY)

    def test_critical_fail_is_unhealthy_regardless_of_others(self):
        checks = [_check(HealthStatus.FAIL, critical=True), _check(HealthStatus.PASS, critical=False)]
        self.assertEqual(_overall_status(checks), OverallStatus.UNHEALTHY)

    def test_noncritical_warn_is_degraded_not_unhealthy(self):
        checks = [_check(HealthStatus.PASS, critical=True), _check(HealthStatus.WARN, critical=False)]
        self.assertEqual(_overall_status(checks), OverallStatus.DEGRADED)

    def test_noncritical_fail_is_degraded_not_unhealthy(self):
        checks = [_check(HealthStatus.PASS, critical=True), _check(HealthStatus.FAIL, critical=False)]
        self.assertEqual(_overall_status(checks), OverallStatus.DEGRADED)


class HealthServiceLivenessTests(unittest.TestCase):
    def test_liveness_never_touches_the_database(self):
        service = HealthService()
        with patch("api.app.health.checks.database.database_check", new=AsyncMock(side_effect=AssertionError("liveness nao pode consultar o banco"))):
            report = asyncio.run(service.liveness())
        self.assertEqual(report.overall_status, OverallStatus.HEALTHY)
        self.assertEqual(len(report.checks), 1)
        self.assertIsNone(report.database_revision)


class HealthServiceReadinessTests(unittest.TestCase):
    def _readiness_with(self, check: DatabaseCheck):
        service = HealthService()
        with patch("api.app.health.checks.database.database_check", new=AsyncMock(return_value=check)):
            return asyncio.run(service.readiness())

    def test_healthy_database_yields_healthy_overall(self):
        from api.app.core.config import EXPECTED_DATABASE_REVISION

        report = self._readiness_with(DatabaseCheck(status="connected", revision=EXPECTED_DATABASE_REVISION, revision_status="compatible"))
        self.assertEqual(report.overall_status, OverallStatus.HEALTHY)
        self.assertTrue(report.is_ready)
        self.assertEqual(report.database_revision, EXPECTED_DATABASE_REVISION)

    def test_database_failure_yields_unhealthy(self):
        report = self._readiness_with(DatabaseCheck(status="unavailable", revision=None, revision_status="unavailable"))
        self.assertEqual(report.overall_status, OverallStatus.UNHEALTHY)
        self.assertFalse(report.is_ready)

    def test_database_timeout_like_failure_does_not_hang_and_yields_unhealthy(self):
        # database_check() ja aplica seu proprio timeout (Fase 04); aqui simulamos
        # o resultado que ele produz quando estoura o timeout.
        report = self._readiness_with(DatabaseCheck(status="unavailable", revision=None, revision_status="unavailable"))
        self.assertEqual(report.overall_status, OverallStatus.UNHEALTHY)

    def test_divergent_revision_is_classified_and_yields_unhealthy(self):
        report = self._readiness_with(DatabaseCheck(status="connected", revision="20260803_0013", revision_status="incompatible"))
        self.assertEqual(report.overall_status, OverallStatus.UNHEALTHY)
        schema_checks = [c for c in report.checks if c.name == "schema_revision"]
        self.assertEqual(schema_checks[0].error_code, "SCHEMA_REVISION_MISMATCH")

    def test_report_never_leaks_secrets_in_messages(self):
        report = self._readiness_with(DatabaseCheck(status="unavailable", revision=None, revision_status="unavailable"))
        text = " ".join(check.message for check in report.checks)
        for forbidden in ("password", "PGPASSWORD", "asyncpg://", "SECRET_KEY"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
