from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from app.models.fiscal_table_model import fiscal_status_label, format_weight


FISCAL_REPORT_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "PENDENTES": [
        ("proposta", "Proposta"), ("cliente", "Cliente"), ("obra_site", "Obra/Site"),
        ("status_fiscal", "Status fiscal"), ("data_entrada_fiscal", "Entrada fiscal"),
        ("data_ultima_emissao", "Ultima emissao"), ("quantidade_itens", "Itens"),
        ("itens_pendentes", "Pendentes"), ("peso_pendente", "Peso pendente"),
        ("alerta", "Alerta"), ("acoes", "Acoes"),
    ],
    "PARCIAIS": [],
    "EMITIDAS": [],
    "CRITICAS": [],
    "ENTREGUES_SEM_NF": [],
    "MAIS_7_DIAS": [],
    "ITENS_PENDENTES": [
        ("proposta", "Proposta"), ("cliente", "Cliente"), ("obra_site", "Obra/Site"),
        ("status_fiscal", "Status fiscal"), ("data_entrada_fiscal", "Entrada fiscal"),
        ("numero_item", "Item"), ("codigo_produto", "Codigo"), ("descricao", "Descricao"),
        ("quantidade_total", "Qtd. total"), ("quantidade_faturada", "Qtd. faturada"),
        ("quantidade_pendente", "Qtd. pendente"), ("peso_total", "Peso total"),
        ("peso_faturado", "Peso faturado"), ("peso_pendente", "Peso pendente"),
        ("status_item_fiscal", "Status item"), ("acoes", "Acoes"),
    ],
    "EMISSOES": [
        ("proposta", "Proposta"), ("cliente", "Cliente"), ("obra_site", "Obra/Site"),
        ("status_fiscal", "Status fiscal"), ("data_entrada_fiscal", "Entrada fiscal"),
        ("data_emissao", "Data emissao"), ("numero_controle", "NF/Controle"),
        ("tipo_emissao", "Tipo"), ("usuario", "Usuario"), ("observacao", "Observacao"),
        ("quantidade_itens", "Itens"), ("quantidade_emitida", "Qtd. emitida"),
        ("peso_emitido", "Peso emitido"), ("acoes", "Acoes"),
    ],
    "POR_CLIENTE": [
        ("cliente", "Cliente"), ("propostas", "Propostas"), ("falta_emitir", "Falta emitir"),
        ("nf_parcial", "NF parcial"), ("nf_emitida", "NF emitida"),
        ("peso_total", "Peso total"), ("peso_faturado", "Peso faturado"),
        ("peso_pendente", "Peso pendente"),
    ],
    "POR_PERIODO": [
        ("periodo", "Periodo"), ("propostas", "Propostas"), ("falta_emitir", "Falta emitir"),
        ("nf_parcial", "NF parcial"), ("nf_emitida", "NF emitida"),
        ("peso_total", "Peso total"), ("peso_faturado", "Peso faturado"),
        ("peso_pendente", "Peso pendente"),
    ],
}

for alias in ("PARCIAIS", "EMITIDAS", "CRITICAS", "ENTREGUES_SEM_NF", "MAIS_7_DIAS"):
    FISCAL_REPORT_COLUMNS[alias] = list(FISCAL_REPORT_COLUMNS["PENDENTES"])


class FiscalReportTableModel(QAbstractTableModel):
    def __init__(self, report_type: str = "PENDENTES", rows: list[dict[str, Any]] | None = None):
        super().__init__()
        self.report_type = report_type
        self.columns = FISCAL_REPORT_COLUMNS[report_type]
        self.rows = rows or []

    def set_report(self, report_type: str, rows: list[dict[str, Any]]):
        self.beginResetModel()
        self.report_type = report_type
        self.columns = FISCAL_REPORT_COLUMNS[report_type]
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
                return "..." if row.get("fiscal_processo_id") else "-"
            if key in ("status_fiscal", "status_item_fiscal"):
                return fiscal_status_label(str(value or ""))
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
            return row.get("status_fiscal") if key == "status_fiscal" else value
        if role == Qt.UserRole + 3:
            return "FISCAL"
        if role == Qt.TextAlignmentRole:
            if key.startswith("peso_") or key.startswith("quantidade") or key in {
                "propostas", "falta_emitir", "nf_parcial", "nf_emitida", "itens_pendentes",
            }:
                return Qt.AlignVCenter | Qt.AlignRight
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
