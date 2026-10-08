from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLabel


class ToastNotification(QLabel):
    def __init__(self, parent, message: str, kind: str = "success"):
        super().__init__(message, parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.ToolTip)
        # Cor e canto vem de QLabel#ToastNotification[kind] na folha de estilo.
        self.setObjectName("ToastNotification")
        self.setProperty("kind", "success" if kind == "success" else "error")
        self.adjustSize()
        parent_rect = parent.geometry()
        self.move(parent_rect.right() - self.width() - 34, parent_rect.top() + 34)
        self.show()
        QTimer.singleShot(2600, self.close)
