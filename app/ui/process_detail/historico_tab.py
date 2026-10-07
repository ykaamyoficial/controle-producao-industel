from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from app.ui.components.badge_delegate import BadgeColumnDelegate, set_status_badge
from app.ui.components.detail_widgets import EM_DASH
from app.ui.format_utils import format_empty
from app.ui.sidebar import NAV_LABELS

_NEW_STATUS_COLUMN = 2


class HistoricoTab(QWidget):
    """Aba "Historico": visao cronologica unica consolidando
    `service.process_history_rows()` (a mesma auditoria que ja alimentava a
    "Linha do tempo" do dialogo antigo) - uma unica camada de apresentacao,
    sem duplicar a auditoria em varias fontes. O status novo aparece como
    selo; o anterior, como texto."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.summary = QLabel("Sem registro de histórico.")
        self.summary.setObjectName("KeyLabel")
        layout.addWidget(self.summary)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Área", "Anterior", "Novo", "Quando", "Usuário", "Observação"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        for col, width in enumerate((150, 210, 230, 150, 120, 360)):
            self.table.setColumnWidth(col, width)
        self.table.setItemDelegateForColumn(_NEW_STATUS_COLUMN, BadgeColumnDelegate(self.table))
        layout.addWidget(self.table, 1)

    def load(self, process_ids: list[int]):
        history: list[dict[str, Any]] = []
        for process_id in process_ids:
            history.extend(self.service.process_history_rows(process_id))
        history.sort(key=lambda item: str(item.get("data_hora") or ""), reverse=True)
        if not history:
            self.summary.setText("Sem registro de histórico.")
        elif len(history) == 1:
            self.summary.setText("1 movimentação registrada")
        else:
            self.summary.setText(f"{len(history)} movimentações registradas, da mais recente para a mais antiga")
        self.table.setRowCount(len(history))
        for row, item in enumerate(history):
            area = str(item.get("area") or "")
            new_status = item.get("status_novo") or ""
            values = [
                NAV_LABELS.get(area.strip().upper(), format_empty(area, EM_DASH)),
                self.service.area_status_label(area, item.get("status_anterior") or "") if item.get("status_anterior") else EM_DASH,
                self.service.area_status_label(area, new_status) if new_status else EM_DASH,
                format_empty(item.get("data_hora"), EM_DASH),
                format_empty(item.get("usuario"), EM_DASH),
                format_empty(item.get("observacao"), EM_DASH),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                cell.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                if col == _NEW_STATUS_COLUMN and new_status:
                    set_status_badge(cell, new_status, self.service.palette, area)
                self.table.setItem(row, col, cell)
        return history
