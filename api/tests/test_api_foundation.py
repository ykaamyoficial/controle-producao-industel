from __future__ import annotations

import os
import unittest

from pydantic import ValidationError

from api.app.core.config import API_STAGE, API_VERSION, Settings, get_settings
from api.app.database.session import get_engine
from api.app.main import create_app


class ApiFoundationTests(unittest.TestCase):
    def setUp(self):
        self.previous_env = {
            "DATABASE_URL": os.environ.get("DATABASE_URL"),
            "SECRET_KEY": os.environ.get("SECRET_KEY"),
            "CORS_ALLOWED_ORIGINS": os.environ.get("CORS_ALLOWED_ORIGINS"),
        }
        os.environ["DATABASE_URL"] = ""
        os.environ["SECRET_KEY"] = ""
        os.environ["CORS_ALLOWED_ORIGINS"] = ""
        get_settings.cache_clear()
        get_engine.cache_clear()

        from fastapi import Query
        from fastapi.testclient import TestClient

        app = create_app()

        @app.get("/test/validation")
        async def validation_endpoint(value: int = Query(...)):
            return {"value": value}

        self.client = TestClient(app)

    def tearDown(self):
        for key, value in self.previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        get_engine.cache_clear()

    def test_health_check(self):
        response = self.client.get("/api/v1/system/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "healthy", "service": "controle-producao-api"},
        )

    def test_readiness_without_database_url(self):
        response = self.client.get("/api/v1/system/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ready")
        self.assertEqual(response.json()["database"], "not_configured")
        self.assertEqual(response.json()["mode"], "foundation")

    def test_version_endpoint_uses_api_version(self):
        response = self.client.get("/api/v1/system/version")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["api_version"], API_VERSION)
        self.assertEqual(response.json()["api_stage"], API_STAGE)
        self.assertIsNone(response.json()["database_revision"])
        self.assertEqual(response.json()["database_status"], "not_configured")

    def test_identity_requires_database(self):
        response = self.client.get("/api/v1/system/identity")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "DATABASE_UNAVAILABLE")

    def test_missing_route_has_standard_error_and_request_id(self):
        response = self.client.get("/rota-inexistente")

        self.assertEqual(response.status_code, 404)
        body = response.json()
        self.assertEqual(body["error"]["code"], "NOT_FOUND")
        self.assertIn("request_id", body["error"])
        self.assertEqual(response.headers["X-Request-ID"], body["error"]["request_id"])

    def test_validation_error_has_standard_shape(self):
        response = self.client.get("/test/validation?value=abc")

        self.assertEqual(response.status_code, 422)
        body = response.json()
        self.assertEqual(body["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(body["error"]["message"], "Dados invalidos na requisicao.")

    def test_request_id_is_generated_and_returned(self):
        response = self.client.get("/api/v1/system/health")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get("X-Request-ID"))

    def test_valid_request_id_is_reused(self):
        response = self.client.get("/api/v1/system/health", headers={"X-Request-ID": "REQ-123"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Request-ID"], "REQ-123")

    def test_invalid_request_id_is_replaced(self):
        response = self.client.get("/api/v1/system/health", headers={"X-Request-ID": "../bad"})

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.headers["X-Request-ID"], "../bad")

    def test_errors_do_not_expose_secrets(self):
        os.environ["SECRET_KEY"] = "super-secret-test-value"
        get_settings.cache_clear()
        response = self.client.get("/rota-inexistente")
        raw = response.text

        self.assertNotIn("super-secret-test-value", raw)
        self.assertNotIn("DATABASE_URL", raw)
        self.assertNotIn("Traceback", raw)

    def test_settings_load_without_database_url(self):
        settings = Settings(DATABASE_URL="", SECRET_KEY="")

        self.assertEqual(settings.database_url, "")
        self.assertEqual(settings.secret_key, "")
        self.assertEqual(settings.api_port, 8000)
        self.assertEqual(settings.operational_company_code, "local-dev")
        self.assertEqual(settings.operational_environment_type, "production")

    def test_invalid_configuration_is_rejected(self):
        with self.assertRaises(ValidationError):
            Settings(API_LOG_LEVEL="LOUD")


if __name__ == "__main__":
    unittest.main()
