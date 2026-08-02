from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import httpx

from app.integrations.api.auth_client import AuthApiClient
from app.integrations.api.client import DesktopApiClient
from app.integrations.api.compatibility import compatibility_report
from app.integrations.api.config import DesktopApiSettings
from app.integrations.api.exceptions import ApiBusinessError, ApiConnectionError, ApiPermissionError, ApiSessionExpiredError, ApiTimeoutError, ApiUnavailableError, ApiUnexpectedResponseError, ApiValidationError
from app.integrations.api.models import SystemIdentity, SystemVersion
from app.integrations.api.proposals_client import ProposalsApiClient
from app.integrations.api.session import ExperimentalApiSession
from app.integrations.api.token_store import ApiTokenStore


class FakeProtector:
    def protect(self, value: str) -> bytes:
        return ("protected:" + value.encode("utf-8").hex()).encode("ascii")

    def unprotect(self, encrypted: bytes) -> str:
        text = encrypted.decode("utf-8")
        if not text.startswith("protected:"):
            raise ValueError("invalid")
        return bytes.fromhex(text.removeprefix("protected:")).decode("utf-8")


def settings() -> DesktopApiSettings:
    return DesktopApiSettings(enabled=True, base_url="http://127.0.0.1:8000", connect_timeout=1, read_timeout=1)


