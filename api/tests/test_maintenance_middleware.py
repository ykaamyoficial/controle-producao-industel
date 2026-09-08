from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from api.app.core.config import get_settings
from api.app.database.session import get_engine
from api.app.main import create_app
from api.app.maintenance.middleware import is_allowlisted
from api.app.maintenance.models import MaintenanceReasonCode
from api.app.maintenance.service import build_default_service


class AllowlistUnitTests(unittest.TestCase):
    def test_health_maintenance_compatibility_updates_are_allowlisted(self):
        for path in (
            "/api/v1/health/live",
            "/api/v1/health/ready",
            "/api/v1/system/maintenance",
            "/api/v1/system/maintenance/admin/activate",
            "/api/v1/system/compatibility",
            "/api/v1/updates/desktop",
            "/api/v1/updates/desktop/sync",
        ):
            self.assertTrue(is_allowlisted(path), msg=path)

    def test_business_routes_are_not_allowlisted(self):
        for path in ("/api/v1/proposals", "/api/v1/production", "/api/v1/fiscal", "/api/v1/users", "/api/v1/chat"):
            self.assertFalse(is_allowlisted(path), msg=path)

    def test_system_identity_and_version_are_not_allowlisted(self):
        # Deliberado (Secao 16: "nao use prefixos amplos demais") -- so o
        # subconjunto explicitamente listado no prompt tecnico fica aberto.
        for path in ("/api/v1/system/identity", "/api/v1/system/version"):
            self.assertFalse(is_allowlisted(path), msg=path)


class MaintenanceMiddlewareHttpTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        self._previous_env = {
            "DATABASE_URL": os.environ.get("DATABASE_URL"),
            "SECRET_KEY": os.environ.get("SECRET_KEY"),
            "MAINTENANCE_STATE_DIR": os.environ.get("MAINTENANCE_STATE_DIR"),
        }
        os.environ["DATABASE_URL"] = ""
        os.environ["SECRET_KEY"] = ""
        os.environ["MAINTENANCE_STATE_DIR"] = str(self.state_dir)
        get_settings.cache_clear()
        get_engine.cache_clear()
        self.service = build_default_service(settings=get_settings())
        # raise_server_exceptions=False: quando o middleware NAO bloqueia, a
        # requisicao segue ate a dependencia de banco, que levanta RuntimeError
        # porque DATABASE_URL esta vazio neste teste (nada a ver com
        # manutencao) -- queremos inspecionar essa resposta (500, nao 503),
        # nao deixar o TestClient repropagar a excecao para o teste.
        self.client = TestClient(create_app(), raise_server_exceptions=False)

    def tearDown(self):
        for key, value in self._previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        get_engine.cache_clear()

    def _activate(self, **overrides):
        kwargs = dict(reason_code=MaintenanceReasonCode.EMERGENCY_MAINTENANCE, message="Em manutencao", expected_end_at=None, activated_by="tester")
        kwargs.update(overrides)
        return self.service.activate_maintenance(**kwargs)


class OffStateTests(MaintenanceMiddlewareHttpTestCase):
    def test_off_does_not_block_business_route(self):
        response = self.client.post("/api/v1/proposals", json={})
        self.assertNotEqual(response.status_code, 503)
        self.assertNotIn("MAINTENANCE_MODE_ACTIVE", response.text)


class ScheduledStateTests(MaintenanceMiddlewareHttpTestCase):
    def test_scheduled_does_not_block_business_route(self):
        self.service.schedule_maintenance(
            reason_code=MaintenanceReasonCode.DEPLOYMENT, message="Manutencao programada",
            scheduled_start_at=datetime.now(timezone.utc) + timedelta(hours=2),
            expected_end_at=None, activated_by="tester",
        )
        response = self.client.post("/api/v1/proposals", json={})
        self.assertNotEqual(response.status_code, 503)
        self.assertNotIn("MAINTENANCE_MODE_ACTIVE", response.text)

    def test_scheduled_state_is_exposed_for_client_side_warning(self):
        self.service.schedule_maintenance(
            reason_code=MaintenanceReasonCode.DEPLOYMENT, message="Manutencao programada",
            scheduled_start_at=datetime.now(timezone.utc) + timedelta(hours=2),
            expected_end_at=None, activated_by="tester",
        )
        response = self.client.get("/api/v1/system/maintenance")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "SCHEDULED")


