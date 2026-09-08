from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QDialog, QVBoxLayout

from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent


class UserProfileDialog(QDialog):
    def __init__(self, service, *, focus_password: bool = False, parent=None):
        super().__init__(parent)
        self.service = service
        self.focus_password = focus_password
        self.setWindowTitle("Meu perfil")
        self.setMinimumWidth(560)
        style_dialog_from_parent(self, parent)
        self._build()
        if focus_password:
            self.current_password.setFocus()

    def _build(self):
        user = self.service.user or {}
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)
        title = QLabel("Meu perfil")
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        root.addWidget(title)
        root.addWidget(QLabel("Gerencie suas informacoes pessoais e sua seguranca."))

        personal = QGroupBox("Informacoes pessoais")
        form = QFormLayout(personal)
        self.display_name = QLineEdit(str(user.get("nome") or ""))
        self.username = QLineEdit(str(user.get("login") or ""))
        self.profile = QLineEdit(self.service.user_profile())
        self.profile.setReadOnly(True)
        self.status = QLineEdit("Ativo" if user.get("ativo") else "Inativo")
        self.status.setReadOnly(True)
        form.addRow("Nome completo", self.display_name)
        form.addRow("Nome de usuario", self.username)
        form.addRow("Perfil de acesso", self.profile)
        form.addRow("Status", self.status)
        root.addWidget(personal)

        avatar_group = QGroupBox("Foto de perfil")
        avatar_layout = QHBoxLayout(avatar_group)
        self.avatar_preview = QLabel(self._initials(str(user.get("nome") or user.get("login") or "?")))
        self.avatar_preview.setFixedSize(82, 82)
        self.avatar_preview.setAlignment(Qt.AlignCenter)
        self.avatar_preview.setStyleSheet(f"background: {self.service.palette['accent']}; color: {self.service.palette['accent_text']}; border-radius: 41px; font-size: 22px; font-weight: 800;")
        avatar_layout.addWidget(self.avatar_preview)
        avatar_buttons = QVBoxLayout()
        choose = ModernButton("Alterar foto", "edit")
        remove = ModernButton("Remover foto", "remove")
        choose.clicked.connect(self._choose_avatar)
        remove.clicked.connect(self._remove_avatar)
        avatar_buttons.addWidget(choose)
        avatar_buttons.addWidget(remove)
        avatar_buttons.addStretch()
        avatar_layout.addLayout(avatar_buttons)
        root.addWidget(avatar_group)

        security = QGroupBox("Seguranca")
        security_form = QFormLayout(security)
        self.current_password = QLineEdit()
        self.current_password.setEchoMode(QLineEdit.Password)
        self.new_password = QLineEdit()
        self.new_password.setEchoMode(QLineEdit.Password)
        self.confirm_password = QLineEdit()
        self.confirm_password.setEchoMode(QLineEdit.Password)
        security_form.addRow("Senha atual", self.current_password)
        security_form.addRow("Nova senha", self.new_password)
        security_form.addRow("Confirmar nova senha", self.confirm_password)
        root.addWidget(security)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = ModernButton("Cancelar", "close")
        save = ModernButton("Salvar alteracoes", "save", accent=True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    @staticmethod
    def _initials(name: str) -> str:
        parts = name.split()
        return (parts[0][:1] + (parts[-1][:1] if len(parts) > 1 else parts[0][1:2])).upper() or "?"

    def _choose_avatar(self):
        path, _ = QFileDialog.getOpenFileName(self, "Selecionar foto", "", "Imagens (*.jpg *.jpeg *.png *.webp)")
        if not path:
            return
        content = Path(path).read_bytes()
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(Path(path).suffix.lower(), "")
        if len(content) > 5 * 1024 * 1024:
            QMessageBox.warning(self, "Foto de perfil", "A foto deve ter no maximo 5 MB.")
            return
        try:
            self.service.upload_current_avatar(Path(path).name, content, mime)
            pixmap = QPixmap(path)
            self.avatar_preview.setPixmap(pixmap.scaled(82, 82, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
            self.avatar_preview.setText("")
        except Exception as exc:
            QMessageBox.warning(self, "Foto de perfil", str(exc))

    def _remove_avatar(self):
        try:
            self.service.remove_current_avatar()
            self.avatar_preview.clear()
            self.avatar_preview.setText(self._initials(self.display_name.text() or self.username.text()))
        except Exception as exc:
            QMessageBox.warning(self, "Foto de perfil", str(exc))

    def _save(self):
        try:
            self.service.update_current_user(username=self.username.text().strip(), display_name=self.display_name.text().strip())
            if any((self.current_password.text(), self.new_password.text(), self.confirm_password.text())):
                self.service.change_current_password(self.current_password.text(), self.new_password.text(), self.confirm_password.text())
        except Exception as exc:
            QMessageBox.warning(self, "Meu perfil", str(exc))
            return
        QMessageBox.information(self, "Meu perfil", "Dados do perfil atualizados com sucesso.")
        self.accept()
