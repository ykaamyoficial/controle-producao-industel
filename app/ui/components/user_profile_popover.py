from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from app.ui.components.modern_button import ModernButton
from app.ui.components.avatar import make_avatar_label


def _initials(name: str | None) -> str:
    parts = (name or "").split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


class UserProfilePopover(QFrame):
    logout_requested = Signal()
    profile_requested = Signal()
    password_requested = Signal()

    def __init__(self, service, parent=None):
        super().__init__(parent, Qt.Popup)
        self.service = service
        self.setObjectName("Panel")
        self.setFixedWidth(240)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        user = self.service.user or {}
        name = user.get("nome") or user.get("login") or "-"
        role = "Administrador" if user.get("perfil") == "admin" else "Usuario"

        header = QHBoxLayout()
        header.setSpacing(10)
        avatar = make_avatar_label(name, self.service, 36, user.get("id"))
        header.addWidget(avatar)

        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        name_label = QLabel(name)
        name_label.setStyleSheet("font-weight: 700;")
        text_col.addWidget(name_label)
        role_label = QLabel(role)
        role_label.setObjectName("Caption")
        text_col.addWidget(role_label)
        header.addLayout(text_col, 1)
        layout.addLayout(header)

        profile_btn = ModernButton("Meu perfil", "users")
        profile_btn.clicked.connect(lambda: (self.close(), self.profile_requested.emit()))
        layout.addWidget(profile_btn)
        password_btn = ModernButton("Alterar senha", "status")
        password_btn.clicked.connect(lambda: (self.close(), self.password_requested.emit()))
        layout.addWidget(password_btn)

        logout_btn = ModernButton("Sair")
        logout_btn.clicked.connect(self._on_logout)
        layout.addWidget(logout_btn)

    def _on_logout(self):
        self.close()
        self.logout_requested.emit()
