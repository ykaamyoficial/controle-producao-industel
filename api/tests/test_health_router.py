from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api.app.core.config import get_settings
from api.app.database.session import get_engine
from api.app.health.models import HealthCheckResult, HealthReport, HealthStatus, OverallStatus
from api.app.main import create_app


def _report(overall: OverallStatus, *, checks=None) -> HealthReport:
    return HealthReport(
        overall_status=overall,
        checked_at_utc=datetime.now(timezone.utc),
        server_version="0.8.0",
        api_contract_version="v1",
        database_revision="20260810_0015",
        checks=checks or [HealthCheckResult(name="database", status=HealthStatus.PASS, critical=True, duration_ms=1, message="ok")],
    )


class HealthRouterTests(unittest.TestCase):
    def setUp(self):
        self.previous_env = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "SECRET_KEY": os.environ.get("SECRET_KEY")}
        os.environ["DATABASE_URL"] = ""
        os.environ["SECRET_KEY"] = ""
        get_settings.cache_clear()
        get_engine.cache_clear()
        self.client = TestClient(create_app())

    def tearDown(self):
        for key, value in self.previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        get_engine.cache_clear()

    def test_live_returns_200_and_never_touches_database(self):
        with patch("api.app.health.checks.database.database_check", new=AsyncMock(side_effect=AssertionError("live nao pode chamar database_check"))):
            response = self.client.get("/api/v1/health/live")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "alive")
        self.assertIn("server_version", body)

    def test_ready_returns_200_when_healthy(self):
        with patch("api.app.modules.health.router._service.readiness", new=AsyncMock(return_value=_report(OverallStatus.HEALTHY))):
            response = self.client.get("/api/v1/health/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["overall_status"], "HEALTHY")

    def test_ready_returns_200_when_degraded(self):
        with patch("api.app.modules.health.router._service.readiness", new=AsyncMock(return_value=_report(OverallStatus.DEGRADED))):
            response = self.client.get("/api/v1/health/ready")
        self.assertEqual(response.status_code, 200)

    def test_ready_returns_503_when_unhealthy_never_200_with_error_status(self):
        with patch("api.app.modules.health.router._service.readiness", new=AsyncMock(return_value=_report(OverallStatus.UNHEALTHY))):
            response = self.client.get("/api/v1/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["overall_status"], "UNHEALTHY")

    def test_ready_without_database_configured_returns_503(self):
        response = self.client.get("/api/v1/health/ready")
        self.assertEqual(response.status_code, 503)

    def test_ready_response_includes_checks_list_with_typed_fields(self):
        response = self.client.get("/api/v1/health/ready")
        body = response.json()
        self.assertIn("checks", body)
        self.assertTrue(body["checks"])
        for check in body["checks"]:
            self.assertIn("name", check)
            self.assertIn("status", check)
            self.assertIn("critical", check)
            self.assertIn("duration_ms", check)


if __name__ == "__main__":
    unittest.main()
