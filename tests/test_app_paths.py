import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import backend_adapter
from app.services import app_paths


class AppPathsTest(unittest.TestCase):
    def test_development_paths_stay_inside_project(self):
        self.assertFalse(app_paths.is_packaged())
        self.assertEqual(app_paths.get_database_path(), app_paths.APP_DIR / "data" / "controle_producao.db")
        self.assertEqual(app_paths.get_config_path(), app_paths.APP_DIR / "config" / "controle_producao_config.json")
        self.assertEqual(app_paths.get_backup_dir(), app_paths.APP_DIR / "data" / "backups")

    def test_packaged_paths_use_program_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(app_paths.sys, "frozen", True, create=True), patch.dict(
                os.environ,
                {"ProgramData": temp_dir},
                clear=False,
            ):
                expected_root = Path(temp_dir) / "Industel" / "ControleProducao"
                self.assertEqual(app_paths.get_app_data_dir(), expected_root)
                self.assertEqual(app_paths.get_database_path(), expected_root / "controle_producao.db")
                self.assertEqual(app_paths.get_config_path(), expected_root / "controle_producao_config.json")
                self.assertEqual(app_paths.get_backup_dir(), expected_root / "backups")

    def test_environment_override_wins_for_packaged_data_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(app_paths.sys, "frozen", True, create=True), patch.dict(
                os.environ,
                {"CONTROLE_PRODUCAO_DATA_DIR": temp_dir},
                clear=False,
            ):
                self.assertEqual(app_paths.get_app_data_dir(), Path(temp_dir))

    def test_new_packaged_config_points_to_program_data_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(app_paths.sys, "frozen", True, create=True), patch.dict(
                os.environ,
                {"CONTROLE_PRODUCAO_DATA_DIR": temp_dir},
                clear=False,
            ):
                config = backend_adapter.load_app_config()

        self.assertEqual(config["db_path"], str(Path(temp_dir) / "controle_producao.db"))
        self.assertEqual(config["backup_dir"], str(Path(temp_dir) / "backups"))


if __name__ == "__main__":
    unittest.main()
