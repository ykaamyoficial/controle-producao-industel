from __future__ import annotations

import asyncio
import os
import unittest

from alembic import command
from fastapi.testclient import TestClient

from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine
from api.app.health.smoke import SmokeTestRunner
from api.app.main import create_app
from api.tests._health_test_support import SmokeHttpAdapterOverTestClient
from api.tests._migration_test_support import TEST_DATABASE_URL, alembic_config, integration_enabled

_SKIP_REASON = "Testes de integracao de health/smoke exigem APP_ENV=test e POSTGRES_TEST_DATABASE_URL (mesmo guard de seguranca das Fases 04/05)."


def _swap_env():
    previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV")}
    os.environ["APP_ENV"] = "test"
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    get_settings.cache_clear()
    get_engine.cache_clear()
    return previous


def _restore_env(previous):
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    get_settings.cache_clear()
    get_engine.cache_clear()


@unittest.skipUnless(integration_enabled(), _SKIP_REASON)
class ScenarioAHealthyApiAndDatabaseTests(unittest.TestCase):
    """Cenario A (Secao 27): API + DB corretos -> live 200, ready 200, smoke PASS."""

    @classmethod
    def setUpClass(cls):
        cls.previous_env = _swap_env()
        command.upgrade(alembic_config(), "head")

    @classmethod
    def tearDownClass(cls):
        asyncio.run(dispose_engine())
        _restore_env(cls.previous_env)

    def test_live_ready_and_smoke_all_succeed(self):
        client = TestClient(create_app())

        live = client.get("/api/v1/health/live")
        self.assertEqual(live.status_code, 200)
        self.assertEqual(live.json()["status"], "alive")

        ready = client.get("/api/v1/health/ready")
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()["overall_status"], "HEALTHY")

        runner = SmokeTestRunner(base_url="http://testserver", http_client=SmokeHttpAdapterOverTestClient(client))
        report = runner.run()
        self.assertEqual(report.status.value, "PASS")
        self.assertEqual(report.exit_code, 0)
        self.assertTrue(all(step.status.value == "PASS" for step in report.steps))


@unittest.skipUnless(integration_enabled(), _SKIP_REASON)
class ScenarioBDatabaseUnavailableTests(unittest.TestCase):
    """Cenario B: DB indisponivel -> live 200, ready 503, smoke FAIL."""

    def setUp(self):
        self.previous_env = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = ""  # nao configurada -> database_check() = not_configured
        get_settings.cache_clear()
        get_engine.cache_clear()

    def tearDown(self):
        asyncio.run(dispose_engine())
        _restore_env(self.previous_env)

    def test_live_ok_but_ready_and_smoke_fail(self):
        client = TestClient(create_app())

        live = client.get("/api/v1/health/live")
        self.assertEqual(live.status_code, 200)

        ready = client.get("/api/v1/health/ready")
        self.assertEqual(ready.status_code, 503)
        self.assertEqual(ready.json()["overall_status"], "UNHEALTHY")

        runner = SmokeTestRunner(base_url="http://testserver", http_client=SmokeHttpAdapterOverTestClient(client))
        report = runner.run()
        self.assertEqual(report.status.value, "FAIL")
        self.assertEqual(report.exit_code, 1)
        ready_step = next(s for s in report.steps if s.name == "health_ready")
        self.assertEqual(ready_step.http_status, 503)


@unittest.skipUnless(integration_enabled(), _SKIP_REASON)
class ScenarioCSchemaRevisionDivergentTests(unittest.TestCase):
    """Cenario C: schema/revision divergente -> live 200, ready 503, smoke FAIL."""

    @classmethod
    def setUpClass(cls):
        cls.previous_env = _swap_env()
        command.upgrade(alembic_config(), "head")
        # Downgrade deliberado para uma revisao anterior conhecida, simulando um
        # banco que ainda nao recebeu a ultima migration da release.
        command.downgrade(alembic_config(), "20260803_0013")

    @classmethod
    def tearDownClass(cls):
        command.upgrade(alembic_config(), "head")
        asyncio.run(dispose_engine())
        _restore_env(cls.previous_env)

    def test_live_ok_but_ready_and_smoke_fail_on_schema_mismatch(self):
        client = TestClient(create_app())

        live = client.get("/api/v1/health/live")
        self.assertEqual(live.status_code, 200)

        ready = client.get("/api/v1/health/ready")
        self.assertEqual(ready.status_code, 503)
        schema_checks = [c for c in ready.json()["checks"] if c["name"] == "schema_revision"]
        self.assertEqual(schema_checks[0]["status"], "FAIL")
        self.assertEqual(schema_checks[0]["error_code"], "SCHEMA_REVISION_MISMATCH")

        runner = SmokeTestRunner(base_url="http://testserver", http_client=SmokeHttpAdapterOverTestClient(client))
        report = runner.run()
        self.assertEqual(report.status.value, "FAIL")
        self.assertEqual(report.exit_code, 1)


if __name__ == "__main__":
    unittest.main()
