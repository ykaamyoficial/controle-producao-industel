from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.updater.contract import UpdateRequest
from app.updater.precheck import run_local_precheck
from app.updater.validation import PackageValidationResult, PackageValidationStatus


def _request(install_dir: Path) -> UpdateRequest:
    return UpdateRequest(
        request_id="req-1", current_version="1.0.0", target_version="1.1.0",
        package_url_or_source="http://x/pkg.zip", install_dir=str(install_dir),
        executable_path=str(install_dir / "App.exe"), parent_pid=1234,
    )


class RunLocalPrecheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.install_dir = self.tmp / "install"
        self.install_dir.mkdir()
        self.staging_dir = self.tmp / "staging"
        self.staging_dir.mkdir()
        (self.staging_dir / "App.exe").write_text("new")
        self.backup_dir = self.tmp / "backup"
        self.valid_result = PackageValidationResult(PackageValidationStatus.VALID, "OK")

    def _run(self, **overrides):
        kwargs = dict(
            request=_request(self.install_dir), staging_dir=self.staging_dir, backup_dir=self.backup_dir,
            validation_result=self.valid_result, min_free_space_mb=1,
        )
        kwargs.update(overrides)
        return run_local_precheck(**kwargs)

    def test_valid_conditions_pass(self):
        result = self._run()
        self.assertTrue(result.ok)

    def test_empty_staging_fails(self):
        empty_staging = self.tmp / "empty_staging"
        empty_staging.mkdir()
        result = self._run(staging_dir=empty_staging)
        self.assertFalse(result.ok)

    def test_missing_staging_fails(self):
        result = self._run(staging_dir=self.tmp / "does-not-exist")
        self.assertFalse(result.ok)

    def test_invalid_package_status_fails(self):
        invalid = PackageValidationResult(PackageValidationStatus.INVALID_HASH, "hash mismatch")
        result = self._run(validation_result=invalid)
        self.assertFalse(result.ok)

    def test_missing_metadata_status_is_accepted(self):
        missing = PackageValidationResult(PackageValidationStatus.MISSING_METADATA, "no hash provided")
        result = self._run(validation_result=missing)
        self.assertTrue(result.ok)

    def test_existing_backup_dir_fails(self):
        self.backup_dir.mkdir()
        result = self._run()
        self.assertFalse(result.ok)

    def test_insufficient_disk_space_fails(self):
        result = self._run(min_free_space_mb=10 ** 9, disk_usage_fn=lambda path: type("U", (), {"free": 1024})())
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