class DesktopApiClientTests(unittest.TestCase):
    def test_headers_include_request_id_and_do_not_require_token(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["request_id"] = request.headers.get("X-Request-ID")
            seen["authorization"] = request.headers.get("Authorization")
            return httpx.Response(200, json={"status": "healthy", "service": "api"}, headers={"X-Request-ID": "server-id"})

        client = DesktopApiClient(settings(), transport=httpx.MockTransport(handler))
        response = client.get("/api/v1/system/health")
        self.assertTrue(seen["request_id"])
        self.assertIsNone(seen["authorization"])
        self.assertEqual(response.request_id, "server-id")
        client.close()

    def test_error_mapping(self):
        cases = [
            (401, "TOKEN_EXPIRED", ApiSessionExpiredError),
            (403, "PERMISSION_DENIED", ApiPermissionError),
            (503, "DATABASE_UNAVAILABLE", ApiUnavailableError),
        ]
        for status, code, expected in cases:
            with self.subTest(status=status):
                client = DesktopApiClient(
                    settings(),
                    transport=httpx.MockTransport(lambda _request, s=status, c=code: httpx.Response(s, json={"error": {"code": c, "message": "erro"}})),
                )
                with self.assertRaises(expected):
                    client.get("/api/v1/auth/me", access_token="ACCESS-TOKEN")
                client.close()

    def test_business_error_preserves_official_code(self):
        client = DesktopApiClient(
            settings(),
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    409,
                    json={"error": {"code": "PROPOSAL_VERSION_CONFLICT", "message": "versao conflitante"}},
                    headers={"content-type": "application/json"},
                )
            ),
        )
        with self.assertRaises(ApiBusinessError) as ctx:
            client.patch("/api/v1/proposals/1", json_payload={"version": 1}, access_token="ACCESS")
        self.assertEqual(ctx.exception.error_code, "PROPOSAL_VERSION_CONFLICT")
        client.close()

    def test_not_found_business_error_preserves_official_code(self):
        client = DesktopApiClient(
            settings(),
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    404,
                    json={"error": {"code": "PROPOSAL_NOT_FOUND", "message": "proposta nao encontrada"}},
                    headers={"content-type": "application/json"},
                )
            ),
        )
        with self.assertRaises(ApiBusinessError) as ctx:
            client.get("/api/v1/proposals/404", access_token="ACCESS")
        self.assertEqual(ctx.exception.error_code, "PROPOSAL_NOT_FOUND")
        self.assertEqual(ctx.exception.status_code, 404)
        client.close()

    def test_validation_error_and_server_error_are_mapped(self):
        cases = [
            (400, "PASSWORD_POLICY_VIOLATION", ApiValidationError),
            (422, "VALIDATION_ERROR", ApiValidationError),
            (500, "INTERNAL_ERROR", ApiUnexpectedResponseError),
        ]
        for status, code, expected in cases:
            with self.subTest(status=status):
                client = DesktopApiClient(
                    settings(),
                    transport=httpx.MockTransport(
                        lambda _request, s=status, c=code: httpx.Response(
                            s,
                            json={"error": {"code": c, "message": "erro"}},
                            headers={"content-type": "application/json"},
                        )
                    ),
                )
                with self.assertRaises(expected):
                    client.post("/api/v1/proposals", json_payload={}, access_token="ACCESS")
                client.close()

    def test_invalid_json_is_mapped(self):
        client = DesktopApiClient(settings(), transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"})))
        with self.assertRaises(ApiUnexpectedResponseError):
            client.get("/api/v1/system/health")
        client.close()

    def test_timeout_and_connection_errors(self):
        for exc, expected in [(httpx.ReadTimeout("timeout"), ApiTimeoutError), (httpx.ConnectError("offline"), ApiConnectionError)]:
            with self.subTest(expected=expected):
                client = DesktopApiClient(settings(), transport=httpx.MockTransport(lambda _request, e=exc: (_ for _ in ()).throw(e)))
                with self.assertRaises(expected):
                    client.get("/api/v1/system/health")
                client.close()

    def test_retries_only_idempotent_gets(self):
        calls = {"count": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            if calls["count"] == 1:
                raise httpx.ConnectError("transient")
            return httpx.Response(200, json={"status": "healthy"})

        client = DesktopApiClient(settings(), transport=httpx.MockTransport(handler))
        self.assertEqual(client.get("/api/v1/system/health").status_code, 200)
        self.assertEqual(calls["count"], 2)
        client.close()

    def test_token_store_uses_protected_file_and_clears(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "token.dpapi"
            store = ApiTokenStore(secret_path=path, protector=FakeProtector())
            store.save_refresh_token("REFRESH-TOKEN-123")
            self.assertNotIn("REFRESH-TOKEN-123", path.read_text(encoding="utf-8"))
            self.assertEqual(store.get_refresh_token(), "REFRESH-TOKEN-123")
            store.clear()
            self.assertFalse(path.exists())

    def test_session_replaces_refresh_token_and_permission_check(self):
        class FakeAuth:
            def __init__(self):
                self.calls = 0

            def login(self, _username, _password):
                self.calls += 1
                return _pair("A1", "R1")

            def refresh(self, _refresh):
                self.calls += 1
                return _pair("A2", "R2")

        with tempfile.TemporaryDirectory() as temp_dir:
            store = ApiTokenStore(secret_path=Path(temp_dir) / "token.dpapi", protector=FakeProtector())
            session = ExperimentalApiSession(settings=settings(), auth_client=FakeAuth(), token_store=store)
            state = session.start("admin", "senha")
            self.assertTrue(state.has_permission("users.view"))
            session.refresh_if_needed(force=True)
            self.assertEqual(store.get_refresh_token(), "R2")

    def test_compatibility_requires_supported_features(self):
        version = SystemVersion("0.3.0", "authentication-foundation", "20260720_0002", "compatible", "2.5.2", None, ["auth"])
        result = compatibility_report(version)
        self.assertFalse(result.compatible)
        self.assertIn("auth_me", result.missing_features)

    def test_company_identity_validation_blocks_wrong_company(self):
        from app.integrations.api.compatibility import validate_company_identity
        from app.integrations.api.exceptions import ApiCompatibilityError

        identity = _identity(company_code="outra")
        with self.assertRaises(ApiCompatibilityError):
            validate_company_identity(identity, expected_company_code="teste01", expected_environment_type="production")

    def test_company_identity_validation_accepts_matching_company(self):
        from app.integrations.api.compatibility import validate_company_identity

        result = validate_company_identity(_identity(), expected_company_code="TESTE01", expected_environment_type="production")
        self.assertTrue(result.compatible)

    def test_production_client_methods_use_official_routes(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, request.url.path, request.url.query.decode(), request.content.decode()))
            return httpx.Response(200, json={"items": [], "total": 0, "limit": 50, "offset": 0} if request.method == "GET" and request.url.path.endswith("/production/proposals") else {"id": 10, "version": 2}, headers={"content-type": "application/json"})

        client = DesktopApiClient(settings(), transport=httpx.MockTransport(handler))
        proposals = ProposalsApiClient(client)

        proposals.list_production_proposals("ACCESS", search="CP", status="NAO_INICIADO")
        proposals.get_production_detail("ACCESS", 10)
        proposals.start_production("ACCESS", 10, {"version": 1})
        proposals.update_production_item_flow("ACCESS", 10, {"version": 2, "items": []})
        proposals.update_production_item_weights("ACCESS", 10, {"version": 3, "items": []})
        proposals.complete_production_items("ACCESS", 10, {"version": 4})

        self.assertEqual(seen[0][1], "/api/v1/production/proposals")
        self.assertIn("search=CP", seen[0][2])
        self.assertEqual(seen[1][1], "/api/v1/production/proposals/10")
        self.assertEqual(seen[2][1], "/api/v1/production/proposals/10/start")
        self.assertEqual(seen[3][1], "/api/v1/production/proposals/10/item-flow")
        self.assertEqual(seen[4][1], "/api/v1/production/proposals/10/item-weights")
        self.assertEqual(seen[5][1], "/api/v1/production/proposals/10/complete-items")
        client.close()


def _pair(access: str, refresh: str):
    from app.integrations.api.models import ApiUser, TokenPair

    user = ApiUser(id=1, username="admin", display_name="Admin", active=True, is_superuser=True, permissions=["users.view"])
    return TokenPair(access_token=access, refresh_token=refresh, expires_in=900, user=user)


def _identity(company_code: str = "teste01", environment_type: str = "production") -> SystemIdentity:
    return SystemIdentity(
        instance_id="35df9bf2-7597-4e79-a3af-f0d788a72fa4",
        company_id=None,
        company_code=company_code,
        company_name=company_code,
        environment_type=environment_type,
        api_name="controle-producao-api",
        api_version="0.8.0",
        api_stage="official-fiscal",
        database_revision="20260722_0009",
        database_status="compatible",
        minimum_desktop_version="2.5.2",
        maximum_desktop_version=None,
        supported_features=["auth", "auth_me", "permissions_read", "refresh", "logout"],
    )


if __name__ == "__main__":
    unittest.main()
