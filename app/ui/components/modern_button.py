from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QPushButton

from app.ui.icons import make_icon


class ModernButton(QPushButton):
    def __init__(self, text: str = "", icon_name: str | None = None, accent: bool = False, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(34)
        self.setObjectName("AccentButton" if accent else "GhostButton")
        if icon_name:
            self.setIcon(make_icon(icon_name, "#ffffff" if accent else "#2563eb"))
            self.setIconSize(QSize(18, 18))
