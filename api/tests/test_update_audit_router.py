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

from api.app.audit import service as audit_service
from api.app.audit.models import ActorType, AuditEventType, Component, EventResult
from api.app.audit.spool import AuditSpool
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


class RouterStructureTests(unittest.TestCase):
    """Sem banco: verificacao estrutural, sempre executada."""

    def test_admin_audit_routes_have_no_write_verbs_registered(self):
        # Secao 25: "tela administrativa read-only" -- garante estruturalmente
        # que nenhuma rota POST/PUT/PATCH/DELETE existe sob este prefixo.
        from api.app.modules.update_audit.router import router as update_audit_router

        methods = {method for route in update_audit_router.routes for method in getattr(route, "methods", set())}
        self.assertIn("GET", methods)
        self.assertEqual(methods & {"POST", "PUT", "PATCH", "DELETE"}, set())


@unittest.skipUnless(_integration_enabled(), "Exige APP_ENV=test e POSTGRES_TEST_DATABASE_URL (mesmo guard das demais integracoes Postgres).")
class UpdateAuditRouterTests(unittest.TestCase):
    """Fase 16, Secao 25/29: API somente leitura, protegida por AUDIT_VIEW,
    nunca expõe segredos, nunca escreve nada."""

    @classmethod
    def setUpClass(cls):
        cls.previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV"), "SECRET_KEY": os.environ.get("SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "update-audit-router-integration-secret-32ch"
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
        self.tmp = Path(self._tmp.name)
        self.spool = AuditSpool(pending_dir=self.tmp / "pending", processed_dir=self.tmp / "processed", failed_dir=self.tmp / "failed")
        asyncio.run(self._reset_database())
        self.audit_token, self.plain_token = asyncio.run(self._create_users())
        self.client = TestClient(create_app())

    def tearDown(self):
        get_settings.cache_clear()

    async def _reset_database(self):
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE role_permissions, user_roles, users, roles, permissions RESTART IDENTITY CASCADE"))
            await conn.execute(text("TRUNCATE TABLE update_audit_events RESTART IDENTITY CASCADE"))
            await conn.execute(text("TRUNCATE TABLE client_installations, pilot_client_reports RESTART IDENTITY CASCADE"))

    async def _create_users(self) -> tuple[str, str]:
        from api.app.modules.auth.bootstrap import sync_official_permissions
        from api.app.modules.auth.models import User
        from api.app.modules.auth.permissions import AUDIT_VIEW, PROPOSALS_VIEW
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

            audit_viewer = await users_service.create_user(
                session,
                UserCreate(username="audit.viewer", display_name="Audit Viewer", password="senha-auditor-teste-123", permission_codes=[AUDIT_VIEW]),
                bootstrap_actor,
            )
            plain = await users_service.create_user(
                session,
                UserCreate(username="plain.user", display_name="Plain User", password="senha-plana-teste-123", permission_codes=[PROPOSALS_VIEW]),
                bootstrap_actor,
            )
            audit_token, _exp, _jti = create_access_token(audit_viewer.id)
            plain_token, _exp2, _jti2 = create_access_token(plain.id)
        return audit_token, plain_token

    def _auth(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def _seed_event(self, **overrides):
        defaults = dict(
            event_type=AuditEventType.DEPLOYMENT_STARTED, component=Component.DEPLOYMENT,
            result=EventResult.STARTED, message="x", spool=self.spool,
        )
        defaults.update(overrides)
        return audit_service.record_event(**defaults)

    async def _drain(self) -> int:
        return await audit_service.drain_spool_to_database(spool=self.spool, sessionmaker=get_sessionmaker())

    def test_list_events_without_auth_is_401(self):
        response = self.client.get("/api/v1/admin/update-audit/events")
        self.assertEqual(response.status_code, 401)

    def test_list_events_without_audit_view_permission_is_403(self):
        response = self.client.get("/api/v1/admin/update-audit/events", headers=self._auth(self.plain_token))
        self.assertEqual(response.status_code, 403)

    def test_list_events_returns_seeded_events_after_drain(self):
        self._seed_event(version="3.3.0")
        asyncio.run(self._drain())
        response = self.client.get("/api/v1/admin/update-audit/events", headers=self._auth(self.audit_token))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["version"], "3.3.0")

    def test_events_endpoint_triggers_its_own_drain_caller_never_has_to_drain_manually(self):
        # Nao chamamos self._drain() aqui de proposito -- o endpoint deve
        # drenar sozinho (Secao 18: "perto de tempo real") antes de responder.
        self._seed_event(version="3.4.0")
        response = self.client.get("/api/v1/admin/update-audit/events?version=3.4.0", headers=self._auth(self.audit_token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)

    def test_list_events_limit_is_clamped_to_max_page_size(self):
        response = self.client.get("/api/v1/admin/update-audit/events?limit=9999", headers=self._auth(self.audit_token))
        self.assertEqual(response.status_code, 422)  # Query(le=200) rejeita antes mesmo de chegar ao service

    def test_get_event_detail_returns_full_record_without_secrets(self):
        event = self._seed_event(metadata={"password": "should-not-leak", "sha256": "abc123"})
        asyncio.run(self._drain())
        response = self.client.get(f"/api/v1/admin/update-audit/events/{event.event_id}", headers=self._auth(self.audit_token))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["metadata"]["password"], "***REDACTED***")
        self.assertNotIn("should-not-leak", response.text)

    def test_get_event_detail_unknown_id_is_404(self):
        response = self.client.get("/api/v1/admin/update-audit/events/does-not-exist", headers=self._auth(self.audit_token))
        self.assertEqual(response.status_code, 404)

    def test_timeline_returns_events_ordered_chronologically(self):
        corr = "upd-20260812-routertest"
        self._seed_event(event_type=AuditEventType.DEPLOYMENT_STARTED, correlation_id=corr)
        self._seed_event(event_type=AuditEventType.BACKUP_STARTED, correlation_id=corr)
        self._seed_event(event_type=AuditEventType.DEPLOYMENT_SUCCEEDED, correlation_id=corr)
        asyncio.run(self._drain())
        response = self.client.get(f"/api/v1/admin/update-audit/timeline/{corr}", headers=self._auth(self.audit_token))
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(len(items), 3)
        timestamps = [item["occurred_at"] for item in items]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_installation_status_unknown_installation_is_404(self):
        response = self.client.get("/api/v1/admin/update-audit/installations/does-not-exist", headers=self._auth(self.audit_token))
        self.assertEqual(response.status_code, 404)

    def test_installation_status_known_installation_returns_snapshot(self):
        from api.app.channels.db_models import ClientInstallation

        async def _seed():
            async with get_sessionmaker()() as session:
                session.add(ClientInstallation(installation_id="pc-router-1", machine_name="PC-ROUTER-1", channel="PRODUCTION", current_desktop_version="3.2.0"))
                await session.commit()

        asyncio.run(_seed())
        response = self.client.get("/api/v1/admin/update-audit/installations/pc-router-1", headers=self._auth(self.audit_token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["installation_id"], "pc-router-1")

    def test_release_events_returns_events_for_that_version_only(self):
        self._seed_event(version="3.3.0")
        self._seed_event(version="3.2.0")
        asyncio.run(self._drain())
        response = self.client.get("/api/v1/admin/update-audit/releases/3.3.0", headers=self._auth(self.audit_token))
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["version"], "3.3.0")

if __name__ == "__main__":
    unittest.main()
