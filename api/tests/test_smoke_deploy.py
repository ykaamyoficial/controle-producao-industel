"""scripts/smoke_deploy.py: etapas autenticadas, hardening, saida e exit code.

Parte 1: cliente falso (sem banco). Parte 2: app FastAPI in-process + PostgreSQL de teste
(mesmo guard das demais suites de integracao); nada toca rede real.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import unittest
from unittest.mock import patch

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import delete

from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.health.smoke import SmokeHttpResponse
from api.app.main import create_app
from api.tests._health_test_support import SmokeHttpAdapterOverTestClient
from api.tests._migration_test_support import TEST_DATABASE_URL, alembic_config, integration_enabled
from scripts import smoke_deploy

PASSWORD = "senha-smoke-super-secreta-123"
TOKEN = "token-smoke-xyz-" + "a" * 30
LISTS = (
    "/api/v1/proposals?limit=1", "/api/v1/warehouse/proposals?limit=1", "/api/v1/warehouse/items?limit=1",
    "/api/v1/inspections?limit=1", "/api/v1/logistics/logs?limit=1", "/api/v1/logistics/loads?limit=1",
)
ENV = {"SMOKE_USERNAME": "smoke.user", "SMOKE_PASSWORD": PASSWORD}
BASE = ["--base-url", "https://api.teste.invalid"]


class FakeApi:
    """Cliente falso: so get/post_json/set_bearer, registra o que foi chamado."""

    def __init__(self, overrides: dict[str, SmokeHttpResponse] | None = None, login: SmokeHttpResponse | None = None):
        page = {"items": [], "total": 0}
        self.routes = {
            "/api/v1/health/live": SmokeHttpResponse(200, {"status": "alive", "server_version": "1.0"}, ""),
            "/api/v1/health/ready": SmokeHttpResponse(200, {"overall_status": "HEALTHY"}, ""),
            "/api/v1/system/compatibility": SmokeHttpResponse(200, {"server_version": "1.0", "api_contract_version": "v1", "database_revision": "r"}, ""),
            "/api/v1/system/version": SmokeHttpResponse(200, {"api_version": "1.0", "database_revision": "r", "database_status": "ok"}, ""),
            "/api/v1/updates/desktop": SmokeHttpResponse(200, {"available": False}, ""),
            "/api/v1/auth/me": SmokeHttpResponse(200, {"id": 1, "username": "smoke.user", "permissions": []}, ""),
            "/docs": SmokeHttpResponse(404, {"detail": "Not Found"}, ""),
            "/redoc": SmokeHttpResponse(404, None, "Not Found"),
            "/openapi.json": SmokeHttpResponse(404, {"detail": "Not Found"}, ""),
            **{path: SmokeHttpResponse(200, page, "") for path in LISTS},
            **(overrides or {}),
        }
        self.login = login or SmokeHttpResponse(200, {"access_token": TOKEN, "refresh_token": "r" * 30}, "")
        self.calls: list[tuple[str, str]] = []
        self.bearer: str | None = None
        self.bearer_seen: list[str | None] = []

    def set_bearer(self, token):
        self.bearer = token

    def get(self, path, *, timeout):
        self.calls.append(("GET", path))
        self.bearer_seen.append(self.bearer)
        return self.routes[path]

    def post_json(self, path, payload, *, timeout):
        self.calls.append(("POST", path))
        return self.login


def run_cli(args, client, env=ENV):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = smoke_deploy.main(args, env=env, http_client=client)
    return code, out.getvalue(), err.getvalue()


class SmokeDeployFakeServerTests(unittest.TestCase):
    def test_success_runs_all_stages_and_only_login_is_post(self):
        api = FakeApi()
        code, out, _ = run_cli(BASE, api)
        self.assertEqual(code, 0, out)
        self.assertIn("RESULTADO: OK", out)
        for name in ("auth_login", "auth_me", "updates_discovery", "logistics_logs_list", "inspections_list", "warehouse_items_list"):
            self.assertIn(name, out)
        self.assertEqual([c for c in api.calls if c[0] != "GET"], [("POST", "/api/v1/auth/login")])
        self.assertTrue(set(LISTS) <= {p for _, p in api.calls})
        self.assertIsNone(api.bearer)  # token descartado ao final
        self.assertNotIn("/docs", [p for _, p in api.calls])  # hardening so com a flag

    def test_login_failure_fails_and_skips_authenticated_reads(self):
        api = FakeApi(login=SmokeHttpResponse(401, {"detail": f"credencial {PASSWORD} invalida"}, PASSWORD))
        code, out, err = run_cli(BASE, api)
        self.assertEqual(code, 1)
        self.assertIn("[FALHA] auth_login", out)
        self.assertIn("HTTP 401", out)
        self.assertNotIn("/api/v1/auth/me", [p for _, p in api.calls])
        self.assertNotIn(PASSWORD, out + err)

    def test_simulated_500_on_a_route_gives_nonzero_exit(self):
        api = FakeApi({"/api/v1/logistics/logs?limit=1": SmokeHttpResponse(500, {"detail": "segredo do servidor"}, "segredo do servidor")})
        code, out, _ = run_cli(BASE, api)
        self.assertEqual(code, 1)
        self.assertIn("[FALHA] logistics_logs_list", out)
        self.assertIn("HTTP 500", out)
        self.assertIn("RESULTADO: FALHA (1 de", out)
        self.assertNotIn("segredo do servidor", out)  # corpo da resposta nunca e impresso

    def test_password_and_token_never_in_output_text_or_json(self):
        for extra in ([], ["--json"]):
            _, out, err = run_cli(BASE + extra, FakeApi())
            self.assertNotIn(PASSWORD, out + err)
            self.assertNotIn(TOKEN, out + err)

    def test_secret_in_network_error_message_is_masked(self):
        class Boom(FakeApi):
            def post_json(self, path, payload, *, timeout):
                raise ConnectionError(f"falha com {payload['password']} no corpo")

        code, out, err = run_cli(BASE, Boom())
        self.assertEqual(code, 1)
        self.assertNotIn(PASSWORD, out + err)
        self.assertIn("***", out)

    def test_bearer_only_sent_after_login(self):
        api = FakeApi()
        run_cli(BASE, api)
        gets = [p for m, p in api.calls if m == "GET"]
        me_index = gets.index("/api/v1/auth/me")
        self.assertTrue(all(b is None for b in api.bearer_seen[:me_index]))
        self.assertTrue(all(b == TOKEN for b in api.bearer_seen[me_index:]))

    def test_skip_auth_runs_only_public_stages_and_needs_no_credentials(self):
        api = FakeApi()
        code, out, _ = run_cli(BASE + ["--skip-auth"], api, env={})
        self.assertEqual(code, 0, out)
        self.assertEqual([m for m, _ in api.calls if m == "POST"], [])
        self.assertNotIn("auth_login", out)
        self.assertIn("updates_discovery", out)

    def test_missing_credentials_without_tty_exits_2_without_calling_api(self):
        api = FakeApi()
        with patch("sys.stdin.isatty", return_value=False):
            code, _, err = run_cli(BASE, api, env={})
        self.assertEqual(code, 2)
        self.assertIn("SMOKE_PASSWORD", err)
        self.assertEqual(api.calls, [])

    def test_hardening_passes_when_docs_closed_and_fails_when_open(self):
        code, out, _ = run_cli(BASE + ["--skip-auth", "--expect-production-hardening"], FakeApi())
        self.assertEqual(code, 0, out)
        self.assertIn("hardening_closed/openapi.json", out)
        code, out, _ = run_cli(
            BASE + ["--skip-auth", "--expect-production-hardening"],
            FakeApi({"/openapi.json": SmokeHttpResponse(200, {"openapi": "3.1.0"}, "")}),
        )
        self.assertEqual(code, 1)
        self.assertIn("[FALHA] hardening_closed/openapi.json", out)

    def test_base_url_from_env_and_invalid_urls_rejected(self):
        code, _, _ = run_cli(["--skip-auth"], FakeApi(), env={"SMOKE_BASE_URL": "http://127.0.0.1:8001"})
        self.assertEqual(code, 0)
        for bad in ("ftp://x", "https://user:pw@host", "https://host/?token=1", "host-sem-esquema"):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                smoke_deploy.main(["--base-url", bad, "--skip-auth"], env={}, http_client=FakeApi())

    def test_real_httpx_client_sends_version_and_bearer_headers_to_loopback_server(self):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        from api.app.health.smoke import HttpxSmokeClient

        seen: list[tuple[str, str, str | None, str | None]] = []

        class Handler(BaseHTTPRequestHandler):
            def _reply(self):
                seen.append((self.command, self.path, self.headers.get("X-Client-Version"), self.headers.get("Authorization")))
                body = json.dumps({"ok": True}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = _reply

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = HttpxSmokeClient(f"http://127.0.0.1:{server.server_port}", client_version="9.9.9")
            client.post_json("/login", {"username": "u", "password": "p"}, timeout=5)
            client.set_bearer("tok")
            self.assertEqual(client.get("/x", timeout=5).status_code, 200)
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(seen, [("POST", "/login", "9.9.9", None), ("GET", "/x", "9.9.9", "Bearer tok")])

    def test_real_client_keeps_tls_verification_on(self):
        import inspect

        from api.app.health import smoke

        self.assertNotIn("verify", inspect.getsource(smoke.HttpxSmokeClient).replace("Sem verify=False", ""))
        self.assertNotIn("--insecure", inspect.getsource(smoke_deploy))


def _swap_env():
    previous = {k: os.environ.get(k) for k in ("DATABASE_URL", "APP_ENV", "SECRET_KEY")}
    os.environ["APP_ENV"] = "test"
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "smoke-deploy-integration-secret-key-32chars"
    get_settings.cache_clear()
    get_engine.cache_clear()
    return previous


@unittest.skipUnless(integration_enabled(), "Exige APP_ENV=test e POSTGRES_TEST_DATABASE_URL.")
class SmokeDeployInProcessTests(unittest.TestCase):
    """App real in-process + PostgreSQL de teste, com um superusuario criado so para o smoke."""

    @classmethod
    def setUpClass(cls):
        cls.previous = _swap_env()
        command.upgrade(alembic_config(), "head")
        asyncio.run(cls._seed())

    @classmethod
    async def _seed(cls):
        from api.app.modules.auth.bootstrap import sync_official_permissions
        from api.app.modules.auth.models import User
        from api.app.modules.auth.security import hash_password
        from api.app.modules.auth.tokens import utcnow

        await sync_official_permissions()
        async with get_sessionmaker()() as session:
            await session.execute(delete(User).where(User.username == "smoke.user"))
            session.add(User(username="smoke.user", display_name="Smoke", password_hash=hash_password(PASSWORD), active=True, is_superuser=True, password_changed_at=utcnow()))
            await session.commit()

    @classmethod
    def tearDownClass(cls):
        async def _cleanup():
            from api.app.modules.auth.models import User

            async with get_sessionmaker()() as session:
                await session.execute(delete(User).where(User.username == "smoke.user"))
                await session.commit()
            await dispose_engine()

        asyncio.run(_cleanup())
        for key, value in cls.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        get_engine.cache_clear()

    def _adapter(self):
        # raise_server_exceptions=False: um 500 vira resposta HTTP, como num servidor real.
        return SmokeHttpAdapterOverTestClient(TestClient(create_app(), raise_server_exceptions=False))

    def test_full_smoke_passes_against_real_app(self):
        code, out, err = run_cli(BASE, self._adapter())
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("[OK   ]"), 14, out)
        self.assertNotIn(PASSWORD, out + err)

    def test_wrong_password_fails_with_401(self):
        code, out, _ = run_cli(BASE, self._adapter(), env={"SMOKE_USERNAME": "smoke.user", "SMOKE_PASSWORD": "senha-errada-xyz-999"})
        self.assertEqual(code, 1)
        self.assertIn("[FALHA] auth_login", out)
        self.assertIn("HTTP 401", out)
        self.assertNotIn("senha-errada-xyz-999", out)

    def test_real_route_raising_500_gives_nonzero_exit(self):
        async def boom(*args, **kwargs):
            raise RuntimeError("falha simulada")

        with patch("api.app.modules.logistics.service.list_logs", boom):
            code, out, _ = run_cli(BASE, self._adapter())
        self.assertEqual(code, 1)
        self.assertIn("[FALHA] logistics_logs_list", out)
        self.assertIn("HTTP 500", out)

    def test_hardening_flag_fails_on_non_production_app_with_open_docs(self):
        code, out, _ = run_cli(BASE + ["--skip-auth", "--expect-production-hardening"], self._adapter())
        self.assertEqual(code, 1)
        self.assertIn("[FALHA] hardening_closed/docs", out)


if __name__ == "__main__":
    unittest.main()
