from __future__ import annotations

from decimal import Decimal
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui.components.detail_widgets import ThinProgressBar
from app.ui.components.status_badge import StatusBadge, neutral_badge
from app.ui.components.style_state import set_style_state
from app.ui.numeric_utils import format_decimal, parse_decimal
from app.ui.sidebar import NAV_LABELS
from app.ui.styles import status_color

# Lugar das pecas (devolvido pela API) -> rotulo exibido e status cuja cor o selo usa (so apresentacao).
PLACE_LABEL = {
    "EXPEDICAO": "Expedição",
    "GALVANIZACAO": "Galvanização",
    "PRODUCAO": "Produção",
    "ENTREGUE": "Entregue",
    "SEM_FLUXO": "Fluxo não definido",
}
PLACE_STATUS = {
    "EXPEDICAO": "EM_EXPEDICAO",
    "GALVANIZACAO": "EM_GALVANIZACAO",
    "PRODUCAO": "EM_PRODUCAO",
    "ENTREGUE": "ENTREGUE",
    "SEM_FLUXO": "",
}
# Mista: nenhuma area representa a familia; usa a cor de "parcial/atencao".
MIXED_STATUS = "FINALIZADO_PARCIAL"
_API_AREA_TO_NAV = {"CONTROLE_GERAL": "CONTROLE GERAL"}


def has_partials(family: dict[str, Any] | None) -> bool:
    # Parcial = proposta-filha (`has_partials`) ou lote fisico por lugar (`partials`).
    return bool(family and (family.get("has_partials") or family.get("partials")))


def quantity_text(value: Any) -> str:
    return format_decimal(parse_decimal(value, "0"))


def member_chip_text(member: dict[str, Any], service, *, compact: bool = False) -> str:
    """"CP 05493-1 · Expedição · Separado · 10 un." -- numero da parcial, onde esta e quantas pecas."""
    area = _API_AREA_TO_NAV.get(member.get("current_area") or "", member.get("current_area") or "")
    area_text = NAV_LABELS.get(area, area.title())
    status = member.get("current_status") or ""
    parts = [str(member.get("proposal_number") or member.get("label") or "")]
    if member.get("is_reference"):
        parts.append("referência, sem itens")
    else:
        parts.append(area_text)
        if status and not compact:
            parts.append(service.area_status_label(area, status))
        parts.append(f"{quantity_text(member.get('total_units'))} un.")
    return " · ".join(part for part in parts if part)


def member_chip_colors(member: dict[str, Any], palette: dict) -> tuple[str, str]:
    area = _API_AREA_TO_NAV.get(member.get("current_area") or "", member.get("current_area") or "")
    if member.get("is_reference"):
        return palette.get("surface_alt", "#e2e8f0"), palette.get("text", "#0f172a")
    return status_color(member.get("current_status") or "", palette, area)


def consolidated_badge(family: dict[str, Any], palette: dict) -> tuple[str, tuple[str, str]] | None:
    """Texto e cores do selo principal quando a familia tem parciais; None mantem o selo da linha aberta."""
    if not has_partials(family):
        return None
    consolidated = family.get("consolidated") or {}
    kind = consolidated.get("kind")
    parts = consolidated.get("parts") or []
    if kind == "MIXED":
        places = [part for part in parts if part.get("place") != "ENTREGUE"]
        head = "PARCIAL"
        detail = " · ".join(
            f"{quantity_text(part.get('quantity'))} un. {PLACE_LABEL.get(part.get('place'), '').lower()}" for part in (places or parts)
        )
        return f"{head} · {detail}", status_color(MIXED_STATUS, palette, "")
    if kind == "UNIFORM" and parts:
        place = parts[0].get("place")
        return PLACE_LABEL.get(place, "").upper(), status_color(PLACE_STATUS.get(place, ""), palette, "")
    return None


class _PartialChip(StatusBadge):
    """Selo de uma parcial; clicavel (abre a aba Itens naquela parcial)."""

    clicked = Signal(object)

    def __init__(self, text: str, bg: str, fg: str, key, parent=None):
        super().__init__(text, bg, fg, parent)
        self._key = key
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setToolTip("Mostrar os itens desta parcial")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._key)
        super().mousePressEvent(event)


