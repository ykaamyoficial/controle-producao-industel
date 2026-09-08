from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from app.ui.format_utils import format_quantity, format_weight_or_missing
from app.ui.numeric_utils import format_decimal, parse_decimal
from app.ui.table_utils import configure_wrapping_table, item_product_code, resize_rows_to_contents


class ItensTab(QWidget):
    """Aba "Itens": mesma tabela de itens que existia no dialogo antigo (sem
    selecao/menu/acoes proprias - este dialogo nunca teve isso), so com
    "Descricao" com mais espaco e Processo/Produzido/Galvanizado/Entregue
    compactados numa unica coluna "Situacao" tipo checklist, como pedido."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        self.summary = QLabel("0 item(ns)")
        self.summary.setObjectName("Caption")
        layout.addWidget(self.summary)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Item", "Codigo", "Descricao", "Qtd.", "Peso unit.", "Situacao"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        for col, width in enumerate((70, 100, 320, 70, 100, 190)):
            self.table.setColumnWidth(col, width)
        configure_wrapping_table(self.table, description_columns=(2,), code_columns=(1,), min_row_height=42)
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
        weight_label = f"{format_decimal(total_weight)} kg conhecidos" if weighted_items else "peso nao informado"
        self.summary.setText(
            f"{len(items)} linha(s) | {format_decimal(total_units)} unidade(s) | {weight_label} | "
            f"cobertura {len(weighted_items)}/{len(items)}"
        )
        # Os nomes de proposta ja foram buscados pelo dialogo pai (um get_process_dict
        # por process_id, ja necessario para o cabecalho) - reusa esses dados aqui em
        # vez de refazer uma chamada de rede (process_partials, que dispara busca +
        # get_proposal completos) por process_id so para montar este dicionario.
        process_names: dict[Any, str] = {}
        if len(process_ids) > 1 and processes:
            process_names.update({process.get("id"): process.get("proposta") for process in processes if process})
        for row, item in enumerate(items):
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
                cell.setTextAlignment(Qt.AlignTop | Qt.AlignLeft if col == 2 else Qt.AlignCenter)
                self.table.setItem(row, col, cell)
        resize_rows_to_contents(self.table)
        visible_rows = min(max(len(items), 2), 8)
        self.table.setMinimumHeight(68 + visible_rows * 46)

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
            return "Fluxo nao definido"
        if produzir == "nao":
            return "Nao sera produzido"
        if not produzido:
            return "Em producao"
        if precisa_galvanizacao == "sim":
            if galvanizado:
                return "Galvanizado - aguardando expedicao"
            if enviado_galvanizacao:
                return "Enviado para galvanizacao"
            return "Produzido - disponivel para galvanizacao"
        return "Produzido - aguardando expedicao"
