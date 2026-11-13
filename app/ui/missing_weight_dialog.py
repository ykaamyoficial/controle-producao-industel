from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLabel, QDialog, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout

from app.services.log_weight import NOT_QUERIED, Weight, active_items, collect_weights
from app.ui.components.dialog_shell import dialog_footer, dialog_header
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.item_weight_dialog import ItemWeightDialog


def incomplete_proposals(logs: list[dict[str, Any]], weights: dict[int, Weight]) -> list[dict[str, Any]]:
    """Propostas ativas (uma vez cada) sem nenhum peso ou com item sem peso."""
    found: dict[int, dict[str, Any]] = {}
    for log_ in logs:
        for item in active_items(log_):
            pid = item.get("proposal_id")
            total, missing = weights.get(pid, (None, 0))
            if pid is not None and pid not in found and (total is None or missing > 0):
                found[pid] = {"id": pid, "number": item.get("proposal_number") or "-", "customer": item.get("customer_name") or "-", "total": total, "missing": missing}
    return list(found.values())


class MissingWeightDialog(QDialog):
    """Aviso antes do relatório: propostas com peso pendente. Aceitar = gerar assim mesmo; fechar = cancelar."""

    def __init__(self, service, logs: list[dict[str, Any]], weights: dict[int, Weight], can_edit: bool, parent=None):
        super().__init__(parent)
        self.service = service
        self.logs = logs
        self.weights = dict(weights)  # resultado: já recalculado após "Informar peso"
        self.can_edit = can_edit
        self.setWindowTitle("Propostas com peso pendente")
        self.setMinimumSize(720, 420)
        style_dialog_from_parent(self, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        self.summary = QLabel()
        root.addWidget(dialog_header(QLabel("Propostas com peso pendente"), self.summary))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Proposta", "Cliente", "Situação"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for column in (0, 2):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        root.addWidget(self.table, 1)
        cancel = ModernButton("Cancelar", "clear", variant="ghost")
        self.inform_button = ModernButton("Informar peso", "edit", variant="secondary")
        self.generate_button = ModernButton("Gerar assim mesmo", "reports", accent=True)
        cancel.clicked.connect(self.reject)
        self.inform_button.clicked.connect(self.inform_weight)
        self.generate_button.clicked.connect(self.accept)
        self.inform_button.setVisible(can_edit)
        # A lista do LOG não traz a área da proposta e a API (409) só aceita peso em PRODUCAO;
        # não dá para desabilitar por proposta sem inventar regra, então o motivo fica no tooltip.
        self.inform_button.setToolTip("O peso só pode ser informado em propostas que estão na Produção; nas demais o sistema recusa o salvamento.")
        self.table.itemSelectionChanged.connect(lambda: self.inform_button.setEnabled(bool(self.table.selectedItems())))
        root.addWidget(dialog_footer(right=[cancel, self.inform_button, self.generate_button]))
        self._fill()

    def _fill(self) -> None:
        rows = incomplete_proposals(self.logs, self.weights)
        self.summary.setText(
            f"{len(rows)} proposta(s) com peso ausente ou incompleto. O total do relatório considera só o peso informado."
            if rows else "Todos os pesos informados."
        )
        self.table.setRowCount(len(rows))
        for row, p in enumerate(rows):
            if p["missing"] == NOT_QUERIED:
                situation = "Não foi possível consultar"
            else:
                situation = "Sem peso" if p["total"] is None else f"{p['missing']} item(ns) sem peso"
            for column, text in enumerate([p["number"], p["customer"], situation]):
                cell = QTableWidgetItem(str(text))
                cell.setData(Qt.UserRole, p["id"])
                self.table.setItem(row, column, cell)
        self.inform_button.setEnabled(False)

    def inform_weight(self) -> None:
        selected = self.table.selectedItems()
        if not selected:
            return
        pid = selected[0].data(Qt.UserRole)
        try:
            dialog = ItemWeightDialog(self.service, pid, self)
            if not (dialog.exec() and dialog.saved_count):
                return
        except Exception as exc:
            QMessageBox.warning(self, "Informar peso", f"Não foi possível abrir os itens da proposta: {exc}")
            return
        # collect_weights não lança: falha de consulta vira NOT_QUERIED.
        fresh = collect_weights(self.service, [{"items": [i for log_ in self.logs for i in active_items(log_) if i.get("proposal_id") == pid]}])
        # Falha ao reconsultar mantém o último estado conhecido em vez de virar "não consultado".
        self.weights.update({k: v for k, v in fresh.items() if v[1] != NOT_QUERIED})
        self._fill()
