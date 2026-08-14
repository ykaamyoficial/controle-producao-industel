from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor

from app.ui.components.batch_selection import BatchSelectionController


AREA_ITEM_COLUMNS = {
    "PRODUCAO": [
        ("numero_item", "Item"),
        ("codigo_produto", "Codigo"),
        ("descricao", "Descricao"),
        ("proposta", "Proposta"),
        ("cliente", "Cliente"),
        ("quantidade", "Quantidade"),
        ("peso_total", "Peso total"),
        ("status_producao_item", "Status producao"),
        ("obra_site", "Obra/Site"),
        ("lote", "Lote"),
    ],
    "GALVANIZACAO": [
        ("numero_item", "Item"),
        ("proposta", "Proposta"),
        ("cliente", "Cliente"),
        ("descricao", "Descricao"),
        ("quantidade", "Quantidade"),
        ("quantidade_disponivel", "Disponivel"),
        ("quantidade_em_galvanizacao", "Em galvanizacao"),
        ("status_galvanizacao", "Situacao"),
        ("obra_site", "Obra/Site"),
        ("lote", "Lote"),
    ],
}

# Chave da coluna de status -> area usada por service.area_status_label / status_color.
# Chaves proprias (nao "status_producao" cru) para nao herdar a largura da
# coluna de status das telas de proposta, que precisa ser bem mais larga.
AREA_STATUS_COLUMN_MAP = {
    "status_producao_item": "PRODUCAO",
    "status_galvanizacao": "GALVANIZACAO",
}

WEIGHT_COLUMNS = {"peso_total"}
NUMERIC_COLUMNS = {"quantidade", "quantidade_disponivel", "quantidade_em_galvanizacao"}


class ItemTableModel(QAbstractTableModel):
    """Tabela por item (não por proposta) — porte enxuto de ProcessTableModel
    para as novas abas de Itens em Produção/Galvanização."""

    def __init__(self, service, area: str, rows: list[dict[str, Any]] | None = None):
        super().__init__()
        self.service = service
        self.area = area
        self.columns = AREA_ITEM_COLUMNS[area]
        self.rows = rows or []
        self._base_columns = list(self.columns)
        self.batch_selection: BatchSelectionController | None = None

    def set_batch_selection_controller(self, controller: BatchSelectionController) -> None:
        self.batch_selection = controller
        controller.selection_changed.connect(self._batch_selection_changed)

    def set_batch_selection_mode(self, active: bool) -> None:
        expected = [("batch_select", "")] + self._base_columns if active else list(self._base_columns)
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
        item_id = int(row.get("id") or 0)
        if key == "batch_select":
            if role == Qt.CheckStateRole:
                return Qt.Checked if self.batch_selection and self.batch_selection.is_selected(item_id) else Qt.Unchecked
            if role in (Qt.DisplayRole, Qt.EditRole):
                return ""
        if role == Qt.UserRole:
            return row
        if role == Qt.UserRole + 1:
            return key
        if role == Qt.UserRole + 2:
            return row.get(key, "")
        if role == Qt.UserRole + 3:
            return AREA_STATUS_COLUMN_MAP.get(key, "")
        if role in (Qt.DisplayRole, Qt.EditRole):
            return self._display_text(key, row)
        if role == Qt.ToolTipRole:
            return self._display_text(key, row)
        if role == Qt.BackgroundRole and self.batch_selection and self.batch_selection.active and self.batch_selection.is_selected(item_id):
            return QBrush(QColor(self.service.palette.get("tree_selected", self.service.palette.get("surface_alt"))))
        if role == Qt.TextAlignmentRole:
            if key in NUMERIC_COLUMNS or key in WEIGHT_COLUMNS:
                return Qt.AlignCenter
            return Qt.AlignVCenter | Qt.AlignLeft
        return None

    def _display_text(self, key: str, row: dict[str, Any]) -> str:
        area = AREA_STATUS_COLUMN_MAP.get(key)
        if area:
            return self.service.area_status_label(area, row.get(key) or "") or "-"
        if key in WEIGHT_COLUMNS:
            value = row.get(key)
            return f"{value} kg" if value not in (None, "") else "-"
        return self.service.display_cell(key, row.get(key), row)

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.columns[section][1]
        return section + 1

    def flags(self, index: QModelIndex):
        flags = super().flags(index)
        if index.isValid() and self.columns[index.column()][0] == "batch_select":
            return flags | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return flags

    def setData(self, index: QModelIndex, value, role=Qt.EditRole):
        if index.isValid() and role == Qt.CheckStateRole and self.columns[index.column()][0] == "batch_select" and self.batch_selection:
            item_id = self.process_id_at(index.row())
            if item_id:
                check_value = getattr(value, "value", value)
                if check_value == Qt.CheckState.Checked.value:
                    self.batch_selection.select(item_id, self.rows[index.row()])
                else:
                    self.batch_selection.deselect(item_id)
                return True
        return False

    def _batch_selection_changed(self) -> None:
        if not self.batch_selection:
            return
        if not self.rows or not self.columns:
            return
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self.rows) - 1, len(self.columns) - 1),
            [Qt.CheckStateRole, Qt.BackgroundRole],
        )

    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder):
        key, _label = self.columns[column]
        reverse = order == Qt.DescendingOrder
        self.layoutAboutToBeChanged.emit()
        self.rows.sort(key=lambda row: str(row.get(key) or "").lower(), reverse=reverse)
        self.layoutChanged.emit()

    def process_id_at(self, row: int) -> int | None:
        """Mesma interface que ModernTable já espera (ProcessTableModel.process_id_at)
        — aqui devolve o id do ITEM (não da proposta); proposal_id/proposal_version
        ficam disponíveis via o dict completo em Qt.UserRole."""
        if row < 0 or row >= len(self.rows):
            return None
        item_id = self.rows[row].get("id")
        return int(item_id) if item_id else None

    def item_row_at(self, row: int) -> dict[str, Any] | None:
        if row < 0 or row >= len(self.rows):
            return None
        return self.rows[row]
