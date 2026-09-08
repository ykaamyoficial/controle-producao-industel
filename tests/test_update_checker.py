from __future__ import annotations

import json
import unittest

from app.services.update_checker import check_for_updates, is_newer_version, parse_github_release


class UpdateCheckerTests(unittest.TestCase):
    def test_version_comparison(self):
        self.assertTrue(is_newer_version("2.4.1", "2.4.0"))
        self.assertTrue(is_newer_version("v2.5.0", "2.4.9"))
        self.assertFalse(is_newer_version("2.4.0", "2.4.0"))
        self.assertFalse(is_newer_version("2.3.9", "2.4.0"))

    def test_parse_github_response(self):
        payload = {
            "tag_name": "v2.4.1",
            "published_at": "2026-06-23T12:00:00Z",
            "body": "Notas da versao",
            "assets": [
                {
                    "name": "ControleProducaoSetup-2.4.1.exe",
                    "browser_download_url": "https://example.com/setup.exe",
                    "size": 123,
                    "content_type": "application/octet-stream",
                }
            ],
        }
        result = parse_github_release(payload, current_version="2.4.0")
        self.assertTrue(result["update_available"])
        self.assertEqual(result["current_version"], "2.4.0")
        self.assertEqual(result["latest_version"], "2.4.1")
        self.assertEqual(result["published_at"], "2026-06-23T12:00:00Z")
        self.assertEqual(result["release_notes"], "Notas da versao")
        self.assertEqual(result["assets"][0]["name"], "ControleProducaoSetup-2.4.1.exe")

    def test_check_for_updates_uses_injected_fetcher_without_internet(self):
        def fake_fetch(_url: str, _timeout: int):
            return {"tag_name": "v2.4.0", "published_at": None, "body": "", "assets": []}

        result = check_for_updates(current_version="2.4.0", fetch_json=fake_fetch)
        self.assertFalse(result["update_available"])
        self.assertNotIn("error", result)

    def test_error_is_returned_without_raising(self):
        def failing_fetch(_url: str, _timeout: int):
            raise OSError("sem conexao")

        result = check_for_updates(current_version="2.4.0", fetch_json=failing_fetch)
        self.assertFalse(result["update_available"])
        self.assertEqual(result["current_version"], "2.4.0")
        self.assertIn("sem conexao", result["error"])

    def test_invalid_json_error_shape(self):
        def failing_fetch(_url: str, _timeout: int):
            raise json.JSONDecodeError("erro", "x", 0)

        result = check_for_updates(current_version="2.4.0", fetch_json=failing_fetch)
        self.assertFalse(result["update_available"])
        self.assertIn("erro", result["error"])


if __name__ == "__main__":
    unittest.main()
