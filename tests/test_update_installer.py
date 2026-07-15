from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import update_installer


class UpdateInstallerTests(unittest.TestCase):
    def test_hidden_subprocess_options_use_no_window_on_windows(self):
        with patch.object(update_installer.sys, "platform", "win32"):
            self.assertEqual(
                update_installer._hidden_subprocess_options(),
                {"creationflags": subprocess.CREATE_NO_WINDOW},
            )

    def test_silent_installer_starts_installer_and_restart_script_without_console_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            installer = Path(tmp) / "ControleProducaoSetup.exe"
            installer.write_bytes(b"setup")
            restart_script = Path(tmp) / "restart_after_update.bat"
            restart_script.write_text("@echo off\n", encoding="utf-8")

            with patch.object(update_installer.sys, "platform", "win32"), patch.object(
                update_installer, "_create_restart_script", return_value=restart_script
            ), patch.object(update_installer.subprocess, "Popen") as popen, patch.object(update_installer.sys, "exit"):
                update_installer.run_silent_installer(installer)

            self.assertEqual(popen.call_count, 2)
            for call in popen.call_args_list:
                self.assertEqual(call.kwargs.get("creationflags"), subprocess.CREATE_NO_WINDOW)


if __name__ == "__main__":
    unittest.main()
