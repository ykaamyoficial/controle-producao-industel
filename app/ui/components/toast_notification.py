from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLabel


class ToastNotification(QLabel):
    def __init__(self, parent, message: str, kind: str = "success"):
        super().__init__(message, parent)
        bg = "#047857" if kind == "success" else "#b91c1c"
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.ToolTip)
        self.setStyleSheet(
            f"background: {bg}; color: white; border-radius: 12px; padding: 12px 18px; font-weight: 700;"
        )
        self.adjustSize()
        parent_rect = parent.geometry()
        self.move(parent_rect.right() - self.width() - 34, parent_rect.top() + 34)
        self.show()
        QTimer.singleShot(2600, self.close)
