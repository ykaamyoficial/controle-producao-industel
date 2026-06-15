from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


DEFAULT_COLUMNS = [
    ("status_icon", ""),
    ("id", "ID"),
    ("tipo_processo", "Tipo"),
    ("cliente", "Cliente"),
    ("proposta", "Proposta"),
    ("pedido_compra", "OC/Pedido"),
    ("obra_site", "Obra/Site"),
    ("progresso_peso", "Peso/Saldo"),
    ("lote", "Lote"),
    ("prazo_entrega", "Prazo"),
    ("status_localizacao", "Status"),
    ("localizacao_atual", "Localizacao"),
]


AREA_COLUMNS = {
    "PRODUCAO": [
        ("status_icon", ""),
        ("id", "ID"), ("tipo_processo", "Tipo"), ("cliente", "Cliente"),
        ("proposta", "Proposta"), ("pedido_compra", "OC/Pedido"), ("obra_site", "Obra/Site"),
        ("progresso_peso", "Peso/Saldo"), ("lote", "Lote"), ("data_entrada", "Entrada"),
        ("prazo_entrega", "Prazo"), ("status_producao", "Status producao"),
    ],
    "GALVANIZACAO": [
        ("status_icon", ""),
        ("id", "ID"), ("tipo_processo", "Tipo"), ("cliente", "Cliente"),
        ("proposta", "Proposta"), ("pedido_compra", "OC/Pedido"), ("obra_site", "Obra/Site"),
        ("progresso_peso", "Peso/Saldo"), ("lote", "Lote"), ("carga_galvanizacao", "Carga"), ("data_envio_galv", "Envio Galv."),
        ("data_prevista_retorno_galv", "Prev. Retorno"), ("data_retorno_galv", "Retorno Galv."),
        ("status_galvanizacao", "Status galvanizacao"),
    ],
    "EXPEDICAO": [
        ("status_icon", ""),
        ("id", "ID"), ("tipo_processo", "Tipo"), ("cliente", "Cliente"),
        ("proposta", "Proposta"), ("pedido_compra", "OC/Pedido"), ("obra_site", "Obra/Site"),
        ("progresso_peso", "Peso/Saldo"), ("lote", "Lote"), ("prazo_entrega", "Prazo"),
        ("almoxarifado_info", "Almox."), ("status_expedicao", "Status expedicao"),
    ],
    "ALMOXARIFADO": [
        ("status_icon", ""),
        ("id", "ID"), ("tipo_processo", "Tipo"), ("cliente", "Cliente"),
        ("proposta", "Proposta"), ("pedido_compra", "OC/Pedido"), ("obra_site", "Obra/Site"),
        ("progresso_peso", "Peso/Saldo"), ("lote", "Lote"), ("data_entrada", "Entrada"),
        ("prazo_entrega", "Prazo"), ("necessita_almoxarifado", "Necessita"), ("status_almoxarifado", "Status almoxarifado"),
    ],
}


class ProcessTableModel(QAbstractTableModel):
    def __init__(self, service, area: str | None = None, rows: list[dict[str, Any]] | None = None):
        super().__init__()
        self.service = service
        self.area = area
        self.columns = AREA_COLUMNS.get(area or "", DEFAULT_COLUMNS)
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
            if key == "status_icon":
                area, _label, status = self.service.current_location(row)
                return status
            if key == "status_localizacao":
                return self.service.current_location(row)[2]
            if key == "localizacao_atual":
                return self.service.current_location(row)[0]
            return row.get(key, "")
        if role == Qt.UserRole + 3:
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
            if key == "status_icon":
                return ""
            return self.service.display_cell(key, row.get(key), row)
        if role == Qt.ToolTipRole:
            if key == "status_icon":
                return "Abrir acoes da proposta"
            return self.data(index, Qt.DisplayRole)
        if role == Qt.TextAlignmentRole:
            if key in {"id", "peso", "peso_parcial", "saldo_pendente"}:
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
        if row < 0 or row >= len(self.rows):
            return None
        return int(self.rows[row]["id"])
