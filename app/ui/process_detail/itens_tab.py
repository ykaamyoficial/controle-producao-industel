from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from app.ui.components.badge_delegate import BadgeColumnDelegate, set_status_badge
from app.ui.components.detail_widgets import clear_panel, make_panel, stat_block
from app.ui.format_utils import format_quantity, format_weight_or_missing
from app.ui.numeric_utils import format_decimal, parse_decimal
from app.ui.table_utils import configure_wrapping_table, item_product_code, resize_rows_to_contents

_STAGE_COLUMN = 5
_COLUMNS = 6

# Modo "familia" (proposta com parciais): onde as pecas estao.
_PLACE_ORDER = ("EXPEDICAO", "GALVANIZACAO", "PRODUCAO", "SEM_FLUXO", "ENTREGUE")
_PLACE_TITLE = {
    "EXPEDICAO": "Expedição",
    "GALVANIZACAO": "Galvanização",
    "PRODUCAO": "Produção",
    "SEM_FLUXO": "Fluxo não definido",
    "ENTREGUE": "Entregue",
}
# (campo da API, grupo, rotulo, status cuja cor o selo usa)
_FAMILY_STAGES = (
    ("ready", "EXPEDICAO", "Pronto - na Expedição", "EM_EXPEDICAO"),
    ("in_galvanization", "GALVANIZACAO", "Na galvanização", "EM_GALVANIZACAO"),
    ("awaiting_galvanization", "GALVANIZACAO", "Aguardando galvanização", "EM_GALVANIZACAO"),
    ("to_produce", "PRODUCAO", "Em produção", "EM_PRODUCAO"),
    ("undefined_flow", "SEM_FLUXO", "Fluxo não definido", ""),
    ("delivered", "ENTREGUE", "Entregue", "ENTREGUE"),
)
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
        # Aviso do filtro por parcial (aparece so quando o usuario clica numa ficha do cabecalho).
        self.filter_note = QLabel("")
        self.filter_note.setObjectName("FilterSubtitle")
        self.filter_note.setVisible(False)
        layout.addWidget(self.filter_note)
        self._family_rows: list[dict[str, Any]] = []
        self._partial_filter: str | None = None
        self._partial_names: dict[str, str] = {}

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

    def load(self, process_ids: list[int], processes: list[dict[str, Any]] | None = None, family: dict[str, Any] | None = None):
        if family and family.get("items"):
            return self._load_family(family)
        self._family_rows = []
        self._partial_filter = None
        self.filter_note.setVisible(False)
        self.table.clearSpans()
        self.table.setRowCount(0)
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

    # ---- proposta com parciais: itens agrupados por onde as pecas estao ------------------------------
    def _load_family(self, family: dict[str, Any]) -> int:
        """Itens de toda a familia (mae + parciais). Cada item aparece uma vez por lugar onde tem pecas
        (ex.: 3 un. na Expedicao e 2 un. em Producao), agrupado por lugar. So apresenta o que a API devolve."""
        entries: dict[str, list[dict[str, Any]]] = {place: [] for place in _PLACE_ORDER}
        totals: dict[str, Decimal] = {place: Decimal("0") for place in _PLACE_ORDER}
        items = family.get("items") or []
        for item in items:
            quantities = item.get("quantities") or {}
            placed = False
            for field, place, label, status in _FAMILY_STAGES:
                qty = parse_decimal(quantities.get(field), "0")
                if qty <= 0:
                    continue
                placed = True
                totals[place] += qty
                entries[place].append({"item": item, "qty": qty, "label": label, "status": status})
            if not placed:
                qty = parse_decimal(item.get("quantity"), "0")
                totals["SEM_FLUXO"] += qty
                entries["SEM_FLUXO"].append({"item": item, "qty": qty, "label": "Fluxo não definido", "status": ""})

        self._partial_names = {
            str(p.get("key")): (f"{p.get('label')} · {p.get('proposal_number')}" if p.get("proposal_number") else str(p.get("label") or ""))
            for p in family.get("partials") or []
        }
        self._partial_names.update({f"P:{m.get('proposal_id')}": str(m.get("proposal_number") or "") for m in family.get("members") or []})
        weighted = [item for item in items if parse_decimal(item.get("unit_weight"), "0") > 0]
        total_units = sum((parse_decimal(item.get("quantity"), "0") for item in items), Decimal("0"))
        known_weight = sum(
            (parse_decimal(item.get("quantity"), "0") * parse_decimal(item.get("unit_weight"), "0") for item in weighted), Decimal("0")
        )
        self._load_family_summary(len(items), total_units, totals, known_weight, len(weighted))

        self.table.clearSpans()
        self.table.setRowCount(0)
        self._family_rows = []
        group_font = QFont(self.table.font())
        group_font.setBold(True)
        group_brush = QBrush(QColor(self.service.palette.get("surface_alt", "#e8f1ff")))
        for place in _PLACE_ORDER:
            rows = entries[place]
            if not rows:
                continue
            header_row = self.table.rowCount()
            self.table.insertRow(header_row)
            self.table.setSpan(header_row, 0, 1, _COLUMNS)
            header = QTableWidgetItem(f"{_PLACE_TITLE[place]} · {format_decimal(totals[place])} un.")
            header.setFont(group_font)
            header.setBackground(group_brush)
            header.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(header_row, 0, header)
            self._family_rows.append({"kind": "group", "row": header_row, "partials": []})
            for entry in rows:
                item = entry["item"]
                row = self.table.rowCount()
                self.table.insertRow(row)
                partial_text = str(item.get("partial_label") or "")
                values = [
                    item.get("item_number"),
                    item.get("product_code"),
                    item.get("description"),
                    format_decimal(entry["qty"]),
                    format_weight_or_missing(item.get("unit_weight")),
                    f"{partial_text} | {entry['label']}" if partial_text else entry["label"],
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
                        set_status_badge(cell, entry["status"], self.service.palette)
                    self.table.setItem(row, col, cell)
                keys = list(item.get("partial_keys") or [])
                if not keys and item.get("proposal_id"):
                    keys = [f"P:{item.get('proposal_id')}"]  # API anterior as `partials`
                self._family_rows.append({"kind": "item", "row": row, "partials": keys})
        resize_rows_to_contents(self.table)
        self._partial_filter = None
        self.filter_note.setVisible(False)
        return len(items)

    def _load_family_summary(self, lines: int, units: Decimal, totals: dict[str, Decimal], weight: Decimal, weighted: int) -> None:
        clear_panel(self.summary_panel, keep=0)
        row = QHBoxLayout()
        row.setSpacing(44)
        row.addLayout(stat_block(str(lines), "linha" if lines == 1 else "linhas"))
        row.addLayout(stat_block(format_decimal(units), "unidades"))
        for place in _PLACE_ORDER:
            if totals[place] > 0:
                row.addLayout(stat_block(format_decimal(totals[place]), _PLACE_TITLE[place].lower()))
        row.addLayout(stat_block(f"{format_decimal(weight)} kg" if weighted else "—", "peso conhecido"))
        row.addStretch(1)
        self.summary_panel.layout().addLayout(row)

    def set_partial_filter(self, key: str | None) -> None:
        """Mostra so os itens de uma parcial (clicar de novo na mesma ficha limpa o filtro)."""
        self.show_partial(None if key == self._partial_filter else key)

    def visible_item_count(self) -> int:
        """Quantidade de itens (linhas de item, sem os titulos de grupo) visiveis com o filtro atual."""
        if not self._family_rows:
            return self.table.rowCount()
        distinct = set()
        for meta in self._family_rows:
            if meta["kind"] == "item" and not self.table.isRowHidden(meta["row"]):
                item = self.table.item(meta["row"], 0)
                distinct.add(item.text() if item is not None else meta["row"])
        return len(distinct)

    def show_partial(self, key: str | None) -> None:
        """Filtra a tabela pela parcial `key` (None mostra tudo)."""
        if not self._family_rows:
            return
        self._partial_filter = key or None
        visible_groups: dict[int, bool] = {}
        current_group = None
        for meta in self._family_rows:
            if meta["kind"] == "group":
                current_group = meta["row"]
                visible_groups[current_group] = False
                continue
            show = self._partial_filter is None or self._partial_filter in meta["partials"]
            self.table.setRowHidden(meta["row"], not show)
            if show and current_group is not None:
                visible_groups[current_group] = True
        for group_row, visible in visible_groups.items():
            self.table.setRowHidden(group_row, not visible)
        if self._partial_filter is None:
            self.filter_note.setVisible(False)
        else:
            name = self._partial_names.get(self._partial_filter, "")
            self.filter_note.setText(f"Mostrando só os itens de {name}. Escolha a proposta principal para ver todos.")
            self.filter_note.setVisible(True)

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
