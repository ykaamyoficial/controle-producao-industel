from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from app.ui.app_icon import app_icon
from app.ui.components.dialog_shell import dialog_header
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.settings_page import SettingsPage


class SettingsDialog(QDialog):
    """Janela visual de Configuracoes que reutiliza o servico e as acoes existentes."""

    def __init__(self, service, theme_changed=None, parent=None):
        super().__init__(parent)
        self.service = service
        self._theme_changed = theme_changed
        self.setWindowTitle("Configurações")
        self.setWindowIcon(app_icon())
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title = QLabel("Configurações")
        subtitle = QLabel("Ajustes do sistema, aparência, usuários, API e PostgreSQL.")
        close_button = ModernButton("Fechar", "clear", variant="ghost")
        close_button.clicked.connect(self.accept)
        root.addWidget(dialog_header(title, subtitle, actions=[close_button]))

        self.settings_page = SettingsPage(service, self._apply_theme, self)
        root.addWidget(self.settings_page, 1)

        style_dialog_from_parent(self, parent)
        apply_large_dialog_geometry(
            self,
            parent,
            width_ratio=0.84,
            height_ratio=0.86,
            minimum_width=920,
            minimum_height=600,
        )

    def _apply_theme(self) -> None:
        if self._theme_changed:
            self._theme_changed()
        style_dialog_from_parent(self, self.parentWidget())
        self.settings_page.refresh()

