from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.integrations.api.config import DesktopApiConfigError, DesktopApiConfigStore, normalize_api_base_url


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
            normalize_api_base_url("http://servidor.local:8000")
        self.assertEqual(normalize_api_base_url("https://servidor.local/api/"), "https://servidor.local/api")


if __name__ == "__main__":
    unittest.main()
