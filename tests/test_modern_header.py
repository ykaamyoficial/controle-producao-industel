from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QStandardItem, QStandardItemModel  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QTableView  # noqa: E402

from app.ui.components.batch_selection import BatchSelectionHeader  # noqa: E402
from app.ui.components.modern_header import HEADER_HEIGHT, ModernHeaderView  # noqa: E402
from app.ui.components.modern_table import TABLE_HEADER_HEIGHT  # noqa: E402


class _Model(QStandardItemModel):
    columns = [("batch_select", ""), ("status_icon", ""), ("chat_icon", ""), ("proposta", "Proposta"), ("cliente", "Cliente")]

    def __init__(self):
        super().__init__(3, len(self.columns))
        for column, (_key, label) in enumerate(self.columns):
            self.setHorizontalHeaderItem(column, QStandardItem(label))
            for row in range(3):
                self.setItem(row, column, QStandardItem(f"{label}{row}"))


class ModernHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _table(self):
        table = QTableView()
        header = ModernHeaderView(Qt.Horizontal, table)
        table.setHorizontalHeader(header)
        table.setModel(_Model())
        table.setSortingEnabled(True)
        table.resize(700, 300)
        table.show()
        self.app.processEvents()
        return table, header

    def test_batch_selection_header_is_the_modern_header_and_height_matches(self):
        self.assertIs(BatchSelectionHeader, ModernHeaderView)
        self.assertEqual(HEADER_HEIGHT, TABLE_HEADER_HEIGHT)

    def test_only_titled_columns_sort_and_icon_columns_have_no_title(self):
        _table, header = self._table()
        self.assertEqual([header.is_sortable(i) for i in range(5)], [False, False, False, True, True])
        header.set_batch_state(True, Qt.Unchecked, has_visible_rows=True)
        self.assertFalse(header.is_sortable(0))

    def test_clicking_a_title_sorts_and_clicking_an_icon_column_does_not(self):
        table, header = self._table()
        icon_x = header.sectionViewportPosition(1) + header.sectionSize(1) // 2
        QTest.mouseClick(header.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(icon_x, HEADER_HEIGHT // 2))
        self.assertNotEqual(header.sortIndicatorSection(), 1)
        title_x = header.sectionViewportPosition(3) + header.sectionSize(3) // 2
        QTest.mouseClick(header.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(title_x, HEADER_HEIGHT // 2))
        self.assertEqual(header.sortIndicatorSection(), 3)
        self.assertEqual(table.model().headerData(3, Qt.Horizontal), "Proposta")

    def test_batch_checkbox_emits_toggle_and_keeps_tri_state(self):
        _table, header = self._table()
        seen = []
        header.toggle_visible_requested.connect(seen.append)
        header.set_batch_state(True, Qt.PartiallyChecked, has_visible_rows=True)
        x = header.sectionViewportPosition(0) + header.sectionSize(0) // 2
        QTest.mouseClick(header.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(x, HEADER_HEIGHT // 2))
        self.assertEqual(seen, [True])
        self.assertEqual(header.check_state, Qt.PartiallyChecked)
        header.set_batch_state(True, Qt.Checked, has_visible_rows=True)
        QTest.mouseClick(header.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(x, HEADER_HEIGHT // 2))
        self.assertEqual(seen, [True, False])

    def test_paints_in_both_states_without_error(self):
        table, header = self._table()
        header.set_batch_state(True, Qt.PartiallyChecked, has_visible_rows=True)
        table.sortByColumn(4, Qt.DescendingOrder)
        self.assertFalse(header.grab().isNull())


if __name__ == "__main__":
    unittest.main()
