from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from app.ui.format_utils import format_empty


class HistoricoTab(QWidget):
    """Aba "Historico": visao cronologica unica consolidando
    `service.process_history_rows()` (a mesma auditoria que ja alimentava a
    "Linha do tempo" do dialogo antigo) - uma unica camada de apresentacao,
    sem duplicar a auditoria em varias fontes."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        self.summary = QLabel("Sem registro de historico.")
        self.summary.setObjectName("Caption")
        layout.addWidget(self.summary)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Area", "Anterior", "Novo", "Quando", "Usuario", "Observacao"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        for col, width in enumerate((130, 160, 160, 145, 110, 360)):
            self.table.setColumnWidth(col, width)
        layout.addWidget(self.table, 1)

    def load(self, process_ids: list[int]):
        history: list[dict[str, Any]] = []
        for process_id in process_ids:
            history.extend(self.service.process_history_rows(process_id))
        history.sort(key=lambda item: str(item.get("data_hora") or ""), reverse=True)
        self.summary.setText(
            "Sem registro de historico." if not history else f"{len(history)} movimentacao(oes) registrada(s)"
        )
        self.table.setRowCount(len(history))
        for row, item in enumerate(history):
            values = [
                format_empty(item.get("area")),
                self.service.area_status_label(item.get("area") or "", item.get("status_anterior") or "") if item.get("status_anterior") else "-",
                self.service.area_status_label(item.get("area") or "", item.get("status_novo") or "") if item.get("status_novo") else "-",
                format_empty(item.get("data_hora")),
                format_empty(item.get("usuario")),
                format_empty(item.get("observacao")),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                cell.setTextAlignment(Qt.AlignCenter if col < 5 else Qt.AlignVCenter | Qt.AlignLeft)
                self.table.setItem(row, col, cell)
        return history
