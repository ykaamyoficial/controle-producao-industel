from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from app.ui.icons import make_icon


class KpiCard(QFrame):
    def __init__(self, title: str, value: str | int, icon_name: str, accent: str, parent=None):
        super().__init__(parent)
        self.setObjectName("KpiCard")
        self.setMinimumHeight(96)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        icon = QLabel()
        icon.setPixmap(make_icon(icon_name, accent, 28).pixmap(28, 28))
        icon.setFixedSize(42, 42)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(f"background: {accent}22; border-radius: 12px;")
        layout.addWidget(icon)

        text_box = QVBoxLayout()
        label = QLabel(title)
        label.setObjectName("Caption")
        number = QLabel(str(value))
        number.setStyleSheet("font-size: 24px; font-weight: 800;")
        text_box.addWidget(label)
        text_box.addWidget(number)
        layout.addLayout(text_box)
