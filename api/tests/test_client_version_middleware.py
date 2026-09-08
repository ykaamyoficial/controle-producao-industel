from __future__ import annotations

import os
import unittest

from api.app.core.config import get_settings
from api.app.database.session import get_engine
from api.app.main import create_app


class ClientVersionMiddlewareTests(unittest.TestCase):
    def setUp(self):
        self.previous_env = {
            "DATABASE_URL": os.environ.get("DATABASE_URL"),
            "SECRET_KEY": os.environ.get("SECRET_KEY"),
            "CLIENT_VERSION_ENFORCEMENT_ENABLED": os.environ.get("CLIENT_VERSION_ENFORCEMENT_ENABLED"),
        }
        os.environ["DATABASE_URL"] = ""
        os.environ["SECRET_KEY"] = "test-secret-key-with-32-characters"
        os.environ.pop("CLIENT_VERSION_ENFORCEMENT_ENABLED", None)
        get_settings.cache_clear()
        get_engine.cache_clear()

        from fastapi.testclient import TestClient

        self.app = create_app()
        self.client = TestClient(self.app)

    def tearDown(self):
        for key, value in self.previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        get_engine.cache_clear()

    def _enable_enforcement(self):
        os.environ["CLIENT_VERSION_ENFORCEMENT_ENABLED"] = "true"
        get_settings.cache_clear()

    def test_disabled_by_default_business_endpoint_works_without_header(self):
        response = self.client.get("/api/v1/system/identity")
        # 503 aqui e so porque o banco nao esta configurado neste teste --
        # o ponto e que a ausencia de X-Client-Version nao virou 426.
        self.assertNotEqual(response.status_code, 426)

    def test_health_and_system_are_always_exempt_even_when_enabled(self):
        self._enable_enforcement()
        for path in ("/api/v1/system/health", "/api/v1/system/version", "/api/v1/health/live"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertNotEqual(response.status_code, 426)

    def test_missing_header_is_rejected_when_enabled(self):
        self._enable_enforcement()
        response = self.client.get("/api/v1/system/identity")
        self.assertEqual(response.status_code, 426)
        body = response.json()
        self.assertEqual(body["error"]["code"], "CLIENT_VERSION_UNSUPPORTED")
        self.assertIn("minimum_desktop_version", body["error"]["details"])

    def test_malformed_header_is_rejected_not_500(self):
        self._enable_enforcement()
        response = self.client.get("/api/v1/system/identity", headers={"X-Client-Version": "nao-e-semver"})
        self.assertEqual(response.status_code, 426)

    def test_version_below_minimum_is_rejected(self):
        self._enable_enforcement()
        response = self.client.get("/api/v1/system/identity", headers={"X-Client-Version": "0.0.1"})
        self.assertEqual(response.status_code, 426)

    def test_version_at_or_above_minimum_is_accepted(self):
        self._enable_enforcement()
        from api.app.core.config import MINIMUM_DESKTOP_VERSION

        response = self.client.get("/api/v1/system/identity", headers={"X-Client-Version": MINIMUM_DESKTOP_VERSION})
        self.assertNotEqual(response.status_code, 426)

    def test_options_preflight_is_never_blocked(self):
        self._enable_enforcement()
        response = self.client.options("/api/v1/system/identity")
        self.assertNotEqual(response.status_code, 426)


if __name__ == "__main__":
    unittest.main()
