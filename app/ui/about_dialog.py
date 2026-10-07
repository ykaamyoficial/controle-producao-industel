from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from app.ui.app_icon import app_icon
from app.ui.components.dialog_shell import dialog_footer, dialog_header
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent
from app.version import APP_BUILD, APP_DISPLAY_NAME, APP_PUBLISHER, APP_VERSION


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sobre")
        self.setWindowIcon(app_icon())
        self.setFixedWidth(360)
        style_dialog_from_parent(self, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        name = QLabel(APP_DISPLAY_NAME)
        layout.addWidget(dialog_header(name, f"Versão {APP_VERSION} - build {APP_BUILD} · {APP_PUBLISHER}"))

        support = QLabel("Dúvidas ou problemas? Fale com o time de TI da Industel.")
        support.setWordWrap(True)
        support.setObjectName("KeyLabel")
        layout.addWidget(support)

        close_btn = ModernButton("Fechar", "clear", accent=True)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(dialog_footer(right=[close_btn]))
