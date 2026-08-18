from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


LOAD_COLUMNS = [
    ("code", "Codigo"),
    ("status", "Status"),
    ("expected_ship_date", "Previsao de envio"),
    ("carrier_name", "Transportadora"),
    ("responsible_user_name", "Responsavel"),
    ("total_planned_quantity", "Planejado"),
    ("total_available_quantity", "Disponivel"),
    ("total_missing_quantity", "Faltante"),
]

_NUMERIC_COLUMNS = {"total_planned_quantity", "total_available_quantity", "total_missing_quantity"}


def _display_value(key: str, value: Any) -> str:
    if value in (None, ""):
        return "-"
    return str(value)


class PlannedLoadTableModel(QAbstractTableModel):
    """Tabela de planejamentos de carga (FASE_PL5) -- mesmo padrao de
    `GalvanizationLoadTableModel` (QAbstractTableModel/LOAD_COLUMNS/set_rows),
    porem sem icone de status/badge: indicador visual de divergencia e
    contagem ficam para a fase PL6."""

    def __init__(self, rows: list[dict[str, Any]] | None = None):
        super().__init__()
        self.columns = LOAD_COLUMNS
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
        if role == Qt.UserRole:
            return row
        if role in (Qt.DisplayRole, Qt.EditRole):
            return _display_value(key, row.get(key))
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

    def load_row_at(self, row: int) -> dict[str, Any] | None:
        if row < 0 or row >= len(self.rows):
            return None
        return self.rows[row]

    def load_id_at(self, row: int) -> int | None:
        candidate = self.load_row_at(row)
        if not candidate:
            return None
        load_id = candidate.get("id")
        return int(load_id) if load_id else None
