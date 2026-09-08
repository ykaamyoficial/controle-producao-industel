from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QLineEdit, QVBoxLayout

from app.services.login_preferences import load_login_preferences, save_login_preferences
from app.ui.app_icon import app_icon
from app.ui.components.modern_button import ModernButton


class LoginDialog(QDialog):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Login")
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(420)
        self.preferences = load_login_preferences()
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
        remembered_login = str(self.preferences.get("last_user") or "")
        self.login.setText(remembered_login)
        self.password = QLineEdit()
        self.password.setPlaceholderText("Senha")
        self.password.setEchoMode(QLineEdit.Password)
        self.remember_user = QCheckBox("Lembrar meu usuário")
        self.remember_user.setChecked(bool(self.preferences.get("remember_user")) and bool(remembered_login))
        enter = ModernButton("Entrar", "status", accent=True)
        enter.clicked.connect(self.try_login)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addWidget(self.login)
        layout.addWidget(self.password)
        layout.addWidget(self.remember_user)
        layout.addWidget(self.error)
        layout.addWidget(enter, alignment=Qt.AlignRight)
        if remembered_login:
            self.password.setFocus()
        else:
            self.login.setFocus()

    def try_login(self):
        login = self.login.text().strip()
        if self.service.authenticate(login, self.password.text()):
            save_login_preferences(login, self.remember_user.isChecked())
            self.accept()
        else:
            self.error.setText("Usuario ou senha invalidos.")
