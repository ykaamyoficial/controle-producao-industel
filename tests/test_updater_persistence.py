from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.updater.persistence import copy_protected_files, is_protected


class IsProtectedTests(unittest.TestCase):
    def test_top_level_config_folder_is_protected(self):
        self.assertTrue(is_protected("config/controle_producao_config.json"))

    def test_dotenv_is_protected(self):
        self.assertTrue(is_protected(".env"))
        self.assertTrue(is_protected(".env.production"))

    def test_sqlite_file_is_protected(self):
        self.assertTrue(is_protected("legacy.sqlite3"))

    def test_application_binary_is_not_protected(self):
        self.assertFalse(is_protected("ControleProducao.exe"))
        self.assertFalse(is_protected("app/lib/helper.dll"))

    def test_unknown_top_level_file_is_not_protected(self):
        self.assertFalse(is_protected("randomfile.dat"))

    def test_inno_uninstaller_is_protected(self):
        # Criado pelo Inno Setup na primeira instalacao, nunca vem no pacote
        # de atualizacao -- o swap de diretorio nao pode apaga-lo.
        self.assertTrue(is_protected("unins000.exe"))
        self.assertTrue(is_protected("unins000.dat"))
        self.assertTrue(is_protected("unins001.exe"))


class CopyProtectedFilesTests(unittest.TestCase):
    def test_config_and_logs_are_copied_into_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source = tmp / "old_install"
            (source / "config").mkdir(parents=True)
            (source / "config" / "controle_producao_config.json").write_text('{"real": true}')
            (source / "logs").mkdir()
            (source / "logs" / "app.log").write_text("log line")
            (source / "ControleProducao.exe").write_text("old binary")

            target = tmp / "staging"
            (target / "ControleProducao.exe").parent.mkdir(parents=True, exist_ok=True)
            (target / "ControleProducao.exe").write_text("new binary")

            preserved = copy_protected_files(source_install_dir=source, target_install_dir=target)

            self.assertIn("config/controle_producao_config.json", preserved)
            self.assertIn("logs/app.log", preserved)
            self.assertEqual((target / "config" / "controle_producao_config.json").read_text(), '{"real": true}')
            # o binario novo do staging nao deve ser sobrescrito pelo antigo.
            self.assertEqual((target / "ControleProducao.exe").read_text(), "new binary")

    def test_missing_source_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            preserved = copy_protected_files(source_install_dir=tmp / "does-not-exist", target_install_dir=tmp / "target")
            self.assertEqual(preserved, [])

    def test_no_protected_files_present_preserves_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            source = tmp / "old_install"
            source.mkdir()
            (source / "ControleProducao.exe").write_text("old binary")
            target = tmp / "staging"
            target.mkdir()
            preserved = copy_protected_files(source_install_dir=source, target_install_dir=target)
            self.assertEqual(preserved, [])


if __name__ == "__main__":
    unittest.main()
