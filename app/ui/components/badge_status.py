from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel

from app.ui.theme_tokens import with_alpha


class BadgeStatus(QLabel):
    clicked = Signal(str)

    def __init__(self, text: str, value: int, color: str, palette: dict, parent=None):
        super().__init__(f"{text}  {value}", parent)
        self.badge_key = text
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"Clique para visualizar: {text}")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(32)
        self.setStyleSheet(
            f"""
            background: {with_alpha(color, 34)};
            color: {color};
            border: 1px solid {with_alpha(color, 90)};
            border-radius: 10px;
            padding: 5px 10px;
            font-weight: 800;
            """
        )

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.badge_key)
        super().mouseReleaseEvent(event)