class DrainingStateTests(MaintenanceMiddlewareHttpTestCase):
    def test_draining_blocks_mutating_business_request(self):
        self.service.begin_draining(
            reason_code=MaintenanceReasonCode.DEPLOYMENT, message="Esvaziando",
            expected_end_at=None, activated_by="tester",
        )
        response = self.client.post("/api/v1/proposals", json={})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "MAINTENANCE_MODE_ACTIVE")

    def test_draining_does_not_block_read_business_request(self):
        self.service.begin_draining(
            reason_code=MaintenanceReasonCode.DEPLOYMENT, message="Esvaziando",
            expected_end_at=None, activated_by="tester",
        )
        response = self.client.get("/api/v1/proposals")
        # DB nao configurado -> falha por outro motivo, mas nunca pela
        # manutencao (Secao 14: DRAINING permite leituras).
        self.assertNotEqual(response.json().get("error", {}).get("code"), "MAINTENANCE_MODE_ACTIVE")


class ActiveStateTests(MaintenanceMiddlewareHttpTestCase):
    def test_active_blocks_business_mutation_with_standard_503_payload(self):
        state = self._activate()
        response = self.client.post("/api/v1/proposals", json={})

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body["error"]["code"], "MAINTENANCE_MODE_ACTIVE")
        self.assertEqual(body["error"]["details"]["maintenance_id"], state.maintenance_id)
        self.assertEqual(body["error"]["details"]["state"], "ACTIVE")
        self.assertIn("retry_after_seconds", body["error"]["details"])
        self.assertNotIn("Traceback", response.text)

    def test_active_blocks_business_read_too(self):
        self._activate()
        response = self.client.get("/api/v1/proposals")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "MAINTENANCE_MODE_ACTIVE")

    def test_active_returns_retry_after_header(self):
        self._activate()
        response = self.client.post("/api/v1/proposals", json={})
        self.assertIn("Retry-After", response.headers)
        self.assertTrue(response.headers["Retry-After"].isdigit())

    def test_active_never_returns_500_for_the_block_itself(self):
        self._activate()
        response = self.client.post("/api/v1/proposals", json={})
        self.assertEqual(response.status_code, 503)

    def test_active_permits_health_live(self):
        self._activate()
        response = self.client.get("/api/v1/health/live")
        self.assertEqual(response.status_code, 200)

    def test_active_permits_system_maintenance(self):
        self._activate()
        response = self.client.get("/api/v1/system/maintenance")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "ACTIVE")

    def test_active_permits_system_compatibility_route_through(self):
        self._activate()
        response = self.client.get("/api/v1/system/compatibility")
        # Permanece acessivel: nao e bloqueado pelo middleware (a falha 503
        # observada aqui e DATABASE_UNAVAILABLE, nao MAINTENANCE_MODE_ACTIVE).
        self.assertNotEqual(response.json().get("error", {}).get("code"), "MAINTENANCE_MODE_ACTIVE")

    def test_active_permits_updates_discovery(self):
        self._activate()
        response = self.client.get("/api/v1/updates/desktop")
        self.assertEqual(response.status_code, 200)

    def test_active_does_not_block_openapi_or_docs(self):
        self._activate()
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)

    def test_preflight_options_is_never_blocked(self):
        self._activate()
        response = self.client.options("/api/v1/proposals", headers={
            "Origin": "http://localhost",
            "Access-Control-Request-Method": "POST",
        })
        self.assertNotEqual(response.status_code, 503)


class RecoveryStateTests(MaintenanceMiddlewareHttpTestCase):
    def test_recovery_still_blocks_business_operation(self):
        self._activate()
        self.service.begin_recovery(activated_by="tester")
        response = self.client.post("/api/v1/proposals", json={})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["details"]["state"], "RECOVERY")

    def test_recovery_still_permits_health_live_and_ready(self):
        self._activate()
        self.service.begin_recovery(activated_by="tester")
        self.assertEqual(self.client.get("/api/v1/health/live").status_code, 200)
        ready = self.client.get("/api/v1/health/ready")
        self.assertEqual(ready.json()["maintenance_state"], "RECOVERY")


if __name__ == "__main__":
    unittest.main()
