from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.components import path_field as module
from app.ui.components.path_field import PathField, open_path


class PathFieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_open_button_follows_the_text(self):
        field = PathField()
        self.assertFalse(field.open_button.isEnabled())
        field.setText(r"\\servidor\bim\PD1180.pdf")
        self.assertTrue(field.open_button.isEnabled())
        self.assertEqual(field.text(), r"\\servidor\bim\PD1180.pdf")

    def test_choose_file_saves_the_normalized_path(self):
        field = PathField()
        with patch.object(module.QFileDialog, "getOpenFileName", return_value=("C:/Docs/PIT/pit.pdf", "")):
            field.choose_file()
        self.assertEqual(field.text(), os.path.normpath("C:/Docs/PIT/pit.pdf"))

    def test_choose_folder_saves_the_path_and_cancel_keeps_it(self):
        field = PathField()
        field.setText(r"C:\antes")
        with patch.object(module.QFileDialog, "getExistingDirectory", return_value=""):
            field.choose_folder()
        self.assertEqual(field.text(), r"C:\antes")
        with patch.object(module.QFileDialog, "getExistingDirectory", return_value="C:/Docs/Pasta"):
            field.choose_folder()
        self.assertEqual(field.text(), os.path.normpath("C:/Docs/Pasta"))

    def test_open_existing_path_and_web_link_use_the_desktop(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(module.QDesktopServices, "openUrl", return_value=True) as opened:
            self.assertTrue(open_path(folder))
            self.assertTrue(open_path("https://portal.exemplo.com/doc"))
        self.assertEqual(opened.call_count, 2)

    def test_open_missing_path_warns_instead_of_failing_silently(self):
        with patch.object(module.QMessageBox, "warning") as warning, patch.object(module.QDesktopServices, "openUrl") as opened:
            self.assertFalse(open_path(r"Z:\nao\existe\arquivo.pdf"))
        warning.assert_called_once()
        opened.assert_not_called()

    def test_open_empty_path_does_nothing(self):
        with patch.object(module.QMessageBox, "warning") as warning:
            self.assertFalse(open_path("  "))
        warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
