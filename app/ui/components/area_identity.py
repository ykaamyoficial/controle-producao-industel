from __future__ import annotations

from PySide6.QtWidgets import QLabel, QWidget

from app.ui.styles import area_color
from app.ui.theme_tokens import with_alpha


AREA_SUBTITLES = {
    "CONTROLE GERAL": "Visao geral das propostas e liberacoes.",
    "PRODUCAO": "Acompanhe fabricacao, parciais e pendencias.",
    "GALVANIZACAO": "Controle cargas, retornos e propostas na galvanizacao.",
    "EXPEDICAO": "Gerencie separacao, entregas e remanejamentos.",
    "ALMOXARIFADO": "Acompanhe separacao de materiais complementares.",
    "FISCAL": "Acompanhe emissoes, pendencias e retiradas fiscais.",
    "PARCIAIS": "Acompanhe entregas parciais, saldos e pendencias.",
}


def normalize_area_key(area: str | None) -> str:
    return str(area or "").strip().upper()


def area_subtitle(area: str | None) -> str:
    return AREA_SUBTITLES.get(normalize_area_key(area), "Acompanhe propostas e acoes operacionais.")


def apply_area_identity(widget: QWidget, area: str | None, palette: dict) -> QWidget:
    key = normalize_area_key(area)
    color = area_color(key, palette)
    widget.setProperty("areaKey", key)
    widget.setProperty("areaAccent", color)
    return widget


def style_area_header(frame: QWidget, area: str | None, palette: dict) -> QWidget:
    color = area_color(area or "", palette)
    border = palette.get("border", "#cbd5e1")
    background = palette.get("bg", "transparent")
    apply_area_identity(frame, area, palette)
    frame.setStyleSheet(
        "QFrame#OperationalHeader {"
        f"background: {background};"
        "border: 0;"
        f"border-bottom: 1px solid {border};"
        f"border-left: 3px solid {color};"
        "border-radius: 0;"
        "}"
    )
    return frame


def style_area_title(label: QLabel, area: str | None, palette: dict) -> QLabel:
    apply_area_identity(label, area, palette)
    label.setStyleSheet(f"color: {area_color(area or '', palette)};")
    return label


def area_soft_background(area: str | None, palette: dict, alpha: int = 34) -> str:
    return with_alpha(area_color(area or "", palette), alpha)
