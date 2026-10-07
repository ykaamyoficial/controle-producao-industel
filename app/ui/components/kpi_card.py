from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from app.ui.components.detail_widgets import IconChip


class KpiCard(QFrame):
    def __init__(self, title: str, value: str | int, icon_name: str, accent: str, parent=None):
        super().__init__(parent)
        self.setObjectName("KpiCard")
        self.setMinimumHeight(88)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)
        layout.addWidget(IconChip(icon_name, accent, size=40), 0, Qt.AlignVCenter)

        text_box = QVBoxLayout()
        text_box.setSpacing(0)
        label = QLabel(title)
        label.setObjectName("IndicatorLabel")
        self.number = QLabel(str(value))
        self.number.setObjectName("IndicatorValue")
        text_box.addWidget(label)
        text_box.addWidget(self.number)
        layout.addLayout(text_box, 1)

    def set_value(self, value: str | int):
        self.number.setText(str(value))
