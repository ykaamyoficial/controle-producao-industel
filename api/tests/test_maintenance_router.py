from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.main import create_app


class PublicMaintenanceEndpointTests(unittest.TestCase):
    """GET /system/maintenance nao exige Postgres nem autenticacao (Secao 10) --
    mesmo padrao de test_system_compatibility.py / test_updates_router.py."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._previous_env = {
            "DATABASE_URL": os.environ.get("DATABASE_URL"),
            "SECRET_KEY": os.environ.get("SECRET_KEY"),
            "MAINTENANCE_STATE_DIR": os.environ.get("MAINTENANCE_STATE_DIR"),
        }
        os.environ["DATABASE_URL"] = ""
        os.environ["SECRET_KEY"] = ""
        os.environ["MAINTENANCE_STATE_DIR"] = self._tmp.name
        get_settings.cache_clear()
        get_engine.cache_clear()
        self.client = TestClient(create_app())

    def tearDown(self):
        for key, value in self._previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        get_engine.cache_clear()

    def test_default_state_is_off_with_full_shape(self):
        response = self.client.get("/api/v1/system/maintenance")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            set(body.keys()),
            {"state", "maintenance_id", "reason_code", "message", "scheduled_start_at", "started_at", "expected_end_at", "updated_at", "retry_after_seconds"},
        )
        self.assertEqual(body["state"], "OFF")
        self.assertIsNone(body["retry_after_seconds"])

    def test_never_requires_authorization_header(self):
        response = self.client.get("/api/v1/system/maintenance")
        self.assertNotEqual(response.status_code, 401)

    def test_openapi_documents_the_endpoint(self):
        schema = self.client.get("/openapi.json").json()
        self.assertIn("/api/v1/system/maintenance", schema["paths"])
        self.assertIn("/api/v1/system/maintenance/admin/activate", schema["paths"])


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


@unittest.skipUnless(_integration_enabled(), "Exige APP_ENV=test e POSTGRES_TEST_DATABASE_URL (mesmo guard das demais integracoes Postgres).")
class AdminMaintenanceEndpointsIntegrationTests(unittest.TestCase):
    """Fase 14, Secao 12: rotas administrativas exigem RBAC real -- exercitado
    via HTTP contra um usuario sem system.maintenance_manage."""

    @classmethod
    def setUpClass(cls):
        cls.previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV"), "SECRET_KEY": os.environ.get("SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "maintenance-router-integration-secret-32ch"
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
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._previous_state_dir = os.environ.get("MAINTENANCE_STATE_DIR")
        os.environ["MAINTENANCE_STATE_DIR"] = self._tmp.name
        get_settings.cache_clear()
        asyncio.run(self._reset_database())
        self.admin_token, self.plain_token = asyncio.run(self._create_users())
        self.client = TestClient(create_app())

    def tearDown(self):
        if self._previous_state_dir is None:
            os.environ.pop("MAINTENANCE_STATE_DIR", None)
        else:
            os.environ["MAINTENANCE_STATE_DIR"] = self._previous_state_dir
        get_settings.cache_clear()

    async def _reset_database(self):
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE role_permissions, user_roles, users, roles, permissions RESTART IDENTITY CASCADE"))

    async def _create_users(self) -> tuple[str, str]:
        from api.app.modules.auth.bootstrap import sync_official_permissions
        from api.app.modules.auth.models import User
        from api.app.modules.auth.permissions import PROPOSALS_VIEW, SYSTEM_MAINTENANCE_MANAGE
        from api.app.modules.auth.security import hash_password
        from api.app.modules.auth.tokens import create_access_token, utcnow
        from api.app.modules.users import service as users_service
        from api.app.modules.users.schemas import UserCreate

        await sync_official_permissions()
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            bootstrap_actor = User(
                username="bootstrap.actor", display_name="Bootstrap Actor",
                password_hash=hash_password("senha-bootstrap-teste-123"), active=True,
                is_superuser=True, password_changed_at=utcnow(),
            )
            session.add(bootstrap_actor)
            await session.flush()

            admin = await users_service.create_user(
                session,
                UserCreate(username="maintenance.admin", display_name="Maintenance Admin", password="senha-admin-teste-123", permission_codes=[SYSTEM_MAINTENANCE_MANAGE]),
                bootstrap_actor,
            )
            plain = await users_service.create_user(
                session,
                UserCreate(username="plain.user", display_name="Plain User", password="senha-plana-teste-123", permission_codes=[PROPOSALS_VIEW]),
                bootstrap_actor,
            )
            admin_token, _exp, _jti = create_access_token(admin.id)
            plain_token, _exp2, _jti2 = create_access_token(plain.id)
        return admin_token, plain_token

    def _auth(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_activate_without_auth_is_401(self):
        response = self.client.post("/api/v1/system/maintenance/admin/activate", json={"reason_code": "MANUAL_ADMIN", "message": "x"})
        self.assertEqual(response.status_code, 401)

    def test_plain_user_cannot_activate_maintenance(self):
        response = self.client.post(
            "/api/v1/system/maintenance/admin/activate",
            json={"reason_code": "MANUAL_ADMIN", "message": "x"},
            headers=self._auth(self.plain_token),
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_activate_and_state_reflects_actor(self):
        response = self.client.post(
            "/api/v1/system/maintenance/admin/activate",
            json={"reason_code": "MANUAL_ADMIN", "message": "Manutencao via HTTP"},
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"], "ACTIVE")
        self.assertEqual(body["activated_by"], "maintenance.admin")

    def test_invalid_reason_code_is_a_validation_error(self):
        response = self.client.post(
            "/api/v1/system/maintenance/admin/activate",
            json={"reason_code": "NOT_A_REAL_REASON", "message": "x"},
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, 422)

    def test_invalid_transition_returns_409_not_500(self):
        self.client.post(
            "/api/v1/system/maintenance/admin/activate",
            json={"reason_code": "MANUAL_ADMIN", "message": "x"},
            headers=self._auth(self.admin_token),
        )
        response = self.client.post(
            "/api/v1/system/maintenance/admin/schedule",
            json={"reason_code": "MANUAL_ADMIN", "message": "x", "scheduled_start_at": "2026-08-13T10:00:00Z"},
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "MAINTENANCE_INVALID_TRANSITION")

    def test_full_admin_lifecycle_via_http(self):
        headers = self._auth(self.admin_token)

        schedule = self.client.post(
            "/api/v1/system/maintenance/admin/schedule",
            json={"reason_code": "DEPLOYMENT", "message": "Deploy programado", "scheduled_start_at": "2026-08-13T10:00:00Z"},
            headers=headers,
        )
        self.assertEqual(schedule.status_code, 200)

        draining = self.client.post(
            "/api/v1/system/maintenance/admin/draining",
            json={"reason_code": "DEPLOYMENT", "message": "Esvaziando"},
            headers=headers,
        )
        self.assertEqual(draining.status_code, 200)

        active = self.client.post(
            "/api/v1/system/maintenance/admin/activate",
            json={"reason_code": "DEPLOYMENT", "message": "Em manutencao"},
            headers=headers,
        )
        self.assertEqual(active.status_code, 200)
        self.assertEqual(active.json()["maintenance_id"], schedule.json()["maintenance_id"])

        recovery = self.client.post("/api/v1/system/maintenance/admin/recovery", json={}, headers=headers)
        self.assertEqual(recovery.status_code, 200)
        self.assertEqual(recovery.json()["state"], "RECOVERY")

        finish = self.client.post("/api/v1/system/maintenance/admin/finish", headers=headers)
        self.assertEqual(finish.status_code, 200)
        self.assertEqual(finish.json()["state"], "OFF")

        public_view = self.client.get("/api/v1/system/maintenance")
        self.assertEqual(public_view.json()["state"], "OFF")


if __name__ == "__main__":
    unittest.main()
