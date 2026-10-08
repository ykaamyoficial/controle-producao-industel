from __future__ import annotations

from decimal import Decimal

from PySide6.QtGui import QColor

from app.ui.components.status_badge import StatusBadge, area_badge
from app.ui.numeric_utils import format_decimal
from app.ui.theme_tokens import active_tokens

# Cobertura de um item do pedido -> (texto do selo, token de cor).
COVERAGE_KINDS = {
    "COMPLETO": ("Completo", "success"),
    "PARCIAL": ("Parcial", "warning"),
    "SEM_ORIGEM": ("Sem origem escolhida", "muted"),
    "SEM_MATERIAL": ("Sem material pronto", "danger"),
    "INVALIDO": ("Inválido", "danger"),
}

# Status do item na revisao (API) -> tipo de selo.
REVIEW_STATUS_KINDS = {"COMPLETO": "COMPLETO", "PARCIAL": "PARCIAL", "NAO_ALOCADO": "SEM_ORIGEM", "INVALIDO": "INVALIDO"}


def coverage_kind(requested: Decimal, allocated: Decimal, has_candidates: bool) -> str:
    if not has_candidates:
        return "SEM_MATERIAL"
    if allocated <= 0:
        return "SEM_ORIGEM"
    return "COMPLETO" if allocated >= requested else "PARCIAL"


def coverage_badge(kind: str) -> StatusBadge:
    text, token = COVERAGE_KINDS[kind]
    return area_badge(text, active_tokens()[token])


def set_coverage_badge(badge: StatusBadge, kind: str) -> None:
    from app.ui.styles import _contrast_text

    text, token = COVERAGE_KINDS[kind]
    color = active_tokens()[token]
    badge.setText(text)
    badge.set_colors(color, _contrast_text(color))


def quantity_text(value, unit: str | None = "") -> str:
    return f"{format_decimal(value)} {unit or ''}".strip()


def mark_editable(cell) -> None:
    """Celula digitavel de quantidade: texto em negrito na cor de destaque
    (o fundo da celula e pintado pela zebra da tabela, entao nao serve)."""
    cell.setForeground(QColor(active_tokens()["accent"]))
    font = cell.font()
    font.setBold(True)
    cell.setFont(font)
