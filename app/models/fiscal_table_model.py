from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


FISCAL_STATUS_LABELS = {
    "FALTA_EMITIR_NOTA_FISCAL": "Falta emitir NF",
    "NOTA_FISCAL_PARCIAL": "NF parcial",
    "NOTA_FISCAL_EMITIDA": "NF emitida",
    "FISCAL_CANCELADO": "Fiscal cancelado",
    "PENDENTE": "Pendente",
    "PARCIAL": "Parcial",
    "FATURADO": "Faturado",
    "CANCELADO": "Cancelado",
}


def fiscal_status_label(status: str) -> str:
    return FISCAL_STATUS_LABELS.get((status or "").strip().upper(), status or "-")


def format_number(value: Any) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def format_weight(value: Any) -> str:
    return f"{format_number(value)} kg"


class FiscalProcessTableModel(QAbstractTableModel):
    columns = [
        ("proposta", "Proposta"),
        ("cliente", "Cliente"),
        ("status_fiscal", "Status Fiscal"),
        ("obra_site", "Obra/Site"),
        ("data_entrada_fiscal", "Entrada Fiscal"),
        ("data_ultima_emissao", "Ultima emissao"),
        ("pendencia_critica", "Alerta"),
        ("acoes", "Acoes"),
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
            if key == "acoes":
                return "..."
            if key == "status_fiscal":
                return fiscal_status_label(str(value or ""))
            if key == "pendencia_critica":
                alerts = []
                if int(row.get("pendencia_critica") or 0):
                    alerts.append("Critica")
                if int(row.get("mais_7_dias_sem_emissao") or 0):
                    alerts.append("+7 dias")
                return " | ".join(alerts) if alerts else "-"
            if key.startswith("peso_"):
                return format_weight(value)
            return str(value or "-")
        if role == Qt.UserRole:
            return row
        if role == Qt.UserRole + 1:
            return key
        if role == Qt.UserRole + 2:
            if key == "acoes":
                return ""
            if key == "pendencia_critica" and int(value or 0):
                return "FALTA_EMITIR_NOTA_FISCAL"
            if key == "pendencia_critica" and int(row.get("mais_7_dias_sem_emissao") or 0):
                return "NOTA_FISCAL_PARCIAL"
            return row.get("status_fiscal") if key == "status_fiscal" else value
        if role == Qt.UserRole + 3:
            return "FISCAL"
        if role == Qt.TextAlignmentRole:
            if key == "acoes":
                return Qt.AlignCenter
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

    def process_id_at(self, row: int) -> int | None:
        if 0 <= row < len(self.rows):
            return int(self.rows[row].get("processo_id") or 0)
        return None

    def fiscal_id_at(self, row: int) -> int | None:
        if 0 <= row < len(self.rows):
            return int(self.rows[row].get("fiscal_processo_id") or 0)
        return None
