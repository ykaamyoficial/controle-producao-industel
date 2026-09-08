from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor

from app.ui.components.batch_selection import BatchSelectionController


FISCAL_STATUS_LABELS = {
    "FALTA_EMITIR_NOTA_FISCAL": "Falta emitir NF",
    "AGUARDANDO_NF": "CP em processamento",
    "CP_EM_PROCESSAMENTO": "CP em processamento",
    "NF_EM_PROCESSAMENTO": "NF em processamento",
    "DISPONIVEL_PARA_EMISSAO": "Disponivel para emitir NF",
    "PENDENCIA_FISCAL_CRITICA": "Pendencia fiscal critica",
    "NOTA_FISCAL_PARCIAL": "NF parcial",
    "NF_PARCIAL": "NF parcial",
    "NOTA_FISCAL_EMITIDA": "NF emitida",
    "NF_EMITIDA": "NF emitida",
    "NF_RETIRADA_CLIENTE": "NF retirada pelo cliente",
    "FISCAL_CANCELADO": "Fiscal cancelado",
    "PENDENTE": "Pendente",
    "PARCIAL": "Parcial",
    "FATURADO": "Faturado",
    "CANCELADO": "Cancelado",
}


def fiscal_status_label(status: str) -> str:
    return FISCAL_STATUS_LABELS.get((status or "").strip().upper(), status or "-")


def fiscal_action_icon(row: dict[str, Any]) -> str:
    status = str(row.get("situacao_fiscal") or row.get("status_fiscal") or "").strip().upper()
    if int(row.get("pendencia_critica") or 0):
        return "fiscal_critical"
    if (
        str(row.get("status_expedicao") or "").strip().upper() == "ENTREGUE"
        and status not in {"NOTA_FISCAL_EMITIDA", "NF_EMITIDA", "NF_RETIRADA_CLIENTE"}
    ):
        return "fiscal_blocked"
    if status in {"NOTA_FISCAL_EMITIDA", "NF_EMITIDA", "NF_RETIRADA_CLIENTE"}:
        return "fiscal_done"
    if status in {"NOTA_FISCAL_PARCIAL", "NF_PARCIAL"}:
        return "fiscal_partial"
    return "fiscal_pending"


def fiscal_action_tooltip(row: dict[str, Any]) -> str:
    status = str(row.get("situacao_fiscal") or row.get("status_fiscal") or "").strip().upper()
    if int(row.get("pendencia_critica") or 0):
        return "Pendencia fiscal critica: retirado sem NF emitida"
    if (
        str(row.get("status_expedicao") or "").strip().upper() == "ENTREGUE"
        and status not in {"NOTA_FISCAL_EMITIDA", "NF_EMITIDA", "NF_RETIRADA_CLIENTE"}
    ):
        return "Proposta entregue sem nota fiscal"
    if status == "NF_RETIRADA_CLIENTE":
        return "Nota fiscal retirada pelo cliente"
    if status in {"NOTA_FISCAL_EMITIDA", "NF_EMITIDA"}:
        return "Nota fiscal emitida"
    if status in {"NOTA_FISCAL_PARCIAL", "NF_PARCIAL"}:
        return "Nota fiscal emitida parcialmente"
    return "Falta emitir nota fiscal"


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
        ("fiscal_action", ""),
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
        self._base_columns = list(self.columns)
        self.columns = list(self._base_columns)
        self.rows = rows or []
        self.batch_selection: BatchSelectionController | None = None
        self._selection_eligibility = lambda _row: True

    def set_batch_selection_controller(self, controller: BatchSelectionController) -> None:
        self.batch_selection = controller
        controller.selection_changed.connect(self._selection_changed)

    def set_selection_eligibility(self, checker) -> None:
        self._selection_eligibility = checker or (lambda _row: True)
        self._selection_changed()

    def set_batch_selection_mode(self, active: bool) -> None:
        expected = [("batch_select", "")] + self._base_columns if active else list(self._base_columns)
        if self.columns == expected:
            return
        self.beginResetModel()
        self.columns = expected
        self.endResetModel()

    def set_rows(self, rows: list[dict[str, Any]]):
        if rows == self.rows:
            return False
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()
        return True

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
        fiscal_id = int(row.get("fiscal_processo_id") or 0)
        if key == "batch_select":
            if role == Qt.CheckStateRole:
                return Qt.Checked if self.batch_selection and self.batch_selection.is_selected(fiscal_id) else Qt.Unchecked
            if role in (Qt.DisplayRole, Qt.EditRole):
                return ""
        if role in (Qt.DisplayRole, Qt.EditRole):
            if key == "fiscal_action":
                return ""
            if key == "acoes":
                return "..."
            if key == "status_fiscal":
                return fiscal_status_label(str(row.get("situacao_fiscal") or value or ""))
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
            if key == "fiscal_action":
                return fiscal_action_icon(row)
            if key == "acoes":
                return ""
            if key == "pendencia_critica" and int(value or 0):
                return "FALTA_EMITIR_NOTA_FISCAL"
            if key == "pendencia_critica" and int(row.get("mais_7_dias_sem_emissao") or 0):
                return "NOTA_FISCAL_PARCIAL"
            return (row.get("situacao_fiscal") or row.get("status_fiscal")) if key == "status_fiscal" else value
        if role == Qt.UserRole + 3:
            return "FISCAL"
        if role == Qt.ToolTipRole:
            if key == "fiscal_action":
                return fiscal_action_tooltip(row)
            return self.data(index, Qt.DisplayRole)
        if role == Qt.TextAlignmentRole:
            if key in {"batch_select", "acoes", "fiscal_action"}:
                return Qt.AlignCenter
            return Qt.AlignVCenter | Qt.AlignLeft
        if role == Qt.BackgroundRole and self.batch_selection and self.batch_selection.active and self.batch_selection.is_selected(fiscal_id):
            return QBrush(QColor("#e8f1ff"))
        return None

    def flags(self, index: QModelIndex):
        flags = super().flags(index)
        if index.isValid() and self.columns[index.column()][0] == "batch_select":
            if not self._selection_eligibility(self.rows[index.row()]):
                return flags & ~Qt.ItemIsEnabled
            return flags | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return flags

    def setData(self, index: QModelIndex, value, role=Qt.EditRole):
        if index.isValid() and role == Qt.CheckStateRole and self.columns[index.column()][0] == "batch_select" and self.batch_selection:
            row = self.rows[index.row()]
            if not self._selection_eligibility(row):
                return False
            fiscal_id = int(row.get("fiscal_processo_id") or 0)
            if getattr(value, "value", value) == Qt.CheckState.Checked.value:
                self.batch_selection.select(fiscal_id, row)
            else:
                self.batch_selection.deselect(fiscal_id)
            return True
        return False

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

    def fiscal_ids_at(self, row: int) -> list[int]:
        if 0 <= row < len(self.rows):
            values = self.rows[row].get("fiscal_processo_ids") or [self.rows[row].get("fiscal_processo_id")]
            return [int(value) for value in values if value]
        return []

    def _selection_changed(self) -> None:
        if self.rows and self.columns:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, len(self.columns) - 1), [Qt.CheckStateRole, Qt.BackgroundRole])
