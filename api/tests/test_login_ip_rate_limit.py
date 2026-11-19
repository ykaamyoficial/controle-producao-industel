"""Limite de falhas de login por IP (auditoria 05, achado 4). Sem banco: service.login e mockado."""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from api.app.core import error_codes
from api.app.core.config import get_settings
from api.app.core.exceptions import ApiError, AuthenticationError
from api.app.database.session import get_db_session, get_engine
from api.app.main import create_app
from api.app.modules.auth import ip_rate_limit

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


class LoginIpRateLimitUnitTests(_EnvTestCase):
    env = {"LOGIN_IP_MAX_FAILURES": "3", "LOGIN_IP_WINDOW_SECONDS": "60"}

    def _fail(self, ip, times):
        for _ in range(times):
            ip_rate_limit.reserve(ip)  # reserva nao devolvida = falha

    def test_blocks_after_limit_with_retry_after_and_isolates_ips(self):
        with patch("api.app.modules.auth.ip_rate_limit.time.monotonic", return_value=1000.0):
            self._fail("1.1.1.1", 3)  # as 3 cabem no limite
            with self.assertRaises(ApiError) as raised:
                ip_rate_limit.reserve("1.1.1.1")
            self.assertEqual(raised.exception.status_code, 429)
            self.assertEqual(raised.exception.headers, {"Retry-After": "60"})
            ip_rate_limit.reserve("2.2.2.2")  # outro IP nao e afetado

    def test_window_slides_and_unblocks(self):
        with patch("api.app.modules.auth.ip_rate_limit.time.monotonic", return_value=1000.0):
            self._fail("1.1.1.1", 3)
            with self.assertRaises(ApiError):
                ip_rate_limit.reserve("1.1.1.1")
        with patch("api.app.modules.auth.ip_rate_limit.time.monotonic", return_value=1061.0):
            ip_rate_limit.reserve("1.1.1.1")

    def test_reset_clears_counters(self):
        self._fail("1.1.1.1", 3)
        ip_rate_limit.reset()
        ip_rate_limit.reserve("1.1.1.1")

    def test_release_returns_the_slot(self):
        self._fail("1.1.1.1", 2)
        ip_rate_limit.release("1.1.1.1", ip_rate_limit.reserve("1.1.1.1"))
        ip_rate_limit.reserve("1.1.1.1")  # a devolvida liberou a 3a vaga
        with self.assertRaises(ApiError):
            ip_rate_limit.reserve("1.1.1.1")
        ip_rate_limit.release("9.9.9.9", 123.0)  # reserva desconhecida: nada acontece

    def test_tracked_ips_are_capped_dropping_least_recently_used(self):
        with patch.object(ip_rate_limit, "_MAX_TRACKED_IPS", 3):
            for ip in ("a", "b", "c", "a", "d"):  # "a" reusado vai para o fim; "b" e o mais antigo
                ip_rate_limit.reserve(ip)
        self.assertEqual(list(ip_rate_limit._failures), ["c", "a", "d"])


class LoginIpRateLimitDisabledTests(_EnvTestCase):
    env = {"LOGIN_IP_MAX_FAILURES": "0"}

    def test_zero_disables(self):
        for _ in range(100):
            self.assertIsNone(ip_rate_limit.reserve("1.1.1.1"))
        self.assertEqual(ip_rate_limit._failures, {})


class LoginRouteRateLimitTests(_EnvTestCase):
    env = {"LOGIN_IP_MAX_FAILURES": "2", "LOGIN_IP_WINDOW_SECONDS": "300"}

    def setUp(self):
        super().setUp()
        self.app = create_app()
        self.app.dependency_overrides[get_db_session] = lambda: None
        self.client = TestClient(self.app)

    def _login(self):
        return self.client.post("/api/v1/auth/login", json={"username": "u", "password": "p"})

    def test_simultaneous_burst_only_lets_the_limit_through(self):
        fail = AuthenticationError(error_codes.INVALID_CREDENTIALS, "Usuario ou senha invalidos.")

        async def scenario():
            gate = asyncio.Event()

            async def slow_fail(*_args, **_kwargs):
                await gate.wait()
                raise fail

            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                with patch("api.app.modules.auth.router.service.login", new=AsyncMock(side_effect=slow_fail)) as login:
                    tasks = [asyncio.create_task(client.post("/api/v1/auth/login", json={"username": "u", "password": "p"})) for _ in range(5)]
                    await asyncio.sleep(0.3)  # as 5 chegam a rota antes de qualquer falha terminar
                    gate.set()
                    responses = await asyncio.gather(*tasks)
                return sorted(response.status_code for response in responses), login.await_count

        codes, calls = asyncio.run(scenario())
        self.assertEqual(codes, [401, 401, 429, 429, 429])
        self.assertEqual(calls, 2)

    def test_non_credential_error_does_not_count(self):
        boom = ApiError(error_codes.CONFIGURATION_ERROR, "Configuracao de autenticacao incompleta.", status_code=503)
        with patch("api.app.modules.auth.router.service.login", new=AsyncMock(side_effect=boom)):
            for _ in range(4):
                self.assertEqual(self._login().status_code, 503)
        self.assertEqual(ip_rate_limit._failures, {})

    def test_429_after_failures_and_success_does_not_count(self):
        fail = AuthenticationError(error_codes.INVALID_CREDENTIALS, "Usuario ou senha invalidos.")
        # JSONResponse e devolvida como esta (ignora response_model): simula login OK.
        with patch("api.app.modules.auth.router.service.login", new=AsyncMock(return_value=JSONResponse({}))):
            for _ in range(5):
                self.assertEqual(self._login().status_code, 200)
        with patch("api.app.modules.auth.router.service.login", new=AsyncMock(side_effect=fail)) as login:
            self.assertEqual(self._login().status_code, 401)
            self.assertEqual(self._login().status_code, 401)
            blocked = self._login()
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(blocked.json()["error"]["code"], error_codes.LOGIN_RATE_LIMITED)
            self.assertIn("Retry-After", blocked.headers)
            self.assertEqual(login.await_count, 2)  # o 3o nem chegou ao service


if __name__ == "__main__":
    unittest.main()
