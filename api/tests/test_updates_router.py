from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.main import create_app
from api.app.updates import service
from api.app.updates.download_grant import mint_download_grant


def _write_manifest_and_package(tmp: Path, *, version: str = "2.6.0") -> tuple[Path, Path]:
    package = tmp / f"pkg-{version}.exe"
    package.write_bytes(b"conteudo-real-do-instalador" * 1000)
    manifest_data = {
        "manifest_schema_version": 1, "release_version": version, "channel": "production",
        "published_at": "2026-08-11T12:00:00Z", "minimum_server_version": "0.8.0", "api_contract_version": "v1",
        "artifact": {
            "filename": package.name, "size_bytes": package.stat().st_size,
            "sha256": hashlib.sha256(package.read_bytes()).hexdigest(), "content_type": "application/octet-stream",
        },
    }
    manifest_path = tmp / f"manifest-{version}.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
    return manifest_path, package


class DiscoveryManifestPackageHttpTests(unittest.TestCase):
    """Endpoints publicos (discovery/manifest/package) -- nao precisam de
    Postgres configurado, mesmo padrao de test_system_compatibility.py."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self._previous_env = {
            "DATABASE_URL": os.environ.get("DATABASE_URL"),
            "SECRET_KEY": os.environ.get("SECRET_KEY"),
            "UPDATE_REPOSITORY_DIR": os.environ.get("UPDATE_REPOSITORY_DIR"),
        }
        os.environ["DATABASE_URL"] = ""
        os.environ["SECRET_KEY"] = "local-test-only-secret-key-32-characters-min"
        os.environ["UPDATE_REPOSITORY_DIR"] = str(self.tmp / "repo")
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

    def _publish_authorized_release(self, version: str = "2.6.0") -> None:
        manifest_path, package_path = _write_manifest_and_package(self.tmp, version=version)
        service.sync_release(manifest_path=manifest_path, package_path=package_path)
        service.authorize_release(version)

    def test_discovery_reports_unavailable_by_default(self):
        response = self.client.get("/api/v1/updates/desktop")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"available": False, "version": None, "manifest_url": None, "package_url": None, "release_state": None})

    def test_discovery_reports_authorized_release(self):
        self._publish_authorized_release()
        response = self.client.get("/api/v1/updates/desktop")
        body = response.json()
        self.assertTrue(body["available"])
        self.assertEqual(body["version"], "2.6.0")

    def test_manifest_requires_grant_or_bearer(self):
        self._publish_authorized_release()
        response = self.client.get("/api/v1/updates/desktop/2.6.0/manifest")
        self.assertEqual(response.status_code, 401)

    def test_manifest_with_valid_grant_returns_json(self):
        self._publish_authorized_release()
        grant = mint_download_grant("2.6.0")
        response = self.client.get(f"/api/v1/updates/desktop/2.6.0/manifest?grant={grant}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertEqual(response.json()["release_version"], "2.6.0")

    def test_manifest_grant_scoped_to_wrong_version_is_rejected(self):
        self._publish_authorized_release()
        grant = mint_download_grant("9.9.9")
        response = self.client.get(f"/api/v1/updates/desktop/2.6.0/manifest?grant={grant}")
        self.assertEqual(response.status_code, 401)

    def test_manifest_for_unauthorized_version_is_404_even_with_valid_grant_shape(self):
        grant = mint_download_grant("9.9.9")
        response = self.client.get(f"/api/v1/updates/desktop/9.9.9/manifest?grant={grant}")
        self.assertEqual(response.status_code, 404)

    def test_package_download_streams_with_expected_headers(self):
        self._publish_authorized_release()
        grant = mint_download_grant("2.6.0")
        response = self.client.get(f"/api/v1/updates/desktop/2.6.0/package?grant={grant}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertEqual(response.headers["content-length"], str(len(response.content)))
        self.assertTrue(response.headers["etag"])
        self.assertEqual(response.headers["accept-ranges"], "bytes")

    def test_package_download_supports_range_requests(self):
        self._publish_authorized_release()
        grant = mint_download_grant("2.6.0")
        response = self.client.get(f"/api/v1/updates/desktop/2.6.0/package?grant={grant}", headers={"Range": "bytes=0-9"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(len(response.content), 10)
        self.assertTrue(response.headers["content-range"].startswith("bytes 0-9/"))

    def test_package_download_without_auth_is_401(self):
        self._publish_authorized_release()
        response = self.client.get("/api/v1/updates/desktop/2.6.0/package")
        self.assertEqual(response.status_code, 401)

    def test_revoked_release_package_is_not_served(self):
        self._publish_authorized_release()
        service.revoke_release("2.6.0", reason="teste")
        grant = mint_download_grant("2.6.0")
        response = self.client.get(f"/api/v1/updates/desktop/2.6.0/package?grant={grant}")
        self.assertEqual(response.status_code, 404)

    def test_path_traversal_via_version_segment_never_reaches_filesystem(self):
        response = self.client.get("/api/v1/updates/desktop/..%2f..%2f..%2fetc%2fpasswd/manifest")
        self.assertIn(response.status_code, (404, 401))



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
class AdminReleaseEndpointsIntegrationTests(unittest.TestCase):
    """Fase 12, Secao 19: endpoint administrativo de publicacao nao pode ser
    acessivel a usuarios comuns -- exercita isso via HTTP real contra um
    usuario sem a permissao updates.manage."""

    @classmethod
    def setUpClass(cls):
        cls.previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV"), "SECRET_KEY": os.environ.get("SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "updates-router-integration-secret-key-32chars"
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
                UserCreate(username="updates.admin", display_name="Updates Admin", password="senha-admin-teste-123", permission_codes=[UPDATES_MANAGE]),
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

    def test_admin_sync_without_auth_is_401(self):
        response = self.client.post("/api/v1/updates/desktop/sync", json={"manifest_path": "x", "package_path": "y"})
        self.assertEqual(response.status_code, 401)

    def test_admin_authorize_without_auth_is_401(self):
        response = self.client.post("/api/v1/updates/desktop/2.6.0/authorize")
        self.assertEqual(response.status_code, 401)

    def test_admin_revoke_without_auth_is_401(self):
        response = self.client.post("/api/v1/updates/desktop/2.6.0/revoke", json={"reason": "x"})
        self.assertEqual(response.status_code, 401)

    def test_admin_list_without_auth_is_401(self):
        response = self.client.get("/api/v1/updates/desktop/admin/releases")
        self.assertEqual(response.status_code, 401)

    def test_plain_user_cannot_sync_release(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp)
        response = self.client.post(
            "/api/v1/updates/desktop/sync",
            json={"manifest_path": str(manifest_path), "package_path": str(package_path)},
            headers=self._auth(self.plain_token),
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_user_can_sync_authorize_revoke_and_list(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp)
        sync_response = self.client.post(
            "/api/v1/updates/desktop/sync",
            json={"manifest_path": str(manifest_path), "package_path": str(package_path), "source": "ci-pipeline"},
            headers=self._auth(self.admin_token),
        )
        self.assertEqual(sync_response.status_code, 200)
        self.assertEqual(sync_response.json()["state"], "READY")

        authorize_response = self.client.post("/api/v1/updates/desktop/2.6.0/authorize", headers=self._auth(self.admin_token))
        self.assertEqual(authorize_response.status_code, 200)
        self.assertEqual(authorize_response.json()["state"], "AUTHORIZED")

        list_response = self.client.get("/api/v1/updates/desktop/admin/releases", headers=self._auth(self.admin_token))
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()["items"]), 1)

        revoke_response = self.client.post("/api/v1/updates/desktop/2.6.0/revoke", json={"reason": "teste http"}, headers=self._auth(self.admin_token))
        self.assertEqual(revoke_response.status_code, 200)
        self.assertEqual(revoke_response.json()["state"], "REVOKED")

    def test_authenticated_user_bearer_can_download_authorized_package(self):
        manifest_path, package_path = _write_manifest_and_package(self.tmp)
        service.sync_release(manifest_path=manifest_path, package_path=package_path)
        service.authorize_release("2.6.0")

        response = self.client.get("/api/v1/updates/desktop/2.6.0/package", headers=self._auth(self.plain_token))
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
