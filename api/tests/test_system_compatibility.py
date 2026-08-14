from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from api.app.core.config import (
    API_CONTRACT_VERSION,
    API_VERSION,
    MINIMUM_DESKTOP_VERSION,
    RECOMMENDED_DESKTOP_VERSION,
    get_settings,
)
from api.app.core.exceptions import DatabaseRevisionIncompatibleError, DatabaseUnavailableError, VersionConfigurationError
from api.app.database.health import DatabaseCheck
from api.app.database.session import get_engine
from api.app.main import create_app
from api.app.modules.system import service


def _connected_check(revision: str = "20260810_0015", revision_status: str = "compatible") -> DatabaseCheck:
    return DatabaseCheck(status="connected", revision=revision, revision_status=revision_status)


class CompatibilityServiceTests(unittest.TestCase):
    """Testa api.app.modules.system.service.compatibility() isoladamente (sem HTTP)."""

    def test_builds_response_from_central_source_and_preserves_fields(self):
        async def run():
            with patch(
                "api.app.modules.system.service.database_check",
                new=AsyncMock(return_value=_connected_check()),
            ):
                return await service.compatibility()

        result = asyncio.run(run())
        self.assertEqual(result.server_version, API_VERSION)
        self.assertEqual(result.api_contract_version, API_CONTRACT_VERSION)
        self.assertEqual(result.database_revision, "20260810_0015")
        self.assertEqual(result.minimum_desktop_version, MINIMUM_DESKTOP_VERSION)
        self.assertEqual(result.recommended_desktop_version, RECOMMENDED_DESKTOP_VERSION)
        self.assertEqual(result.maintenance_mode, False)
        self.assertEqual(result.maintenance.state, "OFF")

    def test_preserves_real_observed_revision_even_when_incompatible_with_expected(self):
        # A revisao retornada deve ser a real observada, nunca inventada; quando o revision_status
        # nao e "compatible" o servico deve falhar (ver test_raises_when_revision_incompatible)
        # em vez de mascarar a divergencia com um valor default.
        async def run():
            with patch(
                "api.app.modules.system.service.database_check",
                new=AsyncMock(return_value=_connected_check(revision="old_revision", revision_status="incompatible")),
            ):
                with self.assertRaises(DatabaseRevisionIncompatibleError):
                    await service.compatibility()

        asyncio.run(run())

    def test_raises_when_database_unavailable(self):
        async def run():
            with patch(
                "api.app.modules.system.service.database_check",
                new=AsyncMock(return_value=DatabaseCheck(status="unavailable", revision=None, revision_status="unavailable")),
            ):
                with self.assertRaises(DatabaseUnavailableError):
                    await service.compatibility()

        asyncio.run(run())

    def test_raises_when_database_not_configured(self):
        async def run():
            with patch(
                "api.app.modules.system.service.database_check",
                new=AsyncMock(return_value=DatabaseCheck(status="not_configured", revision=None, revision_status="not_configured")),
            ):
                with self.assertRaises(DatabaseUnavailableError):
                    await service.compatibility()

        asyncio.run(run())

    def test_raises_when_revision_unversioned(self):
        async def run():
            with patch(
                "api.app.modules.system.service.database_check",
                new=AsyncMock(return_value=DatabaseCheck(status="connected", revision=None, revision_status="unversioned")),
            ):
                with self.assertRaises(DatabaseRevisionIncompatibleError):
                    await service.compatibility()

        asyncio.run(run())

    def test_raises_version_configuration_error_for_invalid_policy(self):
        async def run():
            with patch("api.app.modules.system.service.get_compatibility_policy", side_effect=ValueError("boom")):
                with self.assertRaises(VersionConfigurationError):
                    await service.compatibility()

        asyncio.run(run())

    def test_does_not_write_to_database(self):
        mock_check = AsyncMock(return_value=_connected_check())

        async def run():
            with patch("api.app.modules.system.service.database_check", new=mock_check):
                await service.compatibility()

        asyncio.run(run())
        mock_check.assert_awaited_once_with()


class CompatibilityEndpointTests(unittest.TestCase):
    """Testa GET /api/v1/system/compatibility via HTTP (sem banco configurado)."""

    def setUp(self):
        self.previous_env = {
            "DATABASE_URL": os.environ.get("DATABASE_URL"),
            "SECRET_KEY": os.environ.get("SECRET_KEY"),
        }
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

    def test_returns_503_without_inventing_data_when_database_not_configured(self):
        response = self.client.get("/api/v1/system/compatibility")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "DATABASE_UNAVAILABLE")

    def test_success_response_shape_has_only_documented_fields(self):
        with patch(
            "api.app.modules.system.service.database_check",
            new=AsyncMock(return_value=_connected_check()),
        ):
            response = self.client.get("/api/v1/system/compatibility")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/json")
        body = response.json()
        self.assertEqual(
            set(body.keys()),
            {
                "server_version",
                "api_contract_version",
                "database_revision",
                "minimum_desktop_version",
                "recommended_desktop_version",
                "maintenance_mode",
                "maintenance",
                "desktop_state",
                "enforcement",
                "authorized_update_version",
                "policy_revision",
                "grace_until",
                "message",
                "desktop_channel",
                "production_version",
                "pilot_version",
            },
        )
        self.assertEqual(body["server_version"], API_VERSION)
        self.assertEqual(body["api_contract_version"], API_CONTRACT_VERSION)
        self.assertEqual(body["database_revision"], "20260810_0015")
        self.assertEqual(body["minimum_desktop_version"], MINIMUM_DESKTOP_VERSION)
        self.assertEqual(body["recommended_desktop_version"], RECOMMENDED_DESKTOP_VERSION)
        self.assertEqual(body["maintenance_mode"], False)
        self.assertEqual(body["maintenance"]["state"], "OFF")
        self.assertEqual(body["desktop_channel"], "PRODUCTION")

    def test_without_installation_id_never_touches_client_installations_table(self):
        # Fase 15: sem installation_id, o heartbeat nem tenta abrir sessao de
        # banco (fallback imediato para PRODUCTION) -- endpoint continua
        # funcionando com DATABASE_URL vazio, como antes da Fase 15.
        with patch(
            "api.app.modules.system.service.database_check",
            new=AsyncMock(return_value=_connected_check()),
        ):
            response = self.client.get("/api/v1/system/compatibility")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["desktop_channel"], "PRODUCTION")

    def test_endpoint_is_read_only_and_idempotent_across_consecutive_calls(self):
        with patch(
            "api.app.modules.system.service.database_check",
            new=AsyncMock(return_value=_connected_check()),
        ):
            first = self.client.get("/api/v1/system/compatibility")
            second = self.client.get("/api/v1/system/compatibility")

        self.assertEqual(first.json(), second.json())

    def test_request_id_is_preserved_on_error(self):
        response = self.client.get("/api/v1/system/compatibility", headers={"X-Request-ID": "REQ-COMPAT-1"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["X-Request-ID"], "REQ-COMPAT-1")
        self.assertEqual(response.json()["error"]["request_id"], "REQ-COMPAT-1")

    def test_openapi_documents_the_endpoint(self):
        schema = self.client.get("/openapi.json").json()

        self.assertIn("/api/v1/system/compatibility", schema["paths"])
        operation = schema["paths"]["/api/v1/system/compatibility"]["get"]
        self.assertTrue(operation.get("summary"))
        self.assertIn("SystemCompatibilityResponse", str(operation["responses"]["200"]))


if __name__ == "__main__":
    unittest.main()
