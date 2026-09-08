from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.components.operational_header import configure_operational_header
from app.ui.styles import app_stylesheet


class OperationalHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_header_uses_flat_semantic_object_name(self):
        frame = QFrame()
        layout = QVBoxLayout(frame)

        configure_operational_header(frame, layout)

        self.assertEqual(frame.objectName(), "OperationalHeader")
        self.assertNotEqual(frame.objectName(), "FilterBar")
        self.assertNotEqual(frame.objectName(), "Panel")
        self.assertEqual(layout.contentsMargins().left(), 16)
        self.assertEqual(layout.spacing(), 8)

    def test_stylesheet_keeps_operational_header_out_of_card_selector(self):
        stylesheet = app_stylesheet(OFFICIAL_COLOR_PALETTES["claro"])

        self.assertIn("QFrame#OperationalHeader", stylesheet)
        self.assertIn("border-radius: 0", stylesheet)
        card_selector = "QFrame#TopBar, QFrame#FilterBar, QFrame#Card, QFrame#KpiCard, QFrame#Panel"
        self.assertIn(card_selector, stylesheet)
        self.assertNotIn("QFrame#OperationalHeader, QFrame#Card", stylesheet)


if __name__ == "__main__":
    unittest.main()
