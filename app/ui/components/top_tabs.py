from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTabWidget

from app.ui.styles import area_color


def configure_operational_tabs(tabs: QTabWidget, area: str | None = None, palette: dict | None = None) -> QTabWidget:
    tabs.setObjectName("OperationalTabs")
    tabs.setDocumentMode(True)
    tabs.setUsesScrollButtons(True)

    tab_bar = tabs.tabBar()
    tab_bar.setObjectName("OperationalTabBar")
    tab_bar.setDrawBase(False)
    tab_bar.setExpanding(False)
    tab_bar.setElideMode(Qt.ElideRight)
    tab_bar.setMinimumHeight(44)
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
            "min-height: 44px;"
            "}"
            "QTabBar#OperationalTabBar::tab {"
            f"background: {bg};"
            f"color: {muted};"
            "border: 0;"
            "border-radius: 0;"
            "border-bottom: 3px solid transparent;"
            "padding: 12px 18px 9px 18px;"
            "margin: 0;"
            "font-weight: 600;"
            "}"
            "QTabBar#OperationalTabBar::tab:selected {"
            f"background: {bg};"
            f"color: {text};"
            "border: 0;"
            f"border-bottom: 3px solid {accent};"
            "font-weight: 800;"
            "}"
            "QTabBar#OperationalTabBar::tab:hover:!selected {"
            f"background: {surface_alt};"
            f"color: {text};"
            f"border-bottom: 3px solid {border};"
            "}"
            "QTabBar#OperationalTabBar::tab:disabled {"
            f"background: {bg};"
            f"color: {muted};"
            "border-bottom: 3px solid transparent;"
            "}"
        )
    return tabs
