from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout

from app.services.remanagement_badges import describe_link, situation_label
from app.ui.app_icon import app_icon
from app.ui.components.detail_widgets import make_panel
from app.ui.components.dialog_shell import dialog_footer, dialog_header, dialog_layout, info_notice
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent


class RemanagementInfoDialog(QDialog):
    """Para onde foram as pecas de uma proposta marcada por remanejamento.

    Abre pelo clique no icone ao lado do codigo da proposta nas listas de Producao, Galvanizacao e
    Expedicao. Os dados ja vem na linha da lista (situacao + vinculos), entao nao chama a API."""

    def __init__(self, proposal_label: str, situation: str, links: list[dict[str, Any]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Remanejamento da proposta")
        self.setWindowIcon(app_icon())
        self.setFixedWidth(500)
        style_dialog_from_parent(self, parent)

        layout = dialog_layout(self)
        self.header = dialog_header(QLabel(proposal_label), situation_label(situation) or "Remanejamento")
        layout.addWidget(self.header)

        panel, body = make_panel("Para onde foram as peças")
        self.link_labels: list[QLabel] = []
        for link in links:
            row = QVBoxLayout()
            row.setSpacing(1)
            sentence = QLabel(describe_link(link.get("direction"), link.get("counterpart")))
            sentence.setObjectName("ValueLabel")
            sentence.setWordWrap(True)
            row.addWidget(sentence)
            code = str(link.get("code") or "").strip()
            if code:
                code_label = QLabel(code)
                code_label.setObjectName("KeyLabel")
                row.addWidget(code_label)
            body.addLayout(row)
            self.link_labels.append(sentence)
        if not links:
            empty = QLabel("Não há detalhes deste remanejamento na lista. Abra Detalhes da proposta para ver o histórico.")
            empty.setObjectName("KeyLabel")
            empty.setWordWrap(True)
            body.addWidget(empty)
        layout.addWidget(panel)
        layout.addWidget(info_notice("A marca some sozinha quando as peças voltam e a proposta fica inteira."))

        self.close_button = ModernButton("Fechar", "clear", variant="ghost")
        self.close_button.clicked.connect(self.accept)
        layout.addWidget(dialog_footer(right=[self.close_button]))
