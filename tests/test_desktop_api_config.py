from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from app.integrations.api.config import (
    API_BASE_URL_ENV_OVERRIDE,
    DesktopApiConfigError,
    DesktopApiConfigStore,
    normalize_api_base_url,
)


class DesktopApiConfigTests(unittest.TestCase):
    def test_default_settings_are_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = DesktopApiConfigStore(config_path=Path(temp_dir) / "config.json").load_settings()
            self.assertFalse(settings.enabled)
            self.assertEqual(settings.base_url, "http://127.0.0.1:8000")

    def test_save_and_load_settings_without_secrets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            store = DesktopApiConfigStore(config_path=path)
            settings = store.save_settings(enabled=True, base_url=" http://127.0.0.1:8000/// ", connect_timeout=2, read_timeout=8)
            self.assertTrue(settings.enabled)
            self.assertEqual(settings.base_url, "http://127.0.0.1:8000")
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("desktop_api", raw)
            self.assertNotIn("password", path.read_text(encoding="utf-8").lower())
            self.assertNotIn("refresh", path.read_text(encoding="utf-8").lower())

    def test_url_validation(self):
        with self.assertRaises(DesktopApiConfigError):
            normalize_api_base_url("file:///tmp/api")
        with self.assertRaises(DesktopApiConfigError):
            normalize_api_base_url("")
        with self.assertRaises(DesktopApiConfigError):
            normalize_api_base_url("   ")
        self.assertEqual(normalize_api_base_url("https://servidor.local/api/"), "https://servidor.local/api")

    def test_lan_ip_and_internal_dns_over_http_are_valid(self):
        # Fase 1 estabeleceu http://<servidor>:8000 como endereco oficial da
        # LAN; a Fase 2 precisa aceita-lo (HTTPS so chega na Fase 5).
        self.assertEqual(normalize_api_base_url("http://192.168.1.50:8000"), "http://192.168.1.50:8000")
        self.assertEqual(normalize_api_base_url("http://api.industel.local"), "http://api.industel.local")
        self.assertEqual(normalize_api_base_url(" http://192.168.1.50:8000/// "), "http://192.168.1.50:8000")

    def test_bind_address_is_rejected_as_client_url(self):
        # 0.0.0.0 e endereco de bind do servidor, nunca um endereco que o
        # Desktop deva acessar -- precisa ser rejeitado em qualquer esquema.
        with self.assertRaises(DesktopApiConfigError):
            normalize_api_base_url("http://0.0.0.0:8000")
        with self.assertRaises(DesktopApiConfigError):
            normalize_api_base_url("https://0.0.0.0:8000")

    def test_env_override_takes_precedence_over_persisted_file(self):
        previous = os.environ.get(API_BASE_URL_ENV_OVERRIDE)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "config.json"
                store = DesktopApiConfigStore(config_path=path)
                store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")

                os.environ[API_BASE_URL_ENV_OVERRIDE] = "http://192.168.1.99:8000"
                settings = store.load_settings()

                self.assertEqual(settings.base_url, "http://192.168.1.99:8000")
                self.assertTrue(settings.enabled, "override troca so a URL, nao o restante da configuracao persistida")
        finally:
            if previous is None:
                os.environ.pop(API_BASE_URL_ENV_OVERRIDE, None)
            else:
                os.environ[API_BASE_URL_ENV_OVERRIDE] = previous

    def test_changing_server_address_clears_local_token_session(self):
        # Fase 3, Secao 17: sessao/token do servidor anterior nao pode ser
        # reaproveitado quando API_BASE_URL muda para outro host.
        class FakeTokenStore:
            def __init__(self):
                self.cleared = False

            def clear(self):
                self.cleared = True

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            fake_token_store = FakeTokenStore()
            store = DesktopApiConfigStore(config_path=path, token_store=fake_token_store)
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")
            self.assertFalse(fake_token_store.cleared, "primeira gravacao nao e uma troca de servidor")

            store.save_settings(enabled=True, base_url="http://192.168.1.99:8000")

            self.assertTrue(fake_token_store.cleared)

    def test_saving_same_server_address_again_does_not_clear_session(self):
        class FakeTokenStore:
            def __init__(self):
                self.cleared = False

            def clear(self):
                self.cleared = True

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            fake_token_store = FakeTokenStore()
            store = DesktopApiConfigStore(config_path=path, token_store=fake_token_store)
            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")

            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000", connect_timeout=5)

            self.assertFalse(fake_token_store.cleared)

    def test_is_configured_reflects_persisted_base_url_not_in_memory_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            store = DesktopApiConfigStore(config_path=path)
            self.assertFalse(store.is_configured())
            self.assertEqual(store.load_settings().base_url, "http://127.0.0.1:8000")  # default em memoria, nao persistido

            store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")

            self.assertTrue(store.is_configured())

    def test_without_env_override_persisted_value_is_used(self):
        previous = os.environ.pop(API_BASE_URL_ENV_OVERRIDE, None)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "config.json"
                store = DesktopApiConfigStore(config_path=path)
                store.save_settings(enabled=True, base_url="http://192.168.1.50:8000")

                settings = store.load_settings()

                self.assertEqual(settings.base_url, "http://192.168.1.50:8000")
        finally:
            if previous is not None:
                os.environ[API_BASE_URL_ENV_OVERRIDE] = previous


if __name__ == "__main__":
    unittest.main()
