from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
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
from api.app.channels.service import build_default_service
from api.app.maintenance.models import MaintenanceReasonCode
from api.app.maintenance.service import build_default_service as build_default_maintenance_service
from api.app.updates import service as updates_service
from api.app.updates.download_grant import mint_download_grant


def _write_manifest_and_package(tmp: Path, *, version: str = "3.3.0") -> tuple[Path, Path]:
    package = tmp / f"pkg-{version}.exe"
    package.write_bytes(b"conteudo-real-do-instalador" * 1000)
    manifest_data = {
        "manifest_schema_version": 1, "release_version": version, "channel": "production",
        "published_at": "2026-08-12T12:00:00Z", "minimum_server_version": "0.8.0", "api_contract_version": "v1",
        "artifact": {
            "filename": package.name, "size_bytes": package.stat().st_size,
            "sha256": hashlib.sha256(package.read_bytes()).hexdigest(), "content_type": "application/octet-stream",
        },
    }
    manifest_path = tmp / f"manifest-{version}.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
    return manifest_path, package


class NoDatabaseChannelGatingTests(unittest.TestCase):
    """Sem Postgres configurado, toda instalacao resolve para PRODUCTION
    (fallback seguro, Secao 8) -- exercitado aqui sem depender de banco."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self._previous_env = {
            "DATABASE_URL": os.environ.get("DATABASE_URL"),
            "SECRET_KEY": os.environ.get("SECRET_KEY"),
            "UPDATE_REPOSITORY_DIR": os.environ.get("UPDATE_REPOSITORY_DIR"),
            "MAINTENANCE_STATE_DIR": os.environ.get("MAINTENANCE_STATE_DIR"),
        }
        os.environ["DATABASE_URL"] = ""
        os.environ["SECRET_KEY"] = "local-test-only-secret-key-32-characters-min"
        os.environ["UPDATE_REPOSITORY_DIR"] = str(self.tmp / "repo")
        os.environ["MAINTENANCE_STATE_DIR"] = str(self.tmp / "maintenance")
        get_settings.cache_clear()
        get_engine.cache_clear()
        self.client = TestClient(create_app())
        self.channel_service = build_default_service()

    def tearDown(self):
        for key, value in self._previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        get_engine.cache_clear()

    def _authorize_pilot_release(self, version: str = "3.3.0"):
        manifest_path, package_path = _write_manifest_and_package(self.tmp, version=version)
        updates_service.sync_release(manifest_path=manifest_path, package_path=package_path)
        return self.channel_service.authorize_pilot(version, actor="release.admin")

    def test_pilot_only_release_is_not_offered_to_default_client(self):
        self._authorize_pilot_release()
        response = self.client.get("/api/v1/updates/desktop")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["available"])

    def test_pilot_only_release_not_offered_even_with_installation_id_when_db_unavailable(self):
        # Sem sessionmaker (DATABASE_URL vazio), installation_id nao pode ser
        # resolvido -- cai em PRODUCTION, nunca PILOT (Secao 8).
        self._authorize_pilot_release()
        response = self.client.get("/api/v1/updates/desktop?installation_id=some-pc")
        self.assertFalse(response.json()["available"])

    def test_maintenance_active_blocks_channel_admin_routes(self):
        # Fase 15, Secao 25: Maintenance (Fase 14) e independente de canal e
        # prevalece -- rotas administrativas de canal nao estao na allowlist
        # do MaintenanceMiddleware, entao ficam bloqueadas durante ACTIVE.
        maintenance_service = build_default_maintenance_service()
        maintenance_service.activate_maintenance(
            reason_code=MaintenanceReasonCode.EMERGENCY_MAINTENANCE, message="Incidente",
            expected_end_at=None, activated_by="tester",
        )
        response = self.client.get("/api/v1/channels/installations")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "MAINTENANCE_MODE_ACTIVE")

    def test_maintenance_active_still_allows_authorized_update_downloads(self):
        # Downloads autorizados continuam possiveis quando a allowlist
        # permitir (Secao 25) -- /updates permanece fora do bloqueio de
        # manutencao mesmo com um release ja gated por canal.
        manifest_path, package_path = _write_manifest_and_package(self.tmp, version="3.2.0")
        updates_service.sync_release(manifest_path=manifest_path, package_path=package_path)
        updates_service.authorize_release("3.2.0")

        maintenance_service = build_default_maintenance_service()
        maintenance_service.activate_maintenance(
            reason_code=MaintenanceReasonCode.EMERGENCY_MAINTENANCE, message="Incidente",
            expected_end_at=None, activated_by="tester",
        )
        response = self.client.get("/api/v1/updates/desktop")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["available"])

    def test_ungated_authorized_release_is_offered_to_everyone(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp, version="3.2.0")
        updates_service.sync_release(manifest_path=manifest_path, package_path=package_path)
        updates_service.authorize_release("3.2.0")

        response = self.client.get("/api/v1/updates/desktop")
        self.assertTrue(response.json()["available"])
        self.assertEqual(response.json()["version"], "3.2.0")

    def test_manifest_download_with_grant_for_pilot_release_rejected_for_production_caller(self):
        self._authorize_pilot_release()
        grant = mint_download_grant("3.3.0", channel="PILOT")
        response = self.client.get(f"/api/v1/updates/desktop/3.3.0/manifest?grant={grant}")
        self.assertEqual(response.status_code, 401)

    def test_manifest_download_of_ungated_release_still_works_with_grant(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp, version="3.2.0")
        updates_service.sync_release(manifest_path=manifest_path, package_path=package_path)
        updates_service.authorize_release("3.2.0")
        grant = mint_download_grant("3.2.0")
        response = self.client.get(f"/api/v1/updates/desktop/3.2.0/manifest?grant={grant}")
        self.assertEqual(response.status_code, 200)



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
class ChannelAssignmentAndDiscoveryIntegrationTests(unittest.TestCase):
    """Fase 15, Secao 6-8/15/16: cadastro de instalacoes, resolucao de canal
    e descoberta condicionada a canal, ponta a ponta via HTTP real."""

    @classmethod
    def setUpClass(cls):
        cls.previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV"), "SECRET_KEY": os.environ.get("SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "channels-router-integration-secret-key-32ch"
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
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self._previous_repo_dir = os.environ.get("UPDATE_REPOSITORY_DIR")
        os.environ["UPDATE_REPOSITORY_DIR"] = str(self.tmp / "repo")
        get_settings.cache_clear()
        asyncio.run(self._reset_database())
        self.admin_token, self.plain_token = asyncio.run(self._create_users())
        self.client = TestClient(create_app())
        self.channel_service = build_default_service()

    def tearDown(self):
        if self._previous_repo_dir is None:
            os.environ.pop("UPDATE_REPOSITORY_DIR", None)
        else:
            os.environ["UPDATE_REPOSITORY_DIR"] = self._previous_repo_dir
        get_settings.cache_clear()

    async def _reset_database(self):
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE role_permissions, user_roles, users, roles, permissions RESTART IDENTITY CASCADE"))
            await conn.execute(text("TRUNCATE TABLE client_installations, pilot_client_reports RESTART IDENTITY CASCADE"))

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
                username="bootstrap.actor", display_name="Bootstrap Actor",
                password_hash=hash_password("senha-bootstrap-teste-123"), active=True,
                is_superuser=True, password_changed_at=utcnow(),
            )
            session.add(bootstrap_actor)
            await session.flush()

            admin = await users_service.create_user(
                session,
                UserCreate(username="channels.admin", display_name="Channels Admin", password="senha-admin-teste-123", permission_codes=[UPDATES_MANAGE]),
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

    def _authorize_pilot_release(self, version: str = "3.3.0"):
        manifest_path, package_path = _write_manifest_and_package(self.tmp, version=version)
        updates_service.sync_release(manifest_path=manifest_path, package_path=package_path)
        return self.channel_service.authorize_pilot(version, actor="release.admin")

    def test_list_installations_without_auth_is_401(self):
        response = self.client.get("/api/v1/channels/installations")
        self.assertEqual(response.status_code, 401)

    def test_pilot_report_without_auth_is_401(self):
        response = self.client.post("/api/v1/channels/pilot-reports", json={
            "installation_id": "pc-1", "release_version": "3.3.0",
            "update_result": "SUCCESS", "app_start_result": "SUCCESS", "compatibility_result": "OK",
        })
        self.assertEqual(response.status_code, 401)

    def test_unknown_installation_falls_back_to_production(self):
        self._authorize_pilot_release()
        response = self.client.get("/api/v1/updates/desktop?installation_id=never-seen-before")
        self.assertFalse(response.json()["available"])

    def test_plain_user_cannot_assign_channel(self):
        response = self.client.post(
            "/api/v1/channels/installations/pc-1/assign", json={"channel": "PILOT"}, headers=self._auth(self.plain_token),
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_assigns_pilot_and_client_then_sees_pilot_release(self):
        self._authorize_pilot_release()
        assign = self.client.post(
            "/api/v1/channels/installations/pc-pilot-1/assign", json={"channel": "PILOT"}, headers=self._auth(self.admin_token),
        )
        self.assertEqual(assign.status_code, 200)
        self.assertEqual(assign.json()["channel"], "PILOT")

        response = self.client.get("/api/v1/updates/desktop?installation_id=pc-pilot-1")
        self.assertTrue(response.json()["available"])
        self.assertEqual(response.json()["version"], "3.3.0")

    def test_production_client_never_sees_pilot_only_release(self):
        self._authorize_pilot_release()
        self.client.post(
            "/api/v1/channels/installations/pc-prod-1/assign", json={"channel": "PRODUCTION"}, headers=self._auth(self.admin_token),
        )
        response = self.client.get("/api/v1/updates/desktop?installation_id=pc-prod-1")
        self.assertFalse(response.json()["available"])

    def test_removing_assignment_falls_back_to_production(self):
        self.client.post(
            "/api/v1/channels/installations/pc-1/assign", json={"channel": "PILOT"}, headers=self._auth(self.admin_token),
        )
        response = self.client.delete("/api/v1/channels/installations/pc-1/assign", headers=self._auth(self.admin_token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["channel"], "PRODUCTION")

    def test_heartbeat_via_compatibility_updates_last_seen_and_version(self):
        self.client.get("/api/v1/system/compatibility?installation_id=pc-heartbeat&desktop_version=3.2.0")
        listing = self.client.get("/api/v1/channels/installations", headers=self._auth(self.admin_token))
        rows = {row["installation_id"]: row for row in listing.json()["items"]}
        self.assertIn("pc-heartbeat", rows)
        self.assertEqual(rows["pc-heartbeat"]["current_desktop_version"], "3.2.0")
        self.assertIsNotNone(rows["pc-heartbeat"]["last_seen_at"])
        self.assertEqual(rows["pc-heartbeat"]["channel"], "PRODUCTION")

    def test_pilot_grant_download_rejected_for_production_resolved_client(self):
        self._authorize_pilot_release()
        self.client.post(
            "/api/v1/channels/installations/pc-prod-2/assign", json={"channel": "PRODUCTION"}, headers=self._auth(self.admin_token),
        )
        grant = mint_download_grant("3.3.0", channel="PILOT")
        response = self.client.get(f"/api/v1/updates/desktop/3.3.0/manifest?grant={grant}&installation_id=pc-prod-2")
        self.assertEqual(response.status_code, 401)

    def test_pilot_grant_download_works_for_pilot_resolved_client(self):
        self._authorize_pilot_release()
        self.client.post(
            "/api/v1/channels/installations/pc-pilot-2/assign", json={"channel": "PILOT"}, headers=self._auth(self.admin_token),
        )
        grant = mint_download_grant("3.3.0", channel="PILOT")
        response = self.client.get(f"/api/v1/updates/desktop/3.3.0/manifest?grant={grant}&installation_id=pc-pilot-2")
        self.assertEqual(response.status_code, 200)

    def test_full_admin_promotion_lifecycle_via_http(self):
        headers = self._auth(self.admin_token)
        self._authorize_pilot_release()

        report = self.client.post("/api/v1/channels/pilot-reports", json={
            "installation_id": "pc-pilot-3", "release_version": "3.3.0",
            "update_result": "SUCCESS", "app_start_result": "SUCCESS", "compatibility_result": "OK",
        }, headers=headers)
        self.assertEqual(report.status_code, 200)

        approve = self.client.post(
            "/api/v1/channels/pilot/3.3.0/approve",
            json={"min_pilot_clients_updated": 1, "observation_minutes": 0},
            headers=headers,
        )
        self.assertEqual(approve.status_code, 200, approve.text)
        self.assertEqual(approve.json()["status"], "PILOT_APPROVED")

        promote = self.client.post("/api/v1/channels/pilot/3.3.0/promote", headers=headers)
        self.assertEqual(promote.status_code, 200)
        self.assertEqual(promote.json()["status"], "PRODUCTION_AUTHORIZED")

        discovery = self.client.get("/api/v1/updates/desktop")
        self.assertTrue(discovery.json()["available"])
        self.assertEqual(discovery.json()["version"], "3.3.0")

    def test_approval_rejected_without_enough_reports(self):
        headers = self._auth(self.admin_token)
        self._authorize_pilot_release()

        approve = self.client.post(
            "/api/v1/channels/pilot/3.3.0/approve",
            json={"min_pilot_clients_updated": 3, "observation_minutes": 0},
            headers=headers,
        )
        self.assertEqual(approve.status_code, 409)
        self.assertEqual(approve.json()["error"]["code"], "CHANNEL_GATES_NOT_MET")

    def test_pilot_report_never_stores_operational_fields(self):
        headers = self._auth(self.admin_token)
        response = self.client.post("/api/v1/channels/pilot-reports", json={
            "installation_id": "pc-1", "release_version": "3.3.0",
            "update_result": "SUCCESS", "app_start_result": "SUCCESS", "compatibility_result": "OK",
        }, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.json().keys()),
            {"installation_id", "release_version", "update_result", "app_start_result", "compatibility_result", "error_code", "reported_at"},
        )


if __name__ == "__main__":
    unittest.main()
