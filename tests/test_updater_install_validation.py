from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.updater.install_validation import validate_installation


class ValidateInstallationTests(unittest.TestCase):
    def test_missing_executable_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            install_dir = Path(tmp)
            result = validate_installation(install_dir=install_dir, executable_path=install_dir / "App.exe", target_version="1.1.0")
            self.assertFalse(result.ok)

    def test_leftover_part_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            install_dir = Path(tmp)
            exe = install_dir / "App.exe"
            exe.write_text("bin")
            (install_dir / "leftover.part").write_text("x")
            result = validate_installation(install_dir=install_dir, executable_path=exe, target_version="1.1.0")
            self.assertFalse(result.ok)

    def test_missing_protected_path_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            install_dir = Path(tmp)
            exe = install_dir / "App.exe"
            exe.write_text("bin")
            result = validate_installation(
                install_dir=install_dir, executable_path=exe, target_version="1.1.0",
                protected_relative_paths=["config/controle_producao_config.json"],
            )
            self.assertFalse(result.ok)

    def test_version_marker_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            install_dir = Path(tmp)
            exe = install_dir / "App.exe"
            exe.write_text("bin")
            (install_dir / "VERSION").write_text("9.9.9")
            result = validate_installation(install_dir=install_dir, executable_path=exe, target_version="1.1.0")
            self.assertFalse(result.ok)

    def test_valid_installation_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            install_dir = Path(tmp)
            exe = install_dir / "App.exe"
            exe.write_text("bin")
            (install_dir / "config").mkdir()
            (install_dir / "config" / "cfg.json").write_text("{}")
            (install_dir / "VERSION").write_text("1.1.0")
            result = validate_installation(
                install_dir=install_dir, executable_path=exe, target_version="1.1.0",
                protected_relative_paths=["config/cfg.json"],
            )
            self.assertTrue(result.ok)

    def test_missing_version_marker_is_not_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            install_dir = Path(tmp)
            exe = install_dir / "App.exe"
            exe.write_text("bin")
            result = validate_installation(install_dir=install_dir, executable_path=exe, target_version="1.1.0")
            self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
