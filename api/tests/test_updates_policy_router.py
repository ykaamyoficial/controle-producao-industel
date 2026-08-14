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
from sqlalchemy import text

from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.main import create_app

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
class AdminPolicyEndpointsIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV"), "SECRET_KEY": os.environ.get("SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "updates-policy-router-integration-secret-32ch"
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
        asyncio.run(self._reset_database())
        self.admin_token, self.plain_token = asyncio.run(self._create_users())
        self.client = TestClient(create_app())

    async def _reset_database(self):
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE role_permissions, user_roles, users, roles, permissions, system_metadata RESTART IDENTITY CASCADE"))

    async def _create_users(self) -> tuple[str, str]:
        from api.app.modules.auth.bootstrap import sync_official_permissions
        from api.app.modules.auth.models import User
        from api.app.modules.auth.permissions import PROPOSALS_VIEW, UPDATES_MANAGE
        from api.app.modules.auth.security import hash_password
        from api.app.modules.auth.tokens import create_access_token, utcnow
        from api.app.modules.users import service as users_service
        from api.app.modules.users.schemas import UserCreate

        await sync_official_permissions()
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            bootstrap_actor = User(
                username="bootstrap.actor2", display_name="Bootstrap Actor 2",
                password_hash=hash_password("senha-bootstrap-teste-123"), active=True,
                is_superuser=True, password_changed_at=utcnow(),
            )
            session.add(bootstrap_actor)
            await session.flush()

            admin = await users_service.create_user(
                session,
                UserCreate(username="policy.admin", display_name="Policy Admin", password="senha-admin-teste-123", permission_codes=[UPDATES_MANAGE]),
                bootstrap_actor,
            )
            plain = await users_service.create_user(
                session,
                UserCreate(username="policy.plain", display_name="Policy Plain", password="senha-plana-teste-123", permission_codes=[PROPOSALS_VIEW]),
                bootstrap_actor,
            )
            admin_token, _exp, _jti = create_access_token(admin.id)
            plain_token, _exp2, _jti2 = create_access_token(plain.id)
        return admin_token, plain_token

    def _auth(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_get_policy_without_auth_is_401(self):
        response = self.client.get("/api/v1/updates/policy")
        self.assertEqual(response.status_code, 401)

    def test_put_policy_without_permission_is_403(self):
        response = self.client.put("/api/v1/updates/policy", json={"enforcement": "OPTIONAL"}, headers=self._auth(self.plain_token))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_read_default_policy(self):
        response = self.client.get("/api/v1/updates/policy", headers=self._auth(self.admin_token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["enforcement"], "NONE")
        self.assertEqual(response.json()["policy_revision"], 0)

    def test_admin_can_set_and_read_back_policy(self):
        put_response = self.client.put(
            "/api/v1/updates/policy",
            json={"enforcement": "RECOMMENDED", "message": "Atualize quando puder"},
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(put_response.status_code, 200)
        self.assertEqual(put_response.json()["enforcement"], "RECOMMENDED")
        self.assertEqual(put_response.json()["policy_revision"], 1)

        get_response = self.client.get("/api/v1/updates/policy", headers=self._auth(self.admin_token))
        self.assertEqual(get_response.json()["message"], "Atualize quando puder")

    def test_invalid_enforcement_value_is_rejected(self):
        response = self.client.put("/api/v1/updates/policy", json={"enforcement": "SUPER_URGENT"}, headers=self._auth(self.admin_token))
        self.assertEqual(response.status_code, 422)

    def test_invalid_authorized_release_version_is_rejected(self):
        response = self.client.put(
            "/api/v1/updates/policy",
            json={"enforcement": "REQUIRED", "authorized_release_version": "not-a-version"},
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, 422)

    def test_invalid_grace_until_is_rejected(self):
        response = self.client.put(
            "/api/v1/updates/policy",
            json={"enforcement": "REQUIRED", "grace_until": "not-a-date"},
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, 422)

    def test_grace_until_round_trips_with_timezone(self):
        grace = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        response = self.client.put(
            "/api/v1/updates/policy",
            json={"enforcement": "REQUIRED", "grace_until": grace},
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()["grace_until"])


if __name__ == "__main__":
    unittest.main()