def partial_card_texts(partial: dict[str, Any], service) -> tuple[str, str, str]:
    """(titulo, status, quantidades) do cartao de uma parcial. Lote fisico nao tem numero de CP proprio."""
    label = str(partial.get("label") or "")
    number = partial.get("proposal_number")
    title = f"{label} · {number}" if number else label
    place = partial.get("place") or ""
    area = _API_AREA_TO_NAV.get(partial.get("current_area") or "", partial.get("current_area") or "")
    area_text = NAV_LABELS.get(area, PLACE_LABEL.get(place, area.title()))
    status = partial.get("current_status") or ""
    status_text = service.area_status_label(area, status) if status else ""
    status_line = f"{area_text} · {status_text}" if status_text else area_text
    items = int(partial.get("item_count") or 0)
    counts = f"{quantity_text(partial.get('total_units'))} un. · {items} {'item' if items == 1 else 'itens'}"
    return title, status_line, counts


def partial_card_colors(partial: dict[str, Any], palette: dict) -> tuple[str, str]:
    area = _API_AREA_TO_NAV.get(partial.get("current_area") or "", partial.get("current_area") or "")
    status = partial.get("current_status") or ""
    if status:
        return status_color(status, palette, area)
    return status_color(PLACE_STATUS.get(partial.get("place") or "", ""), palette, "")


