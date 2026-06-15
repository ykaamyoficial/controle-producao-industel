from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QVBoxLayout

from app.ui.app_icon import app_icon
from app.ui.components.modern_button import ModernButton


class LoginDialog(QDialog):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Login")
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(420)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(12)
        title = QLabel("Controle de Producao Industel")
        title.setStyleSheet("font-size: 21px; font-weight: 800;")
        subtitle = QLabel("Acesse o painel operacional")
        subtitle.setObjectName("Caption")
        self.error = QLabel("")
        self.error.setObjectName("ErrorText")
        self.login = QLineEdit()
        self.login.setPlaceholderText("Usuario")
        self.login.setText("admin")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Senha")
        self.password.setEchoMode(QLineEdit.Password)
        enter = ModernButton("Entrar", "status", accent=True)
        enter.clicked.connect(self.try_login)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addWidget(self.login)
        layout.addWidget(self.password)
        layout.addWidget(self.error)
        layout.addWidget(enter, alignment=Qt.AlignRight)

    def try_login(self):
        if self.service.authenticate(self.login.text(), self.password.text()):
            self.accept()
        else:
            self.error.setText("Usuario ou senha invalidos.")
