from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from app.ui.components.badge_delegate import BadgeColumnDelegate, set_status_badge
from app.ui.components.detail_widgets import EM_DASH, make_panel
from app.ui.components.modern_button import ModernButton
from app.ui.format_utils import format_empty, format_quantity
from app.ui.table_utils import resize_rows_to_contents

_STATUS_COLUMN = 1
_NUMERIC_COLUMNS = (5, 6)


class CargasTab(QWidget):
    """Aba "Cargas": lista as cargas de galvanizacao vinculadas a proposta
    (`service.process_loads()`, ja usado no dialogo antigo) e abre o dialogo
    oficial de detalhe de carga (`GalvanizationLoadDetailsDialog`) por duplo
    clique/botao "Abrir" - sem reimplementar a tela de carga aqui."""

    COLUMNS = ["Carga", "Situação", "Envio", "Retorno", "Motorista", "Itens", "Propostas", "Observações"]

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._loads: list[dict[str, Any]] = []
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.summary_panel, summary_layout = make_panel()
        row = QHBoxLayout()
        row.setSpacing(12)
        self.summary = QLabel("Nenhuma carga vinculada.")
        self.summary.setObjectName("PanelTitle")
        row.addWidget(self.summary)
        row.addStretch(1)
        self.open_button = ModernButton("Abrir carga selecionada", "load")
        self.open_button.clicked.connect(self._open_selected)
        self.open_button.setEnabled(False)
        row.addWidget(self.open_button)
        summary_layout.addLayout(row)
        layout.addWidget(self.summary_panel)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.verticalHeader().setMinimumSectionSize(40)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.horizontalHeader().setSectionResizeMode(len(self.COLUMNS) - 1, QHeaderView.Stretch)
        for col, width in enumerate((100, 240, 120, 120, 150, 70, 100, 200)):
            self.table.setColumnWidth(col, width)
        self.table.setItemDelegateForColumn(_STATUS_COLUMN, BadgeColumnDelegate(self.table))
        self.table.doubleClicked.connect(self._open_selected)
        self.table.itemSelectionChanged.connect(
            lambda: self.open_button.setEnabled(bool(self.table.selectionModel().selectedRows()))
        )
        layout.addWidget(self.table, 1)

    def load(self, loads: list[dict[str, Any]]):
        self._loads = list(loads or [])
        self.summary.setText(
            "Nenhuma carga vinculada." if not self._loads else f"{len(self._loads)} carga(s) vinculada(s)."
        )
        self.table.setRowCount(len(self._loads))
        for row, load in enumerate(self._loads):
            status = load.get("status") or ""
            values = [
                format_empty(load.get("codigo") or load.get("id")),
                self.service.load_status_label(status) or "-",
                format_empty(load.get("data_envio"), EM_DASH),
                format_empty(load.get("data_retorno"), EM_DASH),
                format_empty(load.get("motorista"), EM_DASH),
                format_quantity(load.get("item_count")),
                format_quantity(load.get("proposal_count")),
                format_empty(load.get("observacao"), EM_DASH),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                side = Qt.AlignRight if col in _NUMERIC_COLUMNS else Qt.AlignLeft
                cell.setTextAlignment(Qt.AlignVCenter | side)
                if col == _STATUS_COLUMN:
                    set_status_badge(cell, status, self.service.palette, "GALVANIZACAO")
                self.table.setItem(row, col, cell)
        resize_rows_to_contents(self.table)
        self.open_button.setEnabled(False)
        return len(self._loads)

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
