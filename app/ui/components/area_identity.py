from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QTabBar, QWidget

from app.ui.components.operational_layout import OPERATIONAL_AREA_ACCENT_WIDTH
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
        f"border-left: {OPERATIONAL_AREA_ACCENT_WIDTH}px solid {color};"
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


def refresh_area_theme(root: QWidget, palette: dict) -> None:
    """Re-apply theme-dependent stylesheets baked in at construction time.

    ``configure_operational_header``/``configure_operational_tabs``/``style_area_title``
    set an explicit ``setStyleSheet`` on their widgets using the palette that was
    current when the page was built. Toggling the theme later (see
    ``MainWindow.apply_theme``) only unpolishes/polishes widgets, which has no
    effect on those explicit stylesheets, so they stay stuck on the old
    (often light) colors. Walk the page tree and reapply them with the given
    palette.
    """
    from app.ui.components.top_tabs import style_operational_tab_bar

    for frame in root.findChildren(QFrame, "OperationalHeader"):
        area = frame.property("areaKey")
        if area:
            style_area_header(frame, area, palette)

    for tab_bar in root.findChildren(QTabBar, "OperationalTabBar"):
        area = tab_bar.property("areaKey")
        if area:
            style_operational_tab_bar(tab_bar, area, palette)

    for label in root.findChildren(QLabel, "FilterTitle"):
        area = label.property("areaKey")
        if area:
            style_area_title(label, area, palette)
