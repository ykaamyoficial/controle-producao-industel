from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication, QDialog, QWidget

from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent


class LargeDialogGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_large_dialog_standard_sets_minimum_size_and_centers_from_parent(self):
        parent = QWidget()
        parent.resize(1400, 900)
        parent.move(80, 60)
        parent.setStyleSheet("QDialog { color: rgb(1, 2, 3); }")

        dialog = QDialog(parent)
        apply_large_dialog_geometry(dialog, parent)
        style_dialog_from_parent(dialog, parent)

        self.assertGreaterEqual(dialog.minimumWidth(), 1100)
        self.assertGreaterEqual(dialog.minimumHeight(), 650)
        self.assertGreaterEqual(dialog.width(), 1100)
        self.assertGreaterEqual(dialog.height(), 650)
        self.assertIn("rgb(1, 2, 3)", dialog.styleSheet())


if __name__ == "__main__":
    unittest.main()
