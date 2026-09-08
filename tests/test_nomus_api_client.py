from __future__ import annotations

import json
import ssl
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError

from app.services.nomus_api_client import (
    NomusApiClient,
    NomusApiClientError,
    NomusHttpResponse,
    _build_headers,
    _basic_auth_token,
)
from app.services.nomus_api_config import NomusApiConfigStore, NomusApiSecretError


SECRET = "NOMUS-SECRET-KEY"


class FakeTransport:
    def __init__(self, response: NomusHttpResponse | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, headers: dict[str, str], timeout_seconds: int) -> NomusHttpResponse:
        self.calls.append({"url": url, "headers": dict(headers), "timeout": timeout_seconds})
        if self.error:
            raise self.error
        assert self.response is not None
        return self.response


class FakeProtector:
    def protect(self, value: str) -> bytes:
        return value.encode("utf-8")

    def unprotect(self, encrypted: bytes) -> str:
        return encrypted.decode("utf-8")


class BrokenProtector:
    def unprotect(self, encrypted: bytes) -> str:
        raise NomusApiSecretError("DPAPI unavailable")


class NomusApiClientTests(unittest.TestCase):
    def make_store(self, temp_dir: str, api_key: str = SECRET, base_url: str = "https://example.nomus.com.br/erp/rest") -> NomusApiConfigStore:
        root = Path(temp_dir)
        store = NomusApiConfigStore(
            config_path=root / "config.json",
            secret_path=root / "secrets" / "nomus_api_key.dpapi",
            protector=FakeProtector(),
        )
        store.save_api_key(api_key)
        store.save_settings(enabled=False, base_url=base_url)
        return store

    def test_build_headers_follow_official_basic_base64_without_secret(self):
        headers = _build_headers(SECRET)

        self.assertEqual(headers["Authorization"], "Basic Tk9NVVMtU0VDUkVULUtFWQ==")
        self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertNotIn(SECRET, json.dumps(headers))

    def test_successful_json_get_never_places_key_in_url_or_repr(self):
        transport = FakeTransport(NomusHttpResponse(200, "application/json", '{"id": 1}', "https://example.nomus.com.br/erp/rest/produtos"))
        client = NomusApiClient(base_url="https://example.nomus.com.br/erp/rest", api_key=SECRET, transport=transport)

        result = client.test_authenticated_connection()

        self.assertTrue(result.success)
        self.assertEqual(result.category, "success")
        self.assertTrue(result.authentication_confirmed)
        self.assertNotIn(SECRET, str(result))
        self.assertNotIn(SECRET, repr(client))
        self.assertNotIn(SECRET, str(transport.calls[0]["url"]))
        self.assertIn("/produtos", str(transport.calls[0]["url"]))

    def test_build_headers_does_not_double_encode_base64_key(self):
        encoded_key = "Tk9NVVMtU0VDUkVULUtFWQ=="

        self.assertEqual(_basic_auth_token(encoded_key), encoded_key)
        self.assertEqual(_build_headers(encoded_key)["Authorization"], f"Basic {encoded_key}")

    def test_get_rejects_absolute_or_empty_endpoint(self):
        client = NomusApiClient(base_url="https://example.nomus.com.br/erp/rest", api_key=SECRET, transport=FakeTransport())

        with self.assertRaises(NomusApiClientError):
            client.get("https://evil.example/test")
        with self.assertRaises(NomusApiClientError):
            client.get("")

    def test_http_statuses_are_mapped(self):
        cases = [
            (400, "invalid_configuration"),
            (401, "invalid_key"),
            (403, "forbidden"),
            (404, "not_found"),
            (405, "method_not_allowed"),
            (408, "timeout"),
            (429, "rate_limited"),
            (500, "server_error"),
        ]
        for status, expected in cases:
            with self.subTest(status=status):
                transport = FakeTransport(NomusHttpResponse(status, "application/json", '{"erro": true}', "https://example.nomus.com.br/erp/rest/produtos"))
                client = NomusApiClient(base_url="https://example.nomus.com.br/erp/rest", api_key=SECRET, transport=transport)
                result = client.test_authenticated_connection()
                self.assertFalse(result.success)
                self.assertEqual(result.category, expected)
                self.assertEqual(result.status_code, status)

    def test_nomus_406_unauthenticated_json_is_mapped_to_invalid_key_with_diagnostic(self):
        body = '{"descricao":"ERRO","erros":[{"codigo":"integracao.naoAutenticada","mensagem":"Acesso nao autorizado"}],"status":406}'
        transport = FakeTransport(NomusHttpResponse(406, "application/json", body, "https://example.nomus.com.br/erp/rest/pedidos"))
        client = NomusApiClient(base_url="https://example.nomus.com.br/erp/rest", api_key=SECRET, transport=transport)

        result = client.test_authenticated_connection()

        self.assertFalse(result.success)
        self.assertEqual(result.category, "invalid_key")
        self.assertIn("http_status=406", result.technical_message or "")
        self.assertIn("error_codes=integracao.naoAutenticada", result.technical_message or "")

    def test_network_timeout_and_ssl_errors_are_mapped(self):
        cases = [
            (TimeoutError("slow"), "timeout"),
            (URLError("offline"), "network_error"),
            (ssl.SSLError("certificate"), "ssl_error"),
        ]
        for error, expected in cases:
            with self.subTest(expected=expected):
                client = NomusApiClient(base_url="https://example.nomus.com.br/erp/rest", api_key=SECRET, transport=FakeTransport(error=error))
                result = client.test_authenticated_connection()
                self.assertFalse(result.success)
                self.assertEqual(result.category, expected)

    def test_invalid_json_html_redirect_and_empty_body_are_blocked(self):
        cases = [
            (NomusHttpResponse(200, "application/json", "{bad", "https://example.nomus.com.br/erp/rest/produtos"), "invalid_json"),
            (NomusHttpResponse(200, "text/html", "<html>login</html>", "https://example.nomus.com.br/login"), "login_redirect"),
            (NomusHttpResponse(302, "text/html", "", "https://example.nomus.com.br/login"), "login_redirect"),
            (NomusHttpResponse(200, "application/json", "", "https://example.nomus.com.br/erp/rest/produtos"), "unexpected_response"),
            (NomusHttpResponse(200, "text/plain", "ok", "https://example.nomus.com.br/erp/rest/produtos"), "unexpected_response"),
        ]
        for response, expected in cases:
            with self.subTest(expected=expected):
                client = NomusApiClient(base_url="https://example.nomus.com.br/erp/rest", api_key=SECRET, transport=FakeTransport(response))
                result = client.test_authenticated_connection()
                self.assertFalse(result.success)
                self.assertEqual(result.category, expected)

    def test_missing_or_invalid_configuration_is_reported_without_network(self):
        for kwargs in (
            {"base_url": "", "api_key": SECRET},
            {"base_url": "http://example.nomus.com.br/rest", "api_key": SECRET},
            {"base_url": "https://example.nomus.com.br/rest", "api_key": ""},
        ):
            with self.subTest(kwargs=kwargs):
                transport = FakeTransport(NomusHttpResponse(200, "application/json", "{}", "https://example.nomus.com.br/rest/produtos"))
                client = NomusApiClient(transport=transport, **kwargs)
                result = client.test_authenticated_connection()
                self.assertFalse(result.success)
                self.assertEqual(result.category, "invalid_configuration")
                self.assertEqual(transport.calls, [])

    def test_config_store_secret_error_is_sanitized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            secret_path = root / "secrets" / "nomus_api_key.dpapi"
            secret_path.parent.mkdir(parents=True)
            secret_path.write_bytes(b"encrypted")
            store = NomusApiConfigStore(
                config_path=root / "config.json",
                secret_path=secret_path,
                protector=BrokenProtector(),
            )
            root.joinpath("config.json").write_text(json.dumps({"nomus_api": {"base_url": "https://example.nomus.com.br/rest"}}), encoding="utf-8")

            result = NomusApiClient(config_store=store, transport=FakeTransport()).test_authenticated_connection()

            self.assertFalse(result.success)
            self.assertEqual(result.category, "invalid_configuration")
            self.assertNotIn("encrypted", str(result))


if __name__ == "__main__":
    unittest.main()
