from __future__ import annotations

import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ISS = (_ROOT / "installer" / "ControleProducao.iss").read_text(encoding="utf-8")


class InstallerLayoutTests(unittest.TestCase):
    """O .iss e o spec precisam descrever o MESMO layout versionado que o
    Updater e o launcher esperam (app/updater/versions.py)."""

    def test_launcher_goes_to_root_and_app_goes_to_versions_folder(self):
        self.assertIn(r'Source: "..\dist\Launcher\*"; DestDir: "{app}"', _ISS)
        self.assertIn(r'Source: "..\dist\ControleProducao\*"; DestDir: "{app}\versions\{#MyAppVersion}"', _ISS)
        self.assertIn(r'Source: "..\dist\Updater\*"; DestDir: "{app}\versions\{#MyAppVersion}"', _ISS)

    def test_shortcuts_and_run_point_to_the_launcher(self):
        self.assertIn('#define MyAppExeName "ControleProducao.exe"', _ISS)
        self.assertEqual(len(re.findall(r'Filename: "\{app\}\\{#MyAppExeName\}"', _ISS)), 3)

    def test_installer_stops_every_product_process_including_the_tray_agent(self):
        for image in ("ControleProducao.exe", "ControleProducaoApp.exe", "Updater.exe"):
            self.assertIn(f"KillByImageName('{image}')", _ISS)
        self.assertIn("function PrepareToInstall", _ISS)
        self.assertIn("CloseApplications=force", _ISS)

    def test_legacy_flat_files_are_removed_on_upgrade(self):
        self.assertIn(r'Name: "{app}\_internal"', _ISS)
        self.assertIn(r'Name: "{app}\Updater.exe"', _ISS)

    def test_pointer_is_written_and_user_writable(self):
        self.assertIn("current.json", _ISS)
        self.assertIn("S-1-5-32-545", _ISS)

    def test_real_app_exe_name_matches_between_spec_and_versions_module(self):
        from app.updater.versions import APP_EXECUTABLE_NAME

        spec = (_ROOT / "ControleProducao.spec").read_text(encoding="utf-8")
        self.assertIn(f"name='{APP_EXECUTABLE_NAME[:-4]}'", spec)
        launcher_spec = (_ROOT / "Launcher.spec").read_text(encoding="utf-8")
        self.assertIn("name='ControleProducao'", launcher_spec)


if __name__ == "__main__":
    unittest.main()
