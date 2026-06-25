from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from app.models.fiscal_table_model import fiscal_status_label, format_number, format_weight


class FiscalItemsTableModel(QAbstractTableModel):
    columns = [
        ("numero_item", "Item"),
        ("codigo_produto", "Codigo"),
        ("descricao", "Descricao"),
        ("quantidade_total", "Qtd. total"),
        ("quantidade_faturada", "Qtd. faturada"),
        ("quantidade_pendente", "Qtd. pendente"),
        ("peso_total", "Peso total"),
        ("peso_faturado", "Peso faturado"),
        ("peso_pendente", "Peso pendente"),
        ("status_item_fiscal", "Status item"),
    ]

    def __init__(self, rows: list[dict[str, Any]] | None = None):
        super().__init__()
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
            if key == "status_item_fiscal":
                return fiscal_status_label(str(value or ""))
            if key.startswith("peso_"):
                return format_weight(value)
            if key.startswith("quantidade_"):
                return format_number(value)
            return str(value or "-")
        if role == Qt.UserRole:
            return row
        if role == Qt.UserRole + 1:
            return key
        if role == Qt.UserRole + 2:
            return row.get("status_item_fiscal") if key == "status_item_fiscal" else value
        if role == Qt.UserRole + 3:
            return "FISCAL"
        if role == Qt.TextAlignmentRole:
            if key.startswith("quantidade_") or key.startswith("peso_"):
                return Qt.AlignVCenter | Qt.AlignRight
            if key == "descricao":
                return Qt.AlignTop | Qt.AlignLeft
            return Qt.AlignVCenter | Qt.AlignLeft
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.columns[section][1]
        return section + 1

    def sort(self, column, order=Qt.AscendingOrder):
        key, _label = self.columns[column]
        reverse = order == Qt.DescendingOrder
        self.layoutAboutToBeChanged.emit()
        self.rows.sort(key=lambda row: str(row.get(key) or "").lower(), reverse=reverse)
        self.layoutChanged.emit()
