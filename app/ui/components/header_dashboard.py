from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel

from app.ui.components.modern_button import ModernButton
from app.ui.components.page_header import setup_page_header
from app.ui.theme_tokens import dashboard_tokens


class HeaderDashboard(QFrame):
    """Faixa de topo do Painel geral: titulo, foco operacional, hora da ultima
    atualizacao e o botao Atualizar."""

    def __init__(self, palette: dict, parent=None):
        super().__init__(parent)
        self.tokens = dashboard_tokens(palette)
        self.updated = QLabel("")
        self.updated.setObjectName("TopInfoChip")
        self.refresh_button = ModernButton("Atualizar", "refresh", accent=True)
        self.refresh_button.setAccessibleName("Atualizar painel")
        setup_page_header(
            self,
            "Dashboard Operacional",
            "",
            side=[self.updated],
            actions=[self.refresh_button],
        )
        self.subtitle = self.subtitle_label

    def set_palette(self, palette: dict) -> None:
        # As cores vem da folha de estilo; so os tokens guardados mudam.
        self.tokens = dashboard_tokens(palette)

    def update_content(self, subtitle: str, updated_text: str) -> None:
        self.subtitle.setText(subtitle)
        self.updated.setText(updated_text)
        self.updated.setVisible(bool(updated_text))
