from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QSizePolicy, QTableView

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.components.operational_table import configure_operational_table
from app.ui.styles import app_stylesheet


class OperationalTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_table_uses_full_width_semantic_object_name(self):
        table = QTableView()

        configure_operational_table(table)

        self.assertEqual(table.objectName(), "OperationalTable")
        self.assertEqual(table.sizePolicy().horizontalPolicy(), QSizePolicy.Expanding)
        self.assertEqual(table.sizePolicy().verticalPolicy(), QSizePolicy.Expanding)
        self.assertEqual(table.frameShape(), QFrame.NoFrame)

    def test_stylesheet_removes_operational_table_radius(self):
        stylesheet = app_stylesheet(OFFICIAL_COLOR_PALETTES["claro"])

        self.assertIn("QTableView#OperationalTable", stylesheet)
        self.assertIn("QTableView#OperationalTable::viewport", stylesheet)
        self.assertIn("border-radius: 0", stylesheet)
        self.assertIn("QWidget#OperationalEmptyState", stylesheet)


if __name__ == "__main__":
    unittest.main()
