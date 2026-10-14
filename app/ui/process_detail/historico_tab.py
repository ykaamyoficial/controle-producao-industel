from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.components.badge_delegate import BadgeColumnDelegate, set_status_badge
from app.ui.components.detail_widgets import EM_DASH
from app.ui.format_utils import format_empty
from app.ui.sidebar import NAV_LABELS

_WHEN_COLUMN = 0
_AREA_COLUMN = 1
_WHAT_COLUMN = 2
_STATUS_COLUMN = 3
_DETAIL_COLUMN = 4
_ALL_AREAS = "Todas as áreas"
_ARROW = "→"


def friendly_when(value: Any, now: datetime | None = None) -> str:
    """"Hoje 19:17", "Ontem 19:17", "28/09 19:17" (mesmo ano) ou a data completa.
    Texto que nao seja data (dd/mm/aaaa hh:mm[:ss]) volta como veio."""
    text = str(value or "").strip()
    if not text:
        return EM_DASH
    parsed = None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        return text
    today = (now or datetime.now()).date()
    clock = parsed.strftime("%H:%M")
    if parsed.date() == today:
        return f"Hoje {clock}"
    if parsed.date() == today - timedelta(days=1):
        return f"Ontem {clock}"
    if parsed.year == today.year:
        return f"{parsed.strftime('%d/%m')} {clock}"
    return f"{parsed.strftime('%d/%m/%Y')} {clock}"


class HistoricoTab(QWidget):
    """Aba "Historico": visao cronologica unica consolidando
    `service.process_history_rows()` (a mesma auditoria que ja alimentava a
    "Linha do tempo" do dialogo antigo) - uma unica camada de apresentacao,
    sem duplicar a auditoria em varias fontes.

    A frase de cada linha ("Joao definiu o fluxo de producao de 8 itens.") vem
    pronta da API (`titulo`); aqui nunca se mostra codigo de evento nem
    metadata crua. O selo so aparece quando houve mudanca real de status."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._history: list[dict[str, Any]] = []
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel("Sem registro de histórico.")
        self.summary.setObjectName("KeyLabel")
        header.addWidget(self.summary, 1)
        self.area_filter = QComboBox()
        self.area_filter.setMinimumWidth(170)
        self.area_filter.addItem(_ALL_AREAS, "")
        self.area_filter.currentIndexChanged.connect(self._render)
        header.addWidget(self.area_filter)
        layout.addLayout(header)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Quando", "Área", "O que aconteceu", "Status", "Detalhe"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.horizontalHeader().setSectionResizeMode(_WHAT_COLUMN, QHeaderView.Stretch)
        for col, width in ((_WHEN_COLUMN, 120), (_AREA_COLUMN, 140), (_STATUS_COLUMN, 330), (_DETAIL_COLUMN, 260)):
            self.table.setColumnWidth(col, width)
        self.table.setItemDelegateForColumn(_STATUS_COLUMN, BadgeColumnDelegate(self.table))
        layout.addWidget(self.table, 1)

    def load(self, process_ids: list[int]):
        history: list[dict[str, Any]] = []
        for process_id in process_ids:
            history.extend(self.service.process_history_rows(process_id))
        return self.show(history)

    def show(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Mostra um historico ja buscado (a selecao de parcial do Detalhe busca em segundo plano)."""
        history = sorted(history, key=lambda item: str(item.get("data_hora") or ""), reverse=True)
        self._history = history
        self._refresh_area_filter()
        self._render()
        return history

    def _area_key(self, item: dict[str, Any]) -> str:
        return str(item.get("area") or "").strip().upper()

    def _area_label(self, area_key: str) -> str:
        return NAV_LABELS.get(area_key, format_empty(area_key.title(), EM_DASH))

    def _refresh_area_filter(self):
        current = self.area_filter.currentData()
        keys = sorted({self._area_key(item) for item in self._history if self._area_key(item)}, key=self._area_label)
        self.area_filter.blockSignals(True)
        self.area_filter.clear()
        self.area_filter.addItem(_ALL_AREAS, "")
        for key in keys:
            self.area_filter.addItem(self._area_label(key), key)
        index = self.area_filter.findData(current) if current else 0
        self.area_filter.setCurrentIndex(max(index, 0))
        self.area_filter.blockSignals(False)
        self.area_filter.setVisible(len(keys) > 1)

    def _title(self, item: dict[str, Any]) -> str:
        title = str(item.get("titulo") or "").strip()
        if title:
            return title
        return format_empty(item.get("observacao"), EM_DASH)

    def _status_text(self, item: dict[str, Any], area: str) -> str:
        new_status = item.get("status_real_novo") or ""
        if not new_status:
            return ""
        new_label = self.service.area_status_label(area, new_status)
        previous = item.get("status_anterior") or ""
        if previous and previous != new_status:
            return f"{self.service.area_status_label(area, previous)} {_ARROW} | {new_label}"
        return new_label

    def _render(self, *_):
        selected = self.area_filter.currentData() or ""
        rows = [item for item in self._history if not selected or self._area_key(item) == selected]
        total = sum(int(item.get("quantidade") or 1) for item in rows)
        if not self._history:
            self.summary.setText("Sem registro de histórico.")
        elif len(rows) == 1 and total == 1:
            self.summary.setText("1 movimentação registrada")
        elif total != len(rows):
            self.summary.setText(f"{len(rows)} registros ({total} movimentações, lotes agrupados), do mais recente para o mais antigo")
        else:
            self.summary.setText(f"{len(rows)} movimentações registradas, da mais recente para a mais antiga")
        self.table.setRowCount(len(rows))
        for row, item in enumerate(rows):
            area = str(item.get("area") or "")
            status_text = self._status_text(item, area)
            values = [
                friendly_when(item.get("data_hora")),
                self._area_label(self._area_key(item)) if area else EM_DASH,
                self._title(item),
                status_text,
                format_empty(item.get("detalhe"), ""),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                cell.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                cell.setToolTip(str(value or "") if col != _WHEN_COLUMN else str(item.get("data_hora") or ""))
                if col == _STATUS_COLUMN and status_text:
                    set_status_badge(cell, item.get("status_real_novo") or "", self.service.palette, area)
                self.table.setItem(row, col, cell)
