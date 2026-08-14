from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.updater import paths


class UpdaterPathsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch("app.updater.paths.get_app_data_dir", return_value=Path(self._tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_all_subdirs_are_nested_under_updater_root(self):
        root = paths.updater_root_dir()
        self.assertTrue(str(paths.staging_dir("r1")).startswith(str(root)))
        self.assertTrue(str(paths.backup_dir("r1")).startswith(str(root)))
        self.assertTrue(str(paths.download_dir("r1")).startswith(str(root)))
        self.assertTrue(str(paths.journal_dir()).startswith(str(root)))
        self.assertTrue(str(paths.updater_logs_dir()).startswith(str(root)))

    def test_staging_and_backup_are_namespaced_by_request_id(self):
        self.assertNotEqual(paths.staging_dir("r1"), paths.staging_dir("r2"))
        self.assertNotEqual(paths.backup_dir("r1"), paths.backup_dir("r2"))

    def test_ensure_updater_dirs_creates_expected_directories(self):
        paths.ensure_updater_dirs()
        self.assertTrue(paths.updater_root_dir().is_dir())
        self.assertTrue(paths.journal_dir().is_dir())
        self.assertTrue(paths.updater_logs_dir().is_dir())


if __name__ == "__main__":
    unittest.main()
