from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class OperationalReportTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.columns: list[tuple[str, str]] = []
        self.rows: list[dict[str, Any]] = []

    def set_report(self, columns: list[tuple[str, str]], rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self.columns = list(columns)
        self.rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        key, _label = self.columns[index.column()]
        value = self.rows[index.row()].get(key, "")
        if role in (Qt.DisplayRole, Qt.EditRole):
            return _format_value(key, value)
        if role == Qt.TextAlignmentRole:
            if key.startswith("peso") or key.startswith("kg") or key.startswith("itens") or key.startswith("total"):
                return Qt.AlignVCenter | Qt.AlignRight
            return Qt.AlignVCenter | Qt.AlignLeft
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self.columns):
            return self.columns[section][1]
        if orientation == Qt.Vertical:
            return section + 1
        return None

    def sort(self, column, order=Qt.AscendingOrder):
        if not (0 <= column < len(self.columns)):
            return
        key, _label = self.columns[column]
        reverse = order == Qt.DescendingOrder
        self.layoutAboutToBeChanged.emit()
        self.rows.sort(key=lambda row: _sort_key(row.get(key)), reverse=reverse)
        self.layoutChanged.emit()


def _format_value(key: str, value: Any) -> str:
    if value is None or value == "":
        return "-"
    if key.startswith("peso") or key.startswith("kg"):
        try:
            return f"{float(value):,.2f} kg".replace(",", "X").replace(".", ",").replace("X", ".")
        except (TypeError, ValueError):
            return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(value)


def _sort_key(value: Any):
    if value is None:
        return ""
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value).lower()
