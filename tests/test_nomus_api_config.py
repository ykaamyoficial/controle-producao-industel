from __future__ import annotations

import json
import ssl
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError

from app.services.nomus_api_config import (
    NomusApiConfigError,
    NomusApiConfigStore,
    mask_api_key,
    normalize_base_url,
)


class FakeProtector:
    def protect(self, value: str) -> bytes:
        return f"protected:{value}".encode("utf-8")

    def unprotect(self, encrypted: bytes) -> str:
        text = encrypted.decode("utf-8")
        if not text.startswith("protected:"):
            raise ValueError("invalid blob")
        return text.removeprefix("protected:")


class NomusApiConfigTests(unittest.TestCase):
    def make_store(self, temp_dir: str, fetcher=None) -> NomusApiConfigStore:
        root = Path(temp_dir)
        return NomusApiConfigStore(
            config_path=root / "controle_producao_config.json",
            secret_path=root / "secrets" / "nomus_api_key.dpapi",
            protector=FakeProtector(),
            url_fetcher=fetcher,
        )

    def test_save_and_load_non_secret_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self.make_store(temp_dir)
            store.save_api_key("NOMUS-SECRET-1234")
            settings = store.save_settings(enabled=True, base_url=" https://example.nomus.com.br/industel/rest/// ")

            self.assertTrue(settings.enabled)
            self.assertEqual(settings.base_url, "https://example.nomus.com.br/industel/rest")
            self.assertTrue(settings.api_key_configured)
            self.assertEqual(settings.masked_api_key, "••••••••••••1234")

            config_text = (Path(temp_dir) / "controle_producao_config.json").read_text(encoding="utf-8")
            self.assertNotIn("NOMUS-SECRET-1234", config_text)
            self.assertIn("nomus_api", json.loads(config_text))

    def test_key_can_be_replaced_and_removed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self.make_store(temp_dir)
            store.save_api_key("FIRST-KEY")
            self.assertEqual(store.get_api_key(), "FIRST-KEY")

            store.save_api_key("SECOND-KEY")
            self.assertEqual(store.get_api_key(), "SECOND-KEY")

            store.delete_api_key()
            self.assertIsNone(store.get_api_key())

    def test_mask_does_not_expose_short_key(self):
        self.assertEqual(mask_api_key("abc"), "•••")
        self.assertEqual(mask_api_key("abcdef"), "••••••••••••cdef")

    def test_invalid_urls_are_blocked(self):
        with self.assertRaises(NomusApiConfigError):
            normalize_base_url("")
        with self.assertRaises(NomusApiConfigError):
            normalize_base_url("file:///tmp/key")
        with self.assertRaises(NomusApiConfigError):
            normalize_base_url("http://nomus.example.com/rest")

    def test_http_localhost_can_be_allowed_explicitly(self):
        self.assertEqual(
            normalize_base_url("http://localhost:8080/rest/", allow_http_local=True),
            "http://localhost:8080/rest",
        )

    def test_enabled_requires_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self.make_store(temp_dir)
            with self.assertRaises(NomusApiConfigError):
                store.save_settings(enabled=True, base_url="https://example.nomus.com.br/rest")

    def test_connection_success_uses_mock_without_internet(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self.make_store(temp_dir, fetcher=lambda _url, _timeout: 200)
            store.save_api_key("SECRET-KEY")
            store.save_settings(enabled=False, base_url="https://example.nomus.com.br/rest")

            result = store.test_connection()

            self.assertTrue(result.success)
            self.assertEqual(result.category, "success")
            self.assertEqual(result.status_code, 200)

    def test_connection_maps_http_statuses(self):
        cases = [(401, "unauthorized"), (403, "forbidden"), (404, "not_found"), (500, "server_error")]
        for status, expected in cases:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temp_dir:
                store = self.make_store(temp_dir, fetcher=lambda _url, _timeout, code=status: code)
                store.save_api_key("SECRET-KEY")
                store.save_settings(enabled=False, base_url="https://example.nomus.com.br/rest")
                self.assertEqual(store.test_connection().category, expected)

    def test_connection_maps_network_timeout_and_ssl(self):
        error_cases = [
            (lambda _url, _timeout: (_ for _ in ()).throw(TimeoutError("timeout")), "timeout"),
            (lambda _url, _timeout: (_ for _ in ()).throw(URLError("offline")), "network_error"),
            (lambda _url, _timeout: (_ for _ in ()).throw(ssl.SSLError("certificate")), "ssl_error"),
        ]
        for fetcher, expected in error_cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temp_dir:
                store = self.make_store(temp_dir, fetcher=fetcher)
                store.save_api_key("SECRET-KEY")
                store.save_settings(enabled=False, base_url="https://example.nomus.com.br/rest")
                result = store.test_connection()
                self.assertFalse(result.success)
                self.assertEqual(result.category, expected)

    def test_safe_dict_does_not_expose_secret(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self.make_store(temp_dir)
            store.save_api_key("SECRET-KEY-9999")
            settings = store.save_settings(enabled=False, base_url="https://example.nomus.com.br/rest")

            serialized = json.dumps(settings.safe_dict(), ensure_ascii=False)
            self.assertNotIn("SECRET-KEY-9999", serialized)
            self.assertIn("••••••••••••9999", serialized)


if __name__ == "__main__":
    unittest.main()
