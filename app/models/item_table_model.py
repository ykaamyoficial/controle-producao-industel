from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


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
