from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QPushButton

from app.ui.icons import make_icon


class FloatingChatButton(QPushButton):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setObjectName("AccentButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(56, 56)
        self.setIconSize(QSize(26, 26))
        self.setStyleSheet("border-radius: 28px; font-weight: 800;")
        self.set_unread_count(0)

    def set_unread_count(self, count: int):
        self.setIcon(make_icon("chat", "#ffffff"))
        self.setText(("99+" if count >= 100 else str(count)) if count else "")
        self.setToolTip(f"{count} mensagem(ns) nao lida(s)" if count else "Abrir chats")
