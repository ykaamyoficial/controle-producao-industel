from __future__ import annotations

import asyncio
import os
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from api.app.core.config import get_settings
from api.app.core.versioning import EnforcementMode
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.main import create_app
from api.app.updates.policy import DEFAULT_POLICY, get_policy, save_policy

TEST_DATABASE_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL", "")


def _database_name(url: str) -> str:
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    return parsed.path.lstrip("/")


def _integration_enabled() -> bool:
    return bool(TEST_DATABASE_URL) and os.environ.get("APP_ENV") == "test" and "test" in _database_name(TEST_DATABASE_URL).lower()


def _alembic_config() -> Config:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "api" / "alembic.ini"))
    config.set_main_option("script_location", str(root / "api" / "alembic"))
    return config


@unittest.skipUnless(_integration_enabled(), "Exige APP_ENV=test e POSTGRES_TEST_DATABASE_URL.")
class PolicyStoreIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV"), "SECRET_KEY": os.environ.get("SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "updates-policy-integration-secret-key-32chars"
        get_settings.cache_clear()
        get_engine.cache_clear()
        command.downgrade(_alembic_config(), "base")
        command.upgrade(_alembic_config(), "head")

    @classmethod
    def tearDownClass(cls):
        command.upgrade(_alembic_config(), "head")
        asyncio.run(dispose_engine())
        for key, value in cls.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        get_engine.cache_clear()

    def setUp(self):
        asyncio.run(self._truncate_metadata())

    async def _truncate_metadata(self):
        from sqlalchemy import text

        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE system_metadata RESTART IDENTITY CASCADE"))

    def test_get_policy_returns_default_when_nothing_saved(self):
        record = asyncio.run(self._get())
        self.assertEqual(record.enforcement, DEFAULT_POLICY.enforcement)
        self.assertEqual(record.policy_revision, 0)

    async def _get(self):
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            return await get_policy(session)

    def test_save_then_get_round_trips(self):
        asyncio.run(self._save(EnforcementMode.RECOMMENDED, "3.2.0", None, "atualize"))
        record = asyncio.run(self._get())
        self.assertEqual(record.enforcement, EnforcementMode.RECOMMENDED)
        self.assertEqual(record.authorized_release_version, "3.2.0")
        self.assertEqual(record.message, "atualize")
        self.assertEqual(record.policy_revision, 1)

    async def _save(self, enforcement, authorized_release_version, grace_until, message):
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            return await save_policy(session, enforcement=enforcement, authorized_release_version=authorized_release_version, grace_until=grace_until, message=message)

    def test_revision_increments_only_when_content_actually_changes(self):
        asyncio.run(self._save(EnforcementMode.OPTIONAL, None, None, "v1"))
        asyncio.run(self._save(EnforcementMode.OPTIONAL, None, None, "v1"))  # identico -- nao muda
        record = asyncio.run(self._get())
        self.assertEqual(record.policy_revision, 1)

        asyncio.run(self._save(EnforcementMode.REQUIRED, None, None, "v1"))  # enforcement mudou
        record2 = asyncio.run(self._get())
        self.assertEqual(record2.policy_revision, 2)

    def test_invalid_authorized_release_version_is_rejected(self):
        from api.app.updates.policy import PolicyValidationError

        with self.assertRaises(PolicyValidationError):
            asyncio.run(self._save(EnforcementMode.REQUIRED, "not-a-version", None, ""))


@unittest.skipUnless(_integration_enabled(), "Exige APP_ENV=test e POSTGRES_TEST_DATABASE_URL.")
class CompatibilityEndpointPolicyIntegrationTests(unittest.TestCase):
    """GET /system/compatibility?desktop_version=... considerando a politica
    persistida (end-to-end via HTTP, sem mocks na fronteira)."""

    @classmethod
    def setUpClass(cls):
        cls.previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV"), "SECRET_KEY": os.environ.get("SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "updates-policy-integration-secret-key-32chars"
        get_settings.cache_clear()
        get_engine.cache_clear()
        command.downgrade(_alembic_config(), "base")
        command.upgrade(_alembic_config(), "head")

    @classmethod
    def tearDownClass(cls):
        command.upgrade(_alembic_config(), "head")
        asyncio.run(dispose_engine())
        for key, value in cls.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        get_engine.cache_clear()

    def setUp(self):
        asyncio.run(self._truncate_metadata())
        self.client = TestClient(create_app())

    async def _truncate_metadata(self):
        from sqlalchemy import text

        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE system_metadata RESTART IDENTITY CASCADE"))

    async def _save(self, enforcement, authorized_release_version, grace_until, message):
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            from api.app.updates.policy import save_policy

            return await save_policy(session, enforcement=enforcement, authorized_release_version=authorized_release_version, grace_until=grace_until, message=message)

    def test_no_policy_saved_is_backward_compatible_and_never_blocks(self):
        response = self.client.get("/api/v1/system/compatibility?desktop_version=2.5.2")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["enforcement"], "NONE")
        self.assertEqual(body["policy_revision"], 0)
        self.assertIn(body["desktop_state"], ("COMPATIBLE", "UPDATE_AVAILABLE"))

    def test_old_client_without_desktop_version_still_gets_original_fields(self):
        response = self.client.get("/api/v1/system/compatibility")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        for key in ("server_version", "api_contract_version", "database_revision", "minimum_desktop_version", "recommended_desktop_version", "maintenance_mode"):
            self.assertIn(key, body)
        self.assertIsNone(body["desktop_state"])

    def test_recommended_enforcement_reflected_in_response(self):
        asyncio.run(self._save(EnforcementMode.RECOMMENDED, None, None, "Nova versao recomendada"))
        response = self.client.get("/api/v1/system/compatibility?desktop_version=2.5.2")
        body = response.json()
        self.assertEqual(body["enforcement"], "RECOMMENDED")
        self.assertEqual(body["message"], "Nova versao recomendada")
        self.assertGreaterEqual(body["policy_revision"], 1)

    def test_blocked_enforcement_makes_even_compatible_version_incompatible(self):
        from api.app.core.config import MINIMUM_DESKTOP_VERSION

        asyncio.run(self._save(EnforcementMode.BLOCKED, None, None, "Emergencia de seguranca"))
        response = self.client.get(f"/api/v1/system/compatibility?desktop_version={MINIMUM_DESKTOP_VERSION}")
        body = response.json()
        self.assertEqual(body["desktop_state"], "INCOMPATIBLE")

    def test_invalid_desktop_version_never_fails_the_request(self):
        response = self.client.get("/api/v1/system/compatibility?desktop_version=garbage")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["desktop_state"])

    def test_required_without_an_authorized_target_targets_recommended_version(self):
        # Sem authorized_release_version configurada, REQUIRED nao tem nada da
        # Fase 12 para degradar -- passa a exigir a recommended_desktop_version
        # (Fase 01/02) diretamente, sem quebrar.
        from api.app.core.config import MINIMUM_DESKTOP_VERSION

        asyncio.run(self._save(EnforcementMode.REQUIRED, None, None, "obrigatorio"))
        response = self.client.get(f"/api/v1/system/compatibility?desktop_version={MINIMUM_DESKTOP_VERSION}")
        body = response.json()
        self.assertEqual(body["enforcement"], "REQUIRED")
        self.assertIn(body["desktop_state"], ("UPDATE_REQUIRED", "COMPATIBLE"))


if __name__ == "__main__":
    unittest.main()
