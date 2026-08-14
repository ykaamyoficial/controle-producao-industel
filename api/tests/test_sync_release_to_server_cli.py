from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.app.core.config import get_settings  # noqa: E402
from api.app.updates import service  # noqa: E402
from api.app.updates.models import ReleaseState  # noqa: E402
from scripts.sync_release_to_server import main  # noqa: E402


class SyncReleaseToServerCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self._previous_repo_dir = os.environ.get("UPDATE_REPOSITORY_DIR")
        self._previous_secret = os.environ.get("SECRET_KEY")
        os.environ["UPDATE_REPOSITORY_DIR"] = str(self.tmp / "repo")
        os.environ["SECRET_KEY"] = "local-test-only-secret-key-32-characters-min"
        get_settings.cache_clear()

    def tearDown(self):
        for key, value in (("UPDATE_REPOSITORY_DIR", self._previous_repo_dir), ("SECRET_KEY", self._previous_secret)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()

    def _write_manifest_and_package(self, version: str = "2.6.0") -> tuple[Path, Path]:
        package = self.tmp / f"pkg-{version}.exe"
        package.write_bytes(b"conteudo-do-instalador" * 500)
        manifest_data = {
            "manifest_schema_version": 1, "release_version": version, "channel": "production",
            "published_at": "2026-08-11T12:00:00Z", "minimum_server_version": "0.8.0", "api_contract_version": "v1",
            "artifact": {"filename": package.name, "size_bytes": package.stat().st_size, "sha256": hashlib.sha256(package.read_bytes()).hexdigest()},
        }
        manifest_path = self.tmp / f"manifest-{version}.json"
        manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
        return manifest_path, package

    def test_sync_without_authorize_leaves_release_ready(self):
        manifest_path, package_path = self._write_manifest_and_package()
        exit_code = main(["--manifest", str(manifest_path), "--package", str(package_path), "--source", "ci-pipeline"])
        self.assertEqual(exit_code, 0)
        record = service._state_store().load("2.6.0")
        self.assertEqual(record.state, ReleaseState.READY)
        self.assertEqual(record.source, "ci-pipeline")

    def test_sync_with_authorize_flag_authorizes_in_same_call(self):
        manifest_path, package_path = self._write_manifest_and_package()
        exit_code = main(["--manifest", str(manifest_path), "--package", str(package_path), "--authorize"])
        self.assertEqual(exit_code, 0)
        record = service._state_store().load("2.6.0")
        self.assertEqual(record.state, ReleaseState.AUTHORIZED)

    def test_invalid_manifest_returns_nonzero_exit_code(self):
        bad_manifest = self.tmp / "bad.json"
        bad_manifest.write_text('{"manifest_schema_version": 99}', encoding="utf-8")
        _, package_path = self._write_manifest_and_package()
        exit_code = main(["--manifest", str(bad_manifest), "--package", str(package_path)])
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
