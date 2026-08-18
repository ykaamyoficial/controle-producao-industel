from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QApplication, QStyle


ITEM_COLUMNS = [
    ("proposal_number", "Proposta"),
    ("customer_name", "Cliente"),
    ("item_number", "Codigo"),
    ("description", "Descricao"),
    ("planned_quantity", "Qtd. planejada"),
    ("currently_available_quantity", "Qtd. disponivel"),
    ("missing_quantity", "Qtd. faltante"),
]

_NUMERIC_COLUMNS = {"planned_quantity", "currently_available_quantity", "missing_quantity"}

# Traducao de `PlannedLoadItemSummary.divergence_reason` (FASE_PL2/backend)
# para o tooltip do indicador visual de divergencia (FASE_PL6). Nunca abre
# QMessageBox automatico -- e so um sinal passivo na tabela.
DIVERGENCE_REASON_LABELS = {
    "PROPOSAL_CANCELLED": "Proposta cancelada",
    "ITEM_INACTIVE": "Item inativo",
    "QUANTITY_REDUCED": "Quantidade reduzida na proposta",
}

# Amarelo suave -- mesmo tom de alerta nao-bloqueante usado em outras
# tabelas do projeto (ver FiscalProcessTableModel, que tambem hardcoda a cor
# de fundo em vez de depender de um `service.palette`).
_DIVERGENCE_BACKGROUND = QColor(255, 243, 205)


def divergence_reason_label(reason: str | None) -> str:
    if not reason:
        return "Este item tem divergencia entre a quantidade planejada e a disponivel."
    return DIVERGENCE_REASON_LABELS.get(reason, reason)


def _display_value(key: str, value: Any) -> str:
    if value in (None, ""):
        return "-"
    return str(value)


class PlannedLoadItemTableModel(QAbstractTableModel):
    """Tabela de itens dentro do `PlannedLoadDialog`. Mostra pelo menos
    proposal_number/customer_name/item_number/description/planned_quantity/
    currently_available_quantity/missing_quantity, que ja chegam prontos em
    `PlannedLoadItemSummary` (o backend computa disponibilidade real na
    FASE_PL2). Divergencia (`has_divergence`/`divergence_reason`) recebe um
    indicador visual NAO-BLOQUEANTE (FASE_PL6): icone de alerta na primeira
    coluna + fundo suave na linha + tooltip com o motivo traduzido -- nunca
    um QMessageBox automatico ao carregar a tela."""

    def __init__(self, rows: list[dict[str, Any]] | None = None):
        super().__init__()
        self.columns = ITEM_COLUMNS
        self.rows = rows or []

    def set_rows(self, rows: list[dict[str, Any]]) -> bool:
        if rows == self.rows:
            return False
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()
        return True

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        key, _label = self.columns[index.column()]
        has_divergence = bool(row.get("has_divergence"))
        if role == Qt.UserRole:
            return row
        if role in (Qt.DisplayRole, Qt.EditRole):
            return _display_value(key, row.get(key))
        if role == Qt.DecorationRole and index.column() == 0 and has_divergence:
            style = QApplication.style()
            return style.standardIcon(QStyle.SP_MessageBoxWarning) if style else None
        if role == Qt.ToolTipRole:
            if has_divergence:
                return divergence_reason_label(row.get("divergence_reason"))
            return _display_value(key, row.get(key))
        if role == Qt.BackgroundRole and has_divergence:
            return QBrush(_DIVERGENCE_BACKGROUND)
        if role == Qt.TextAlignmentRole:
            if key in _NUMERIC_COLUMNS:
                return Qt.AlignCenter
            return Qt.AlignVCenter | Qt.AlignLeft
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.columns[section][1]
        return section + 1

    def item_row_at(self, row: int) -> dict[str, Any] | None:
        if row < 0 or row >= len(self.rows):
            return None
        return self.rows[row]

    def item_id_at(self, row: int) -> int | None:
        """Id da linha de item DO PLANEJAMENTO (`PlannedLoadItemSummary.id`),
        usado no PATCH/DELETE de item -- nao confundir com
        `proposal_item_id`."""
        candidate = self.item_row_at(row)
        if not candidate:
            return None
        item_id = candidate.get("id")
        return int(item_id) if item_id else None
