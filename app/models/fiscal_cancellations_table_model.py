from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from app.models.fiscal_table_model import format_weight

FISCAL_CANCELLATION_COLUMNS: list[tuple[str, str]] = [
    ("proposta", "Proposta"),
    ("cliente", "Cliente"),
    ("numero_controle", "NF"),
    ("serie", "Série"),
    ("data_emissao", "Emissão"),
    ("itens_resumo", "Itens (item: qtd.)"),
    ("peso_emitido", "Peso"),
    ("motivo_cancelamento", "Motivo"),
    ("cancelado_por", "Cancelada por"),
    ("cancelado_em", "Cancelada em"),
]


class FiscalCancellationsTableModel(QAbstractTableModel):
    """Notas canceladas (somente leitura); `itens_resumo` vem pronto da tela."""

    def __init__(self, rows: list[dict[str, Any]] | None = None):
        super().__init__()
        self.columns = FISCAL_CANCELLATION_COLUMNS
        self.rows = rows or []

    def set_rows(self, rows: list[dict[str, Any]]):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        key, _label = self.columns[index.column()]
        value = row.get(key)
        if role in (Qt.DisplayRole, Qt.EditRole):
            if key == "peso_emitido":
                return format_weight(value)
            return str(value or "-")
        if role == Qt.ToolTipRole and key in {"motivo_cancelamento", "itens_resumo"}:
            return str(value or "")
        if role == Qt.UserRole:
            return row
        if role == Qt.UserRole + 1:
            return key
        if role == Qt.UserRole + 2:
            return value
        if role == Qt.UserRole + 3:
            return "FISCAL"
        if role == Qt.TextAlignmentRole:
            return Qt.AlignVCenter | (Qt.AlignRight if key == "peso_emitido" else Qt.AlignLeft)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        return self.columns[section][1] if orientation == Qt.Horizontal else section + 1
