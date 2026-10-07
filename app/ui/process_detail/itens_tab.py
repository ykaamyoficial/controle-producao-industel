from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from app.ui.components.badge_delegate import BadgeColumnDelegate, set_status_badge
from app.ui.components.detail_widgets import clear_panel, make_panel, stat_block
from app.ui.format_utils import format_quantity, format_weight_or_missing
from app.ui.numeric_utils import format_decimal, parse_decimal
from app.ui.table_utils import configure_wrapping_table, item_product_code, resize_rows_to_contents

_STAGE_COLUMN = 5
# Estagio do item -> status cuja cor o selo usa (so apresentacao).
_STAGE_STATUS = {
    "Entregue": "ENTREGUE",
    "Fluxo não definido": "",
    "Não será produzido": "",
    "Em produção": "EM_PRODUCAO",
    "Galvanizado - aguardando expedição": "EM_EXPEDICAO",
    "Enviado para galvanização": "EM_GALVANIZACAO",
    "Produzido - disponível para galvanização": "EM_GALVANIZACAO",
    "Produzido - aguardando expedição": "EM_EXPEDICAO",
}


class ItensTab(QWidget):
    """Aba "Itens": resumo em numeros + tabela de itens (sem selecao/menu/
    acoes proprias - este dialogo nunca teve isso). Processo/Produzido/
    Galvanizado/Entregue ficam numa unica coluna "Situacao", como selo."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.summary_panel, _ = make_panel()
        layout.addWidget(self.summary_panel)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Item", "Código", "Descrição", "Qtd.", "Peso unit.", "Situação"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        for col, width in enumerate((70, 110, 320, 80, 120, 300)):
            self.table.setColumnWidth(col, width)
        self.table.setItemDelegateForColumn(_STAGE_COLUMN, BadgeColumnDelegate(self.table))
        configure_wrapping_table(self.table, description_columns=(2,), code_columns=(1,), min_row_height=42)
        # A linha cresce com a descricao, mas nunca fica menor que o padrao.
        self.table.verticalHeader().setMinimumSectionSize(40)
        layout.addWidget(self.table, 1)

    def load(self, process_ids: list[int], processes: list[dict[str, Any]] | None = None):
        items: list[dict[str, Any]] = []
        seen_item_ids: set[int] = set()
        for process_id in process_ids:
            for item in self.service.proposal_items(process_id):
                item_id = int(item.get("id") or 0)
                if item_id and item_id in seen_item_ids:
                    continue
                if item_id:
                    seen_item_ids.add(item_id)
                items.append(item)
        self.table.setRowCount(len(items))
        total_units = sum((parse_decimal(item.get("quantidade"), "1") for item in items), Decimal("0"))
        weighted_items = [item for item in items if parse_decimal(item.get("peso"), "0") > 0]
        total_weight = sum(
            (parse_decimal(item.get("quantidade"), "1") * parse_decimal(item.get("peso"), "0") for item in weighted_items),
            Decimal("0"),
        )
        self._load_summary(len(items), total_units, total_weight, len(weighted_items))
        # Os nomes de proposta ja foram buscados pelo dialogo pai (um get_process_dict
        # por process_id, ja necessario para o cabecalho) - reusa esses dados aqui em
        # vez de refazer uma chamada de rede (process_partials, que dispara busca +
        # get_proposal completos) por process_id so para montar este dicionario.
        process_names: dict[Any, str] = {}
        if len(process_ids) > 1 and processes:
            process_names.update({process.get("id"): process.get("proposta") for process in processes if process})
        for row, item in enumerate(items):
            stage = self._current_stage(item)
            values = [
                item.get("numero_item"),
                item_product_code(item),
                item.get("descricao"),
                format_quantity(item.get("quantidade") or 1),
                format_weight_or_missing(item.get("peso")),
                self._situacao_text(item, process_names),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                if col == 2:
                    cell.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                elif col in (3, 4):
                    cell.setTextAlignment(Qt.AlignVCenter | Qt.AlignRight)
                else:
                    cell.setTextAlignment(Qt.AlignCenter if col == 0 else Qt.AlignVCenter | Qt.AlignLeft)
                if col == _STAGE_COLUMN:
                    set_status_badge(cell, _STAGE_STATUS.get(stage, ""), self.service.palette)
                self.table.setItem(row, col, cell)
        resize_rows_to_contents(self.table)
        return len(items)

    def _load_summary(self, lines: int, units: Decimal, weight: Decimal, weighted: int) -> None:
        clear_panel(self.summary_panel, keep=0)
        row = QHBoxLayout()
        row.setSpacing(44)
        row.addLayout(stat_block(str(lines), "linha" if lines == 1 else "linhas"))
        row.addLayout(stat_block(format_decimal(units), "unidades"))
        row.addLayout(stat_block(f"{format_decimal(weight)} kg" if weighted else "—", "peso conhecido"))
        row.addLayout(stat_block(f"{weighted}/{lines}", "itens com peso informado"))
        row.addStretch(1)
        self.summary_panel.layout().addLayout(row)

    @staticmethod
    def _situacao_text(item: dict[str, Any], process_names: dict[Any, str]) -> str:
        parts = []
        process_name = process_names.get(item.get("processo_atual_id"))
        if process_name:
            parts.append(f"Processo: {process_name}")
        parts.append(ItensTab._current_stage(item))
        return " | ".join(parts)

    @staticmethod
    def _current_stage(item: dict[str, Any]) -> str:
        """Rotulo unico com o estagio atual do item, em vez do checklist bruto
        Produzido/Galvanizado/Entregue - reflete o proximo passo esperado."""
        produzir = str(item.get("produzir_internamente") or "indefinido").strip().lower()
        precisa_galvanizacao = str(item.get("precisa_galvanizacao") or "indefinido").strip().lower()
        produzido = bool(item.get("produzido"))
        galvanizado = bool(item.get("galvanizado"))
        enviado_galvanizacao = bool(item.get("enviado_galvanizacao"))
        entregue = bool(item.get("entregue"))

        if entregue:
            return "Entregue"
        if produzir == "indefinido":
            return "Fluxo não definido"
        if produzir == "nao":
            return "Não será produzido"
        if not produzido:
            return "Em produção"
        if precisa_galvanizacao == "sim":
            if galvanizado:
                return "Galvanizado - aguardando expedição"
            if enviado_galvanizacao:
                return "Enviado para galvanização"
            return "Produzido - disponível para galvanização"
        return "Produzido - aguardando expedição"
