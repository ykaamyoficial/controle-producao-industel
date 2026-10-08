from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QComboBox, QScrollArea, QTableWidget, QVBoxLayout, QWidget

from app.ui.wheel_guard import ComboWheelGuard, install_combo_wheel_guard


def _wheel(widget: QWidget, delta: int = -120) -> QWheelEvent:
    position = QPointF(widget.width() / 2, widget.height() / 2)
    return QWheelEvent(
        position,
        QPointF(widget.mapToGlobal(position.toPoint())),
        QPoint(0, 0),
        QPoint(0, delta),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.NoScrollPhase,
        False,
    )


class ComboWheelGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        install_combo_wheel_guard(cls.app)

    def _build(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(QWidget())
        combo = QComboBox()
        combo.addItems(["Produzir + galvanizar", "Produzir sem galvanizar", "Nao produzir"])
        layout.addWidget(combo)
        filler = QWidget()
        filler.setMinimumHeight(1500)
        layout.addWidget(filler)
        scroll.setWidget(content)
        scroll.resize(400, 300)
        scroll.show()
        self.app.processEvents()
        return scroll, combo

    def test_wheel_over_a_combo_never_changes_its_option_and_scrolls_the_area(self):
        scroll, combo = self._build()
        combo.setCurrentIndex(1)
        combo.setFocus()
        bar = scroll.verticalScrollBar()
        self.assertEqual(bar.value(), 0)
        for _ in range(3):
            self.app.sendEvent(combo, _wheel(combo, -120))
        self.assertEqual(combo.currentIndex(), 1)
        self.assertGreater(bar.value(), 0)
        scroll.close()

    def test_wheel_in_the_opposite_direction_also_keeps_the_option(self):
        scroll, combo = self._build()
        combo.setCurrentIndex(0)
        self.app.sendEvent(combo, _wheel(combo, 120))
        self.assertEqual(combo.currentIndex(), 0)
        scroll.close()

    def test_wheel_over_a_combo_inside_a_table_cell_scrolls_the_table(self):
        # Caso do fluxo (coluna "Nova rota"): combo como widget de celula.
        table = QTableWidget(40, 2)
        combos = []
        for row in range(40):
            combo = QComboBox()
            combo.addItems(["Produzir + galvanizar", "Nao produzir"])
            table.setCellWidget(row, 1, combo)
            combos.append(combo)
        table.resize(360, 240)
        table.show()
        self.app.processEvents()
        bar = table.verticalScrollBar()
        self.assertEqual(bar.value(), 0)
        target = combos[0]
        self.app.sendEvent(target, _wheel(target, -120))
        self.assertEqual(target.currentIndex(), 0)
        self.assertGreater(bar.value(), 0)
        table.close()

    def test_keyboard_and_code_still_change_the_option(self):
        scroll, combo = self._build()
        combo.setCurrentIndex(2)
        self.assertEqual(combo.currentIndex(), 2)
        scroll.close()

    def test_installing_twice_reuses_the_same_guard(self):
        first = install_combo_wheel_guard(self.app)
        self.assertIsInstance(first, ComboWheelGuard)
        self.assertIs(install_combo_wheel_guard(self.app), first)


if __name__ == "__main__":
    unittest.main()
