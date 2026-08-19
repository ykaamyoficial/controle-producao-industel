from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from app.ui.format_utils import format_empty, format_quantity
from app.ui.table_utils import resize_rows_to_contents


class CargasTab(QWidget):
    """Aba "Cargas": lista as cargas de galvanizacao vinculadas a proposta
    (`service.process_loads()`, ja usado no dialogo antigo) e abre o dialogo
    oficial de detalhe de carga (`GalvanizationLoadDetailsDialog`) por duplo
    clique/botao "Abrir" - sem reimplementar a tela de carga aqui."""

    COLUMNS = ["Carga", "Situacao", "Envio", "Retorno", "Motorista", "Itens", "Propostas", "Observacoes"]

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._loads: list[dict[str, Any]] = []
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        self.summary = QLabel("Nenhuma carga vinculada.")
        self.summary.setObjectName("Caption")
        layout.addWidget(self.summary)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(len(self.COLUMNS) - 1, QHeaderView.Stretch)
        for col, width in enumerate((90, 170, 130, 130, 130, 70, 80, 200)):
            self.table.setColumnWidth(col, width)
        self.table.doubleClicked.connect(self._open_selected)
        layout.addWidget(self.table, 1)

        self.open_button = QPushButton("Abrir carga selecionada")
        self.open_button.clicked.connect(self._open_selected)
        self.open_button.setEnabled(False)
        self.table.itemSelectionChanged.connect(
            lambda: self.open_button.setEnabled(bool(self.table.selectionModel().selectedRows()))
        )
        layout.addWidget(self.open_button)

    def load(self, loads: list[dict[str, Any]]):
        self._loads = list(loads or [])
        self.summary.setText(
            "Nenhuma carga vinculada." if not self._loads else f"{len(self._loads)} carga(s) vinculada(s)."
        )
        self.table.setRowCount(len(self._loads))
        for row, load in enumerate(self._loads):
            values = [
                format_empty(load.get("codigo") or load.get("id")),
                self.service.load_status_label(load.get("status") or "") or "-",
                format_empty(load.get("data_envio")),
                format_empty(load.get("data_retorno")),
                format_empty(load.get("motorista")),
                format_quantity(load.get("item_count")),
                format_quantity(load.get("proposal_count")),
                format_empty(load.get("observacao")),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                cell.setTextAlignment(Qt.AlignVCenter | (Qt.AlignLeft if col == len(values) - 1 else Qt.AlignCenter))
                self.table.setItem(row, col, cell)
        resize_rows_to_contents(self.table)
        self.open_button.setEnabled(False)

    def _open_selected(self):
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return
        row = selected[0].row()
        if row < 0 or row >= len(self._loads):
            return
        load_id = self._loads[row].get("id")
        if not load_id:
            return
        from app.ui.galvanization_load_details_dialog import GalvanizationLoadDetailsDialog

        dialog = GalvanizationLoadDetailsDialog(self.service, int(load_id), self)
        dialog.exec()
