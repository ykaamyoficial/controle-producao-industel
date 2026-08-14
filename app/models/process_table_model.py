from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor

from app.ui.components.batch_selection import BatchSelectionController


DEFAULT_COLUMNS = [
    ("status_icon", ""),
    ("proposta", "Proposta"),
    ("chat_icon", ""),
    ("cliente", "Cliente"),
    ("status_localizacao", "Status"),
    ("obra_site", "Obra/Site"),
    ("progresso_peso", "Peso/Saldo"),
    ("prazo_entrega", "Prazo"),
    ("id", "ID"),
    ("tipo_processo", "Tipo"),
    ("pedido_compra", "PD / Pedido"),
    ("lote", "Lote"),
    ("localizacao_atual", "Localizacao"),
]


AREA_COLUMNS = {
    "PRODUCAO": [
        ("status_icon", ""),
        ("proposta", "Proposta"), ("chat_icon", ""), ("cliente", "Cliente"), ("status_producao", "Status producao"),
        ("obra_site", "Obra/Site"), ("progresso_peso", "Peso/Saldo"), ("prazo_entrega", "Prazo"),
        ("id", "ID"), ("tipo_processo", "Tipo"), ("pedido_compra", "PD / Pedido"),
        ("lote", "Lote"), ("data_entrada", "Entrada"),
    ],
    "GALVANIZACAO": [
        ("status_icon", ""),
        ("proposta", "Proposta"), ("chat_icon", ""), ("cliente", "Cliente"), ("status_galvanizacao", "Status galvanizacao"),
        ("obra_site", "Obra/Site"), ("progresso_peso", "Peso/Saldo"), ("prazo_entrega", "Prazo"),
        ("id", "ID"), ("tipo_processo", "Tipo"), ("pedido_compra", "PD / Pedido"),
        ("lote", "Lote"), ("carga_galvanizacao", "Carga"), ("data_envio_galv", "Envio Galv."),
        ("data_prevista_retorno_galv", "Prev. Retorno"), ("data_retorno_galv", "Retorno Galv."),
    ],
    "EXPEDICAO": [
        ("status_icon", ""),
        ("proposta", "Proposta"), ("chat_icon", ""), ("cliente", "Cliente"), ("status_expedicao", "Status expedicao"),
        ("obra_site", "Obra/Site"), ("progresso_peso", "Peso/Saldo"), ("prazo_entrega", "Prazo"),
        ("id", "ID"), ("tipo_processo", "Tipo"), ("pedido_compra", "PD / Pedido"),
        ("lote", "Lote"), ("almoxarifado_info", "Almox."),
    ],
    "ALMOXARIFADO": [
        ("status_icon", ""),
        ("proposta", "Proposta"), ("chat_icon", ""), ("cliente", "Cliente"), ("status_almoxarifado", "Status almoxarifado"),
        ("obra_site", "Obra/Site"), ("progresso_peso", "Peso/Saldo"), ("prazo_entrega", "Prazo"),
        ("id", "ID"), ("tipo_processo", "Tipo"), ("pedido_compra", "PD / Pedido"),
        ("lote", "Lote"), ("data_entrada", "Entrada"), ("necessita_almoxarifado", "Necessita"),
    ],
}


