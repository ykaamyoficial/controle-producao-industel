from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.launcher import launcher
from app.updater import versions as v


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _install(self, version: str) -> Path:
        folder = self.root / "versions" / version
        folder.mkdir(parents=True)
        (folder / v.APP_EXECUTABLE_NAME).write_text("x")
        return folder

    def test_launches_pointed_version_forwarding_args(self):
        self._install("2.8.0")
        folder = self._install("2.9.0")
        v.write_pointer(self.root, "2.9.0")
        popen = mock.Mock()
        code = launcher.launch(self.root, ["--post-update", "abc"], popen=popen)
        self.assertEqual(code, 0)
        command = popen.call_args.args[0]
        self.assertEqual(command, [str(folder / v.APP_EXECUTABLE_NAME), "--post-update", "abc"])
        self.assertEqual(popen.call_args.kwargs["cwd"], str(self.root))

    def test_self_heals_to_newest_when_pointer_is_corrupt(self):
        self._install("2.8.0")
        folder = self._install("2.9.0")
        (self.root / "current.json").write_text("lixo")
        popen = mock.Mock()
        self.assertEqual(launcher.launch(self.root, [], popen=popen), 0)
        self.assertEqual(popen.call_args.args[0][0], str(folder / v.APP_EXECUTABLE_NAME))

    def test_reports_error_when_no_version_installed(self):
        popen = mock.Mock()
        with mock.patch.object(launcher, "_show_error") as show:
            self.assertEqual(launcher.launch(self.root, [], popen=popen), 1)
        show.assert_called_once()
        popen.assert_not_called()

    def test_reports_error_when_spawn_fails(self):
        self._install("2.8.0")
        popen = mock.Mock(side_effect=OSError("boom"))
        with mock.patch.object(launcher, "_show_error") as show:
            self.assertEqual(launcher.launch(self.root, [], popen=popen), 1)
        self.assertIn("boom", show.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
