from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.main import create_app
from api.app.modules.auth.models import Permission, Role, User
from api.app.modules.auth.permissions import ADMIN_PERMISSION_CODES
from api.app.modules.auth.security import hash_password
from api.app.modules.auth.tokens import utcnow


ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "api"
TEST_DATABASE_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL", "")


def _database_name(url: str) -> str:
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    return parsed.path.lstrip("/")


def _integration_enabled() -> bool:
    return (
        bool(TEST_DATABASE_URL)
        and os.environ.get("APP_ENV") == "test"
        and TEST_DATABASE_URL.startswith("postgresql+asyncpg://")
        and "test" in _database_name(TEST_DATABASE_URL).lower()
    )


def _alembic_config() -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    return config


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class AuthIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {
            "DATABASE_URL": os.environ.get("DATABASE_URL"),
            "APP_ENV": os.environ.get("APP_ENV"),
            "SECRET_KEY": os.environ.get("SECRET_KEY"),
            "LOGIN_MAX_FAILED_ATTEMPTS": os.environ.get("LOGIN_MAX_FAILED_ATTEMPTS"),
            "LOGIN_LOCK_MINUTES": os.environ.get("LOGIN_LOCK_MINUTES"),
        }
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "auth-integration-secret-key-more-than-32-chars"
        os.environ["LOGIN_MAX_FAILED_ATTEMPTS"] = "2"
        os.environ["LOGIN_LOCK_MINUTES"] = "15"
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
        asyncio.run(self._clean_and_seed_admin())
        self.client = TestClient(create_app())

    async def _clean_and_seed_admin(self):
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE security_events, auth_sessions, proposal_events, proposal_items, proposals, sync_runs, role_permissions, user_roles, users, roles RESTART IDENTITY CASCADE"))
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            permissions = (await session.execute(select(Permission).where(Permission.code.in_(ADMIN_PERMISSION_CODES)))).scalars().all()
            role = Role(code="admin", name="Administrador", description="Admin", active=True, system_role=True)
            role.permissions.extend(permissions)
            user = User(
                username="admin",
                display_name="Administrador",
                password_hash=hash_password("Senha forte de teste 123"),
                active=True,
                is_superuser=True,
                password_changed_at=utcnow(),
            )
            user.roles.append(role)
            session.add(user)
            await session.commit()

    def _login(self, username: str = "admin", password: str = "Senha forte de teste 123"):
        return self.client.post("/api/v1/auth/login", json={"username": username, "password": password})

    def test_login_me_refresh_reuse_logout_flow(self):
        login = self._login()
        self.assertEqual(login.status_code, 200)
        body = login.json()
        self.assertNotIn("password_hash", str(body))

        headers = {"Authorization": f"Bearer {body['access_token']}"}
        me = self.client.get("/api/v1/auth/me", headers=headers)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["username"], "admin")

        refreshed = self.client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
        self.assertEqual(refreshed.status_code, 200)
        reused = self.client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
        self.assertEqual(reused.status_code, 401)

        logout = self.client.post("/api/v1/auth/logout", json={"refresh_token": refreshed.json()["refresh_token"]}, headers=headers)
        self.assertEqual(logout.status_code, 204)

    def test_failed_login_locks_account(self):
        first = self._login(password="errada")
        second = self._login(password="errada")
        third = self._login()
        self.assertEqual(first.status_code, 401)
        self.assertEqual(second.status_code, 401)
        self.assertEqual(third.status_code, 401)
        self.assertEqual(third.json()["error"]["code"], "ACCOUNT_LOCKED")

    def test_admin_can_create_user_and_rbac_blocks_plain_user(self):
        admin_token = self._login().json()["access_token"]
        headers = {"Authorization": f"Bearer {admin_token}"}
        created = self.client.post(
            "/api/v1/users",
            json={
                "username": "operador",
                "display_name": "Operador",
                "password": "Senha do operador 123",
                "permission_codes": ["proposals.view"],
            },
            headers=headers,
        )
        self.assertEqual(created.status_code, 201)

        user_token = self.client.post("/api/v1/auth/login", json={"username": "operador", "password": "Senha do operador 123"}).json()["access_token"]
        denied = self.client.get("/api/v1/users", headers={"Authorization": f"Bearer {user_token}"})
        self.assertEqual(denied.status_code, 403)

    def test_roles_permissions_and_security_events_are_protected(self):
        no_token = self.client.get("/api/v1/roles")
        self.assertEqual(no_token.status_code, 401)

        admin_token = self._login().json()["access_token"]
        headers = {"Authorization": f"Bearer {admin_token}"}
        roles = self.client.get("/api/v1/roles", headers=headers)
        permissions = self.client.get("/api/v1/permissions", headers=headers)
        events = self.client.get("/api/v1/security-events", headers=headers)
        self.assertEqual(roles.status_code, 200)
        self.assertEqual(permissions.status_code, 200)
        self.assertEqual(events.status_code, 200)
        self.assertGreaterEqual(events.json()["total"], 1)

    def test_last_admin_cannot_be_deactivated(self):
        token = self._login().json()["access_token"]
        response = self.client.post("/api/v1/users/1/deactivate", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "LAST_ADMIN_PROTECTION")


if __name__ == "__main__":
    unittest.main()
