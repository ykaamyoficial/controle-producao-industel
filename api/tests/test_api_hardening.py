"""Hardening da API (auditoria 05, achados 3, 4, 5, 6 e 11). Sem banco: tudo isolado por mock."""

from __future__ import annotations

import asyncio
import logging
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from api.app.core import error_codes
from api.app.core.config import MINIMUM_DESKTOP_VERSION, get_settings
from api.app.core.exceptions import ApiError
from api.app.database.health import DatabaseCheck
from api.app.database.session import get_db_session, get_engine
from api.app.main import create_app
from api.app.modules.auth import ip_rate_limit
from api.app.modules.auth.security import validate_password_policy
from api.app.modules.auth.tokens import create_access_token
from api.app.modules.system import service as system_service
from api.app.updates.policy import EnforcementMode

_SECRET = "hardening-tests-secret-key-with-more-than-32-chars"


class _EnvTestCase(unittest.TestCase):
    env: dict[str, str | None] = {}

    def setUp(self):
        base = {"DATABASE_URL": "", "SECRET_KEY": _SECRET, "PASSWORD_MIN_LENGTH": None,
                "LOGIN_IP_MAX_FAILURES": None, "LOGIN_IP_WINDOW_SECONDS": None, "APP_ENV": "development"}
        base.update(self.env)
        self._previous = {key: os.environ.get(key) for key in base}
        for key, value in base.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        get_engine.cache_clear()
        ip_rate_limit.reset()

    def tearDown(self):
        for key, value in self._previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        get_engine.cache_clear()
        ip_rate_limit.reset()


class DocsExposureTests(_EnvTestCase):
    DOC_PATHS = ("/docs", "/redoc", "/openapi.json")

    def test_docs_closed_in_production_and_unknown_envs(self):
        # fail-closed: so abre em ambiente sabidamente de dev/teste.
        for env in ("production", "prod", "PRODUCTION", "staging", ""):
            os.environ["APP_ENV"] = env
            get_settings.cache_clear()
            client = TestClient(create_app())
            for path in self.DOC_PATHS:
                self.assertEqual(client.get(path).status_code, 404, f"{env!r} {path}")

    def test_docs_open_in_development_and_test(self):
        for env in ("development", "test", "dev", "local", " Development "):
            os.environ["APP_ENV"] = env
            get_settings.cache_clear()
            client = TestClient(create_app())
            for path in self.DOC_PATHS:
                self.assertEqual(client.get(path).status_code, 200, f"{env} {path}")


class PasswordPolicyTests(_EnvTestCase):
    def test_default_minimum_is_10(self):
        self.assertEqual(get_settings().password_min_length, 10)
        with self.assertRaises(ApiError) as raised:
            validate_password_policy("Abc123xyz")  # 9 caracteres
        self.assertEqual(raised.exception.code, error_codes.PASSWORD_POLICY_VIOLATION)
        validate_password_policy("Abc123xyz9")  # 10 caracteres


class ValidationLogTests(_EnvTestCase):
    def test_validation_error_log_has_loc_and_type_but_not_input(self):
        app = create_app()
        app.dependency_overrides[get_db_session] = lambda: None
        client = TestClient(app)
        secret_value = "senha-que-nao-pode-vazar-" + "x" * 300
        logging.getLogger("api.errors").disabled = False  # o fileConfig do alembic (outros testes) desliga loggers existentes
        with self.assertLogs("api.errors", level="WARNING") as captured:
            response = client.post("/api/v1/auth/login", json={"password": secret_value})
        self.assertEqual(response.status_code, 422)
        text = "\n".join(captured.output)
        self.assertNotIn("senha-que-nao-pode-vazar", text)
        self.assertIn("'type'", text)
        self.assertIn("'loc'", text)
        self.assertIn("username", text)


def _fake_sessionmaker():
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


def _connected_check() -> DatabaseCheck:
    return DatabaseCheck(status="connected", revision="20260810_0015", revision_status="compatible")


class CompatibilityHeartbeatAuthTests(_EnvTestCase):
    def _run(self, *, authenticated):
        row = SimpleNamespace(channel="PRODUCTION")
        view = system_service._UpdatePolicyView(None, EnforcementMode.NONE, None, 0, None, "")
        with patch("api.app.modules.system.service._evaluate_update_policy", new=AsyncMock(return_value=view)),              patch("api.app.modules.system.service.database_check", new=AsyncMock(return_value=_connected_check())), \
             patch("api.app.modules.system.service.get_sessionmaker", return_value=_fake_sessionmaker()), \
             patch("api.app.modules.system.service.channel_installations.upsert_heartbeat", new=AsyncMock(return_value=row)) as upsert, \
             patch("api.app.modules.system.service.channel_installations.resolve_channel", new=AsyncMock(return_value=system_service.Channel.PILOT)) as resolve, \
             patch("api.app.modules.system.service.audit_service.record_event") as audit:
            result = asyncio.run(system_service.compatibility(
                desktop_version="2.10.0", installation_id="pc-1", machine_name="m", os_version="o", authenticated=authenticated,
            ))
        return result, upsert, resolve, audit

    def test_anonymous_returns_policy_and_known_channel_without_writing(self):
        result, upsert, resolve, audit = self._run(authenticated=False)
        self.assertEqual(result.minimum_desktop_version, MINIMUM_DESKTOP_VERSION)
        self.assertEqual(result.desktop_channel, "PILOT")  # canal ja atribuido continua sendo lido
        upsert.assert_not_awaited()
        resolve.assert_awaited_once()
        audit.assert_not_called()

    def test_authenticated_writes_heartbeat_and_audit(self):
        result, upsert, resolve, audit = self._run(authenticated=True)
        self.assertEqual(result.desktop_channel, "PRODUCTION")
        upsert.assert_awaited_once()
        audit.assert_called_once()

    def test_bearer_validation_never_raises(self):
        creds = lambda token: HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)  # noqa: E731
        self.assertFalse(asyncio.run(system_service.is_authenticated_bearer(None)))
        self.assertFalse(asyncio.run(system_service.is_authenticated_bearer(creds("lixo"))))
        token, _, _ = create_access_token(7)
        user = SimpleNamespace(active=True)
        with patch("api.app.modules.system.service.get_sessionmaker", return_value=_fake_sessionmaker()), \
             patch("api.app.modules.system.service.auth_repository.get_user_by_id", new=AsyncMock(return_value=user)):
            self.assertTrue(asyncio.run(system_service.is_authenticated_bearer(creds(token))))
            user.active = False
            self.assertFalse(asyncio.run(system_service.is_authenticated_bearer(creds(token))))

    def test_http_invalid_token_still_returns_policy(self):
        client = TestClient(create_app())
        with patch("api.app.modules.system.service.database_check", new=AsyncMock(return_value=_connected_check())):
            response = client.get(
                "/api/v1/system/compatibility?installation_id=pc-1&desktop_version=2.10.0",
                headers={"Authorization": "Bearer token-invalido"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("minimum_desktop_version", response.json())


if __name__ == "__main__":
    unittest.main()