class PartialCard(QFrame):
    """Cartao da proposta principal ou de uma parcial no cabecalho; clicar seleciona (o Detalhe passa a
    mostrar so aquela parcial). Estado "selecionado" por propriedade, estilo em `styles.py`."""

    clicked = Signal(object)

    def __init__(self, key, title: str, status_text: str, counts: str, colors: tuple[str, str], parent=None):
        super().__init__(parent)
        self.key = key
        self.setObjectName("PartialCard")
        self.setProperty("selected", False)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setAccessibleName(f"{title}. {status_text}. {counts}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("PartialCardTitle")
        self.badge = StatusBadge(status_text, colors[0], colors[1])
        self.counts_label = QLabel(counts)
        self.counts_label.setObjectName("KeyLabel")
        layout.addWidget(self.title_label)
        layout.addWidget(self.badge, 0, Qt.AlignLeft)
        layout.addWidget(self.counts_label)

    def set_selected(self, selected: bool) -> None:
        set_style_state(self, selected=bool(selected))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(event)


class FamilyStrip(QWidget):
    """Faixa do cabecalho do Detalhe: uma ficha por parcial (numero, onde esta, status, pecas) e, abaixo,
    progresso de entrega, situacao fiscal, peso e avisos de remanejamento. So apresenta o que a API
    (`GET /proposals/{id}/family`) ja calculou."""

    partial_requested = Signal(object)
    # Chave da parcial escolhida nos cartoes (None = proposta principal, visao geral).
    selection_changed = Signal(object)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.chips: list[_PartialChip] = []
        self.cards: list[PartialCard] = []
        self.selected_key = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        self.chip_row = QHBoxLayout()
        self.chip_row.setSpacing(8)
        self.indicator_row = QHBoxLayout()
        self.indicator_row.setSpacing(16)
        outer.addLayout(self.chip_row)
        outer.addLayout(self.indicator_row)
        self.setVisible(False)

    @staticmethod
    def _clear(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def load(self, family: dict[str, Any] | None) -> None:
        self._clear(self.chip_row)
        self._clear(self.indicator_row)
        self.chips = []
        self.cards = []
        self.selected_key = None
        if family and family.get("partials"):
            self._load_cards(family)
            return
        if not has_partials(family):
            self.setVisible(False)
            return
        palette = self.service.palette
        caption = QLabel("Parciais:")
        caption.setObjectName("KeyLabel")
        self.chip_row.addWidget(caption)
        members = family.get("members") or []
        compact = len(members) > 3  # muitas parciais: ficha sem o status para caber na linha
        for member in members:
            bg, fg = member_chip_colors(member, palette)
            chip = _PartialChip(member_chip_text(member, self.service, compact=compact), bg, fg, member.get("proposal_id"))
            if member.get("is_reference"):
                chip.setToolTip("Proposta mãe: só referência, os itens estão nas parciais")
                chip.setCursor(QCursor(Qt.ArrowCursor))
            else:
                chip.clicked.connect(self.partial_requested)
            self.chips.append(chip)
            self.chip_row.addWidget(chip)
        for label in family.get("remanagement_labels") or []:
            self.chip_row.addWidget(neutral_badge(label, palette))
        self.chip_row.addStretch(1)
        self._load_indicators(family)

    def _load_cards(self, family: dict[str, Any]) -> None:
        """Principal + uma parcial por cartao (filhas ou lotes), no padrao aprovado."""
        palette = self.service.palette
        totals = family.get("totals") or {}
        consolidated = consolidated_badge(family, palette)
        main_title = f"{family.get('root_proposal_number') or ''} · Principal".strip(" ·")
        main_status = consolidated[0].capitalize() if consolidated else str((family.get("consolidated") or {}).get("label") or "")
        main_colors = consolidated[1] if consolidated else status_color("", palette, "")
        units = quantity_text(totals.get("total_units"))
        item_total = len(family.get("items") or [])
        main = PartialCard(None, main_title, main_status, f"{units} un. · {item_total} {'item' if item_total == 1 else 'itens'}", main_colors)
        main.setToolTip("Visão geral: todos os itens da proposta")
        self._add_card(main)
        for partial in family.get("partials") or []:
            title, status_line, counts = partial_card_texts(partial, self.service)
            card = PartialCard(partial.get("key"), title, status_line, counts, partial_card_colors(partial, palette))
            card.setToolTip("Mostrar só esta parcial")
            self._add_card(card)
        for label in family.get("remanagement_labels") or []:
            self.chip_row.addWidget(neutral_badge(label, palette))
        self.chip_row.addStretch(1)
        self.cards[0].set_selected(True)
        self._load_indicators(family)

    def _add_card(self, card: PartialCard) -> None:
        card.clicked.connect(self.select)
        self.cards.append(card)
        self.chip_row.addWidget(card)

    def select(self, key) -> None:
        """Seleciona o cartao (None = principal); avisa o Detalhe so quando a escolha muda."""
        if key == self.selected_key and any(card.property("selected") for card in self.cards):
            return
        self.selected_key = key
        for card in self.cards:
            card.set_selected(card.key == key)
        self.selection_changed.emit(key)

    def _load_indicators(self, family: dict[str, Any]) -> None:
        totals = family.get("totals") or {}
        total = parse_decimal(totals.get("total_units"), "0")
        delivered = parse_decimal(totals.get("delivered_units"), "0")
        percent = int(totals.get("progress_percent") or 0)
        bar = ThinProgressBar(percent / 100.0)
        bar.setFixedWidth(140)
        self.indicator_row.addWidget(self._text(f"Entrega: {format_decimal(delivered)} de {format_decimal(total)} un. ({percent}%)"))
        self.indicator_row.addWidget(bar, 0, Qt.AlignVCenter)
        fiscal = totals.get("fiscal_status")
        self.indicator_row.addWidget(self._text(f"Fiscal: {self.service.fiscal_status_label(fiscal) if fiscal else '—'}"))
        self.indicator_row.addWidget(self._text(self._weight_text(totals)))
        self.indicator_row.addStretch(1)
        self.setVisible(True)

    @staticmethod
    def _weight_text(totals: dict[str, Any]) -> str:
        known = parse_decimal(totals.get("known_weight"), "0")
        if known <= Decimal("0"):
            return "Peso: não informado"
        text = f"Peso: {format_decimal(known)} kg · pendente {format_decimal(parse_decimal(totals.get('pending_weight'), '0'))} kg"
        if not totals.get("weight_complete"):
            text += f" ({totals.get('weight_known_items', 0)}/{totals.get('weight_total_items', 0)} itens com peso)"
        return text

    @staticmethod
    def _text(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("DeadlineText")
        return label