class ProcessTableModel(QAbstractTableModel):
    def __init__(self, service, area: str | None = None, rows: list[dict[str, Any]] | None = None):
        super().__init__()
        self.service = service
        self.area = area
        self._base_columns = list(AREA_COLUMNS.get(area or "", DEFAULT_COLUMNS))
        self.columns = list(self._base_columns)
        self.rows = rows or []
        self.batch_selection: BatchSelectionController | None = None

    def set_batch_selection_controller(self, controller: BatchSelectionController) -> None:
        self.batch_selection = controller
        controller.selection_changed.connect(self._batch_selection_changed)

    def set_batch_selection_mode(self, active: bool) -> None:
        expected = [("batch_select", ""), *self._base_columns] if active else list(self._base_columns)
        if self.columns == expected:
            return
        self.beginResetModel()
        self.columns = expected
        self.endResetModel()

    def set_rows(self, rows: list[dict[str, Any]]):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        key, _label = self.columns[index.column()]
        process_id = int(row.get("id") or 0)
        if key == "batch_select":
            if role == Qt.CheckStateRole:
                return Qt.Checked if self.batch_selection and self.batch_selection.is_selected(process_id) else Qt.Unchecked
            if role in (Qt.DisplayRole, Qt.EditRole):
                return ""
        if role == Qt.UserRole:
            return row
        if role == Qt.UserRole + 1:
            return key
        if role == Qt.UserRole + 2:
            if key == "status_icon":
                area, _label, status = self.service.current_location(row)
                return status
            if key == "chat_icon":
                return row.get("_chat_unread", 0)
            if key == "status_localizacao":
                return self.service.current_location(row)[2]
            if key == "localizacao_atual":
                return self.service.current_location(row)[0]
            return row.get(key, "")
        if role == Qt.UserRole + 3:
            if key == "chat_icon":
                return row.get("_chat_has_messages", False)
            if key in {"status_localizacao", "localizacao_atual", "status_icon"}:
                return self.service.current_location(row)[0]
            return {
                "status_geral": "CONTROLE GERAL",
                "status_producao": "PRODUCAO",
                "status_galvanizacao": "GALVANIZACAO",
                "status_expedicao": "EXPEDICAO",
                "status_almoxarifado": "ALMOXARIFADO",
            }.get(key, "")
        if role in (Qt.DisplayRole, Qt.EditRole):
            if key in {"status_icon", "chat_icon"}:
                return ""
            return self.service.display_cell(key, row.get(key), row)
        if role == Qt.ToolTipRole:
            if key == "status_icon":
                area, _label, status = self.service.current_location(row)
                status_text = self.service.area_status_label(area, status) if status else ""
                return f"{status_text}\nAbrir acoes da proposta" if status_text else "Abrir acoes da proposta"
            if key == "chat_icon":
                unread = row.get("_chat_unread", 0)
                return f"{unread} mensagem(ns) nao lida(s)" if unread else "Abrir chat da proposta"
            return self.data(index, Qt.DisplayRole)
        if role == Qt.TextAlignmentRole:
            if key in {"batch_select", "id", "peso", "peso_parcial", "saldo_pendente"}:
                return Qt.AlignCenter
            return Qt.AlignVCenter | Qt.AlignLeft
        if (
            role == Qt.BackgroundRole
            and self.batch_selection
            and self.batch_selection.active
            and self.batch_selection.is_selected(process_id)
        ):
            return QBrush(QColor(self.service.palette.get("tree_selected", self.service.palette.get("surface_alt"))))
        return None

    def flags(self, index: QModelIndex):
        flags = super().flags(index)
        if index.isValid() and self.columns[index.column()][0] == "batch_select":
            return flags | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return flags

    def setData(self, index: QModelIndex, value, role=Qt.EditRole):
        if (
            index.isValid()
            and role == Qt.CheckStateRole
            and self.columns[index.column()][0] == "batch_select"
            and self.batch_selection
        ):
            row = self.rows[index.row()]
            process_id = int(row.get("id") or 0)
            check_value = getattr(value, "value", value)
            if check_value == Qt.CheckState.Checked.value:
                self.batch_selection.select(process_id, row)
            else:
                self.batch_selection.deselect(process_id)
            return True
        return False

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
        if row < 0 or row >= len(self.rows):
            return None
        return int(self.rows[row]["id"])

    def _batch_selection_changed(self) -> None:
        if not self.rows or not self.columns:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self.rows) - 1, len(self.columns) - 1),
            [Qt.CheckStateRole, Qt.BackgroundRole],
        )
