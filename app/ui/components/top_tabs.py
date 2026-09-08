from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTabWidget

from app.ui.components.operational_layout import (
    OPERATIONAL_TAB_GAP,
    OPERATIONAL_TAB_HORIZONTAL_PADDING,
    OPERATIONAL_TAB_MIN_HEIGHT,
    OPERATIONAL_TAB_VERTICAL_PADDING_BOTTOM,
    OPERATIONAL_TAB_VERTICAL_PADDING_TOP,
)
from app.ui.styles import area_color


def style_operational_tab_bar(tab_bar, area: str | None, palette: dict | None) -> None:
    if area and palette:
        accent = area_color(area, palette)
        bg = palette.get("bg", "transparent")
        surface_alt = palette.get("surface_alt", bg)
        text = palette.get("text", "#111827")
        muted = palette.get("muted", text)
        border = palette.get("border", accent)
        tab_bar.setProperty("areaKey", str(area or "").strip().upper())
        tab_bar.setProperty("areaAccent", accent)
        tab_bar.setStyleSheet(
            "QTabBar#OperationalTabBar {"
            f"background: {bg};"
            "border: 0;"
            f"border-bottom: 1px solid {border};"
            f"min-height: {OPERATIONAL_TAB_MIN_HEIGHT}px;"
            "}"
            "QTabBar#OperationalTabBar::tab {"
            f"background: {bg};"
            f"color: {muted};"
            "border: 0;"
            "border-radius: 0;"
            "border-bottom: 2px solid transparent;"
            f"padding: {OPERATIONAL_TAB_VERTICAL_PADDING_TOP}px {OPERATIONAL_TAB_HORIZONTAL_PADDING}px "
            f"{OPERATIONAL_TAB_VERTICAL_PADDING_BOTTOM}px {OPERATIONAL_TAB_HORIZONTAL_PADDING}px;"
            f"margin: 0 {OPERATIONAL_TAB_GAP}px 0 0;"
            "font-weight: 600;"
            "}"
            "QTabBar#OperationalTabBar::tab:selected {"
            f"background: {bg};"
            f"color: {text};"
            "border: 0;"
            f"border-bottom: 2px solid {accent};"
            "font-weight: 800;"
            "}"
            "QTabBar#OperationalTabBar::tab:hover:!selected {"
            f"background: {surface_alt};"
            f"color: {text};"
            f"border-bottom: 2px solid {border};"
            "}"
            "QTabBar#OperationalTabBar::tab:disabled {"
            f"background: {bg};"
            f"color: {muted};"
            "border-bottom: 2px solid transparent;"
            "}"
        )


def configure_operational_tabs(tabs: QTabWidget, area: str | None = None, palette: dict | None = None) -> QTabWidget:
    tabs.setObjectName("OperationalTabs")
    tabs.setDocumentMode(True)
    tabs.setUsesScrollButtons(True)

    tab_bar = tabs.tabBar()
    tab_bar.setObjectName("OperationalTabBar")
    tab_bar.setDrawBase(False)
    tab_bar.setExpanding(False)
    tab_bar.setElideMode(Qt.ElideRight)
    tab_bar.setMinimumHeight(OPERATIONAL_TAB_MIN_HEIGHT)
    style_operational_tab_bar(tab_bar, area, palette)
    return tabs
