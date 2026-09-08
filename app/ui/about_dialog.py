from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from app.ui.app_icon import app_icon
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent
from app.version import APP_BUILD, APP_NAME, APP_PUBLISHER, APP_VERSION


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sobre")
        self.setWindowIcon(app_icon())
        self.setFixedWidth(360)
        style_dialog_from_parent(self, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(6)

        name = QLabel(APP_NAME)
        name.setStyleSheet("font-size: 16px; font-weight: 800;")
        layout.addWidget(name)

        version = QLabel(f"Versao {APP_VERSION} - build {APP_BUILD}")
        version.setObjectName("Caption")
        layout.addWidget(version)

        publisher = QLabel(APP_PUBLISHER)
        publisher.setObjectName("Caption")
        layout.addWidget(publisher)

        layout.addSpacing(10)
        support = QLabel("Duvidas ou problemas? Fale com o time de TI da Industel.")
        support.setWordWrap(True)
        support.setObjectName("Caption")
        layout.addWidget(support)

        layout.addSpacing(14)
        close_btn = ModernButton("Fechar", "clear", accent=True)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)
