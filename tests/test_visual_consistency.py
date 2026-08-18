from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout

from app.ui.components.operational_header import configure_operational_header
from app.ui.components.operational_layout import (
    OPERATIONAL_ACTION_SPACING,
    OPERATIONAL_HEADER_MARGINS,
    OPERATIONAL_HEADER_SPACING,
    OPERATIONAL_PAGE_MARGINS,
    OPERATIONAL_PAGE_SPACING,
    configure_operational_page_layout,
)
from app.ui.data_page import DataPage


class VisualConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_operational_layout_tokens_drive_shared_defaults(self):
        root = QVBoxLayout()
        configure_operational_page_layout(root)

        self.assertEqual(
            (
                root.contentsMargins().left(),
                root.contentsMargins().top(),
                root.contentsMargins().right(),
                root.contentsMargins().bottom(),
            ),
            OPERATIONAL_PAGE_MARGINS,
        )
        self.assertEqual(root.spacing(), OPERATIONAL_PAGE_SPACING)

        header = QFrame()
        header_layout = QVBoxLayout(header)
        configure_operational_header(header, header_layout)

        self.assertEqual(
            (
                header_layout.contentsMargins().left(),
                header_layout.contentsMargins().top(),
                header_layout.contentsMargins().right(),
                header_layout.contentsMargins().bottom(),
            ),
            OPERATIONAL_HEADER_MARGINS,
        )
        self.assertEqual(header_layout.spacing(), OPERATIONAL_HEADER_SPACING)

    def test_data_page_uses_full_area_header_and_table_stack(self):
        page = DataPage("Historico", [("proposta", "Proposta")], lambda: [])
        root = page.layout()
        header = page.findChild(QFrame, "OperationalHeader")
        table_stack = page.findChild(QFrame, "TableStack")

        self.assertIsNotNone(header)
        self.assertIsNotNone(table_stack)
        self.assertIsNone(page.findChild(QFrame, "FilterBar"))
        self.assertEqual(root.spacing(), 12)
        self.assertEqual(header.layout().spacing(), OPERATIONAL_ACTION_SPACING)

    def test_data_page_empty_and_error_states_use_operational_stack(self):
        page = DataPage("Historico", [("proposta", "Proposta")], lambda: [])

        page._refresh_success([])
        self.assertIs(page.table_stack.currentWidget(), page.empty_state)

        page._refresh_success([{"proposta": "1001"}])
        self.assertIs(page.table_stack.currentWidget(), page.table)

        page._refresh_error(RuntimeError("falha de teste"))
        self.assertIs(page.table_stack.currentWidget(), page.empty_state)


if __name__ == "__main__":
    unittest.main()
