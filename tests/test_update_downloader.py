from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from app.services.update_downloader import (
    UpdateDownloadError,
    download_update,
    expected_sha256,
    parse_sha256_text,
    select_asset,
    sha256_file,
)


class UpdateDownloaderTests(unittest.TestCase):
    def test_sha256_file_calculates_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "arquivo.exe"
            path.write_bytes(b"instalador")
            self.assertEqual(sha256_file(path), hashlib.sha256(b"instalador").hexdigest())

    def test_selects_exe_and_sha_assets(self):
        assets = [
            {"name": "ControleProducaoSetup-2.4.2.sha256"},
            {"name": "ControleProducaoSetup-2.4.2.exe"},
        ]
        self.assertEqual(select_asset(assets, ".exe")["name"], "ControleProducaoSetup-2.4.2.exe")
        self.assertEqual(select_asset(assets, ".sha256")["name"], "ControleProducaoSetup-2.4.2.sha256")

    def test_missing_asset_raises_clear_error(self):
        with self.assertRaises(UpdateDownloadError):
            select_asset([], ".exe")

    def test_parse_sha256_text(self):
        digest = hashlib.sha256(b"x").hexdigest()
        self.assertEqual(parse_sha256_text(f"{digest}  setup.exe"), digest)
        with self.assertRaises(UpdateDownloadError):
            parse_sha256_text("sem hash")

    def test_expected_hash_prefers_latest_json_hash(self):
        latest_hash = hashlib.sha256(b"latest").hexdigest()
        sha_hash = hashlib.sha256(b"sha").hexdigest()
        self.assertEqual(expected_sha256({"sha256": latest_hash}, f"{sha_hash}  setup.exe"), latest_hash)

    def test_download_and_validate_with_sha_asset(self):
        installer = b"conteudo do instalador"
        digest = hashlib.sha256(installer).hexdigest()
        update_info = {
            "assets": [
                {"name": "ControleProducaoSetup-2.4.2.exe", "browser_download_url": "https://example.com/app.exe"},
                {"name": "ControleProducaoSetup-2.4.2.sha256", "browser_download_url": "https://example.com/app.sha256"},
            ]
        }

        def fake_download(url: str, _timeout: int) -> bytes:
            if url.endswith(".exe"):
                return installer
            return f"{digest}  ControleProducaoSetup-2.4.2.exe".encode("utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            result = download_update(update_info, updates_dir=Path(tmp), download_bytes=fake_download)
            self.assertTrue(Path(result["installer_path"]).exists())
            self.assertTrue(Path(result["sha256_path"]).exists())
            self.assertEqual(result["sha256"], digest)

    def test_download_and_validate_with_latest_hash_only(self):
        installer = b"conteudo do instalador"
        digest = hashlib.sha256(installer).hexdigest()
        update_info = {
            "sha256": digest,
            "assets": [
                {"name": "ControleProducaoSetup-2.4.2.exe", "browser_download_url": "https://example.com/app.exe"},
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            result = download_update(update_info, updates_dir=Path(tmp), download_bytes=lambda _url, _timeout: installer)
            self.assertTrue(Path(result["installer_path"]).exists())
            self.assertIsNone(result["sha256_path"])

    def test_invalid_hash_discards_installer(self):
        update_info = {
            "sha256": hashlib.sha256(b"esperado").hexdigest(),
            "assets": [
                {"name": "ControleProducaoSetup-2.4.2.exe", "browser_download_url": "https://example.com/app.exe"},
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UpdateDownloadError):
                download_update(update_info, updates_dir=Path(tmp), download_bytes=lambda _url, _timeout: b"outro")
            self.assertFalse((Path(tmp) / "ControleProducaoSetup-2.4.2.exe").exists())

    def test_download_folder_is_created(self):
        installer = b"abc"
        digest = hashlib.sha256(installer).hexdigest()
        update_info = {
            "sha256": digest,
            "assets": [
                {"name": "ControleProducaoSetup-2.4.2.exe", "browser_download_url": "https://example.com/app.exe"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "updates"
            download_update(update_info, updates_dir=target, download_bytes=lambda _url, _timeout: installer)
            self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
