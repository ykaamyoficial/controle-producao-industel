from __future__ import annotations

from PySide6.QtWidgets import QLabel


class StatusBadge(QLabel):
    def __init__(self, text: str, bg: str, fg: str = "#ffffff", parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 9px; padding: 4px 9px; font-weight: 700;"
        )
