from __future__ import annotations

from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QTreeWidget, QTreeWidgetItem

from app.ui.components.detail_widgets import make_panel, stat_block
from app.ui.numeric_utils import format_decimal
from app.ui.remanagement_wizard.base import WizardPage


class DonePage(WizardPage):
    """Ultimo passo: o resultado, na propria janela (sem aviso por cima)."""

    step_name = "Concluído"
    instruction = "Retirada registrada com sucesso."
    next_label = "Fechar"
    next_icon = "status"

    def __init__(self, service, state, parent=None):
        super().__init__(service, state, parent)
        self.panel, layout = make_panel("Retirada registrada")
        row = QHBoxLayout()
        row.setSpacing(28)
        self.proposals_stat = stat_block("0", "propostas processadas")
        self.items_stat = stat_block("0", "itens retirados")
        self.weight_stat = stat_block("0", "kg retirados")
        for block in (self.proposals_stat, self.items_stat, self.weight_stat):
            row.addLayout(block)
        row.addStretch(1)
        layout.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Proposta", "Itens", "Situação", "Peso"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setColumnWidth(0, 420)
        layout.addWidget(self.tree, 1)
        self.root.addWidget(self.panel, 1)

    def enter(self) -> None:
        result = self.state.result or {"proposals": [], "weight": 0}
        proposals = result["proposals"]
        self.tree.clear()
        for entry in proposals:
            QTreeWidgetItem(self.tree, [
                f"{entry['proposal']} — {entry['client']}".strip(" —"),
                f"{entry['items']} de {entry['pending']}" if entry["pending"] else "—",
                "Entregue" if entry["status"] == "ENTREGUE" else "Entrega parcial",
                f"{format_decimal(entry['weight'])} kg" if entry["items"] else "—",
            ])
        self.proposals_stat.itemAt(0).widget().setText(str(len(proposals)))
        self.items_stat.itemAt(0).widget().setText(str(sum(entry["items"] for entry in proposals)))
        self.weight_stat.itemAt(0).widget().setText(format_decimal(result["weight"]))

    def is_valid(self) -> bool:
        return True

    def summary(self) -> str:
        return "A retirada já foi gravada."
