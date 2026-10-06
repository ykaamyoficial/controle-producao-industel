from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.updater.elevation import is_writable, relaunch_elevated


class IsWritableTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_existing_writable_directory_is_true(self):
        self.assertTrue(is_writable(self.tmp))

    def test_missing_directory_falls_back_to_parent(self):
        missing = self.tmp / "does-not-exist-yet"
        self.assertTrue(is_writable(missing))

    def test_missing_directory_and_missing_parent_is_false(self):
        missing = self.tmp / "gone" / "still-gone"
        self.assertFalse(is_writable(missing))

    def test_probe_file_is_cleaned_up(self):
        is_writable(self.tmp)
        leftovers = list(self.tmp.glob(".updater-elevation-check.tmp"))
        self.assertEqual(leftovers, [])


class RelaunchElevatedTests(unittest.TestCase):
    def test_success_when_shell_execute_returns_above_32(self):
        fake_shell32 = unittest.mock.Mock()
        fake_shell32.ShellExecuteW.return_value = 42
        with patch("app.updater.elevation.ctypes.windll", unittest.mock.Mock(shell32=fake_shell32), create=True):
            self.assertTrue(relaunch_elevated(["--request", "req.json"]))

    def test_failure_when_shell_execute_returns_32_or_less(self):
        fake_shell32 = unittest.mock.Mock()
        fake_shell32.ShellExecuteW.return_value = 5
        with patch("app.updater.elevation.ctypes.windll", unittest.mock.Mock(shell32=fake_shell32), create=True):
            self.assertFalse(relaunch_elevated(["--request", "req.json"]))

    def test_failure_when_shell_execute_raises(self):
        fake_shell32 = unittest.mock.Mock()
        fake_shell32.ShellExecuteW.side_effect = OSError("boom")
        with patch("app.updater.elevation.ctypes.windll", unittest.mock.Mock(shell32=fake_shell32), create=True):
            self.assertFalse(relaunch_elevated(["--request", "req.json"]))


if __name__ == "__main__":
    unittest.main()
