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
            runner_script = Path(tmp) / "run_update_hidden.ps1"
            runner_script.write_text("Start-Sleep -Seconds 1\n", encoding="utf-8")

            with patch.object(update_installer.sys, "platform", "win32"), patch.object(
                update_installer, "_create_update_runner", return_value=runner_script
            ), patch.object(
                update_installer, "write_pending_update"
            ), patch.object(update_installer.subprocess, "Popen") as popen, patch.object(update_installer.sys, "exit"):
                update_installer.run_silent_installer(installer, target_version="2.5.2")

            self.assertEqual(popen.call_count, 1)
            for call in popen.call_args_list:
                self.assertEqual(call.kwargs.get("creationflags"), subprocess.CREATE_NO_WINDOW)
            args = popen.call_args.args[0]
            self.assertIn("powershell.exe", args[0])
            self.assertIn("-WindowStyle", args)
            self.assertIn("Hidden", args)

    def test_update_runner_waits_for_current_process_and_runs_installer(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            installer = Path(tmp) / "ControleProducaoSetup.exe"
            installer.write_bytes(b"setup")
            with patch.object(update_installer, "get_app_data_dir", return_value=data_dir), patch.object(
                update_installer, "get_logs_dir", return_value=Path(tmp) / "logs"
            ):
                runner = update_installer._create_update_runner(installer, wait_pid=123)
            content = runner.read_text(encoding="utf-8")
            self.assertIn("Wait-Process -Id $pidToWait", content)
            self.assertIn("/VERYSILENT", content)
            self.assertIn("/CLOSEAPPLICATIONS", content)
            self.assertIn("Start-Process -FilePath $appExe", content)

    def test_pre_update_backup_is_disabled_for_postgresql_only_runtime(self):
        backup = update_installer.create_pre_update_backup("2.6.0")

        self.assertIsNone(backup)


if __name__ == "__main__":
    unittest.main()
