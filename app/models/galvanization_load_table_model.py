from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


def _display_weight(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    text = str(int(number)) if number.is_integer() else f"{number:.2f}"
    return f"{text} kg"


LOAD_COLUMNS = [
    ("status_icon", ""),
    ("id", "Carga"),
    ("status", "Status"),
    ("motorista", "Motorista"),
    ("peso_informado_carga", "Peso da carga"),
    ("proposal_count", "Propostas"),
    ("data_prevista_retorno", "Prev. retorno"),
    ("data_retorno", "Retorno"),
    ("criado_em", "Criada em"),
    ("criado_por", "Usuario"),
]


class GalvanizationLoadTableModel(QAbstractTableModel):
    """Tabela de cargas — mesmo padrão de ProcessTableModel/ItemTableModel
    (ícone de status clicável na frente + badge colorido via StatusBadgeDelegate)."""

    def __init__(self, service, rows: list[dict[str, Any]] | None = None):
        super().__init__()
        self.service = service
        self.columns = LOAD_COLUMNS
        self.rows = rows or []

    def set_rows(self, rows: list[dict[str, Any]]):
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
        if role == Qt.UserRole + 1:
            return key
        if role == Qt.UserRole + 2:
            if key == "status_icon":
                return row.get("status", "")
            return row.get(key, "")
        if role == Qt.UserRole + 3:
            return "GALVANIZACAO"
        if role in (Qt.DisplayRole, Qt.EditRole):
            if key == "status_icon":
                return ""
            if key == "status":
                return self.service.load_status_label(row.get("status") or "")
            if key == "peso_informado_carga":
                return _display_weight(row.get(key))
            return self.service.display_cell(key, row.get(key), row)
        if role == Qt.ToolTipRole:
            if key == "status_icon":
                status_text = self.service.load_status_label(row.get("status") or "")
                return f"{status_text}\nAbrir acoes da carga" if status_text else "Abrir acoes da carga"
            return self.data(index, Qt.DisplayRole)
        if role == Qt.TextAlignmentRole:
            if key in {"id", "peso_informado_carga", "proposal_count"}:
                return Qt.AlignCenter
            return Qt.AlignVCenter | Qt.AlignLeft
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.columns[section][1]
        return section + 1

    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder):
        key, _label = self.columns[column]
        reverse = order == Qt.DescendingOrder
        self.layoutAboutToBeChanged.emit()
        self.rows.sort(key=lambda row: str(row.get(key) or "").lower(), reverse=reverse)
        self.layoutChanged.emit()

    def process_id_at(self, row: int) -> int | None:
        """Mesma interface que ModernTable ja espera — aqui devolve o id da carga."""
        if row < 0 or row >= len(self.rows):
            return None
        load_id = self.rows[row].get("id")
        return int(load_id) if load_id else None

    def load_row_at(self, row: int) -> dict[str, Any] | None:
        if row < 0 or row >= len(self.rows):
            return None
        return self.rows[row]
