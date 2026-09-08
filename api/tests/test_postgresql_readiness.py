from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient

from api.app.core.config import get_settings
from api.app.database.session import get_engine
from api.app.main import create_app


class PostgreSQLReadinessUnitTests(unittest.TestCase):
    def setUp(self):
        self.previous = {
            "DATABASE_URL": os.environ.get("DATABASE_URL"),
            "DATABASE_CONNECT_TIMEOUT": os.environ.get("DATABASE_CONNECT_TIMEOUT"),
        }

    def tearDown(self):
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        get_engine.cache_clear()

    def test_readiness_with_unavailable_database_returns_503_without_secret(self):
        os.environ["DATABASE_URL"] = "postgresql+asyncpg://user:super-secret@127.0.0.1:1/missing_db"
        os.environ["DATABASE_CONNECT_TIMEOUT"] = "1"
        get_settings.cache_clear()
        get_engine.cache_clear()

        client = TestClient(create_app())
        response = client.get("/api/v1/system/ready", headers={"X-Request-ID": "db-down-test"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "DATABASE_UNAVAILABLE")
        self.assertEqual(response.json()["error"]["request_id"], "db-down-test")
        self.assertNotIn("super-secret", response.text)
        self.assertNotIn("127.0.0.1", response.text)


if __name__ == "__main__":
    unittest.main()
