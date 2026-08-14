from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from api.app.core.config import get_settings
from api.app.updates import paths
from api.app.updates.paths import UnsafeVersionSegmentError


class UpdatesPathsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._previous_env = os.environ.get("UPDATE_REPOSITORY_DIR")
        os.environ["UPDATE_REPOSITORY_DIR"] = self._tmp.name
        get_settings.cache_clear()

    def tearDown(self):
        if self._previous_env is None:
            os.environ.pop("UPDATE_REPOSITORY_DIR", None)
        else:
            os.environ["UPDATE_REPOSITORY_DIR"] = self._previous_env
        get_settings.cache_clear()

    def test_update_repository_root_resolves_absolute_configured_dir(self):
        self.assertEqual(paths.update_repository_root(), Path(self._tmp.name))

    def test_ensure_repository_dirs_creates_expected_layout(self):
        paths.ensure_repository_dirs()
        for directory in (paths.staging_dir(), paths.ready_dir(), paths.revoked_dir(), paths.state_dir(), paths.failed_dir()):
            self.assertTrue(directory.is_dir())

    def test_safe_version_segment_accepts_semver(self):
        self.assertEqual(paths.safe_version_segment("2.6.0"), "2.6.0")

    def test_safe_version_segment_rejects_traversal(self):
        with self.assertRaises(UnsafeVersionSegmentError):
            paths.safe_version_segment("../../etc/passwd")

    def test_safe_version_segment_rejects_non_semver(self):
        with self.assertRaises(UnsafeVersionSegmentError):
            paths.safe_version_segment("latest")

    def test_ready_version_dir_is_scoped_to_version(self):
        directory = paths.ready_version_dir("2.6.0")
        self.assertEqual(directory, paths.ready_dir() / "2.6.0")

    def test_resolve_ready_package_path_stays_inside_version_dir(self):
        version_dir = paths.ready_version_dir("2.6.0")
        version_dir.mkdir(parents=True)
        (version_dir / "Setup.exe").write_bytes(b"x")
        resolved = paths.resolve_ready_package_path("2.6.0", "Setup.exe")
        self.assertEqual(resolved, (version_dir / "Setup.exe").resolve())

    def test_resolve_ready_package_path_rejects_traversal_filename(self):
        with self.assertRaises(UnsafeVersionSegmentError):
            paths.resolve_ready_package_path("2.6.0", "../../../etc/passwd")


if __name__ == "__main__":
    unittest.main()
