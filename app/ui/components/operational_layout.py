from __future__ import annotations

from PySide6.QtWidgets import QLayout, QVBoxLayout, QWidget


OPERATIONAL_PAGE_MARGINS = (0, 0, 0, 0)
OPERATIONAL_PAGE_SPACING = 10
OPERATIONAL_SECTION_SPACING = 12
OPERATIONAL_HEADER_MARGINS = (16, 12, 16, 10)
OPERATIONAL_HEADER_SPACING = 8
OPERATIONAL_ACTION_SPACING = 8
OPERATIONAL_FIELD_HORIZONTAL_SPACING = 10
OPERATIONAL_FIELD_VERTICAL_SPACING = 6
OPERATIONAL_TABLE_STACK_MARGINS = (0, 0, 0, 0)
OPERATIONAL_TAB_HORIZONTAL_PADDING = 7
OPERATIONAL_TAB_VERTICAL_PADDING_TOP = 5
OPERATIONAL_TAB_VERTICAL_PADDING_BOTTOM = 4
OPERATIONAL_TAB_MIN_HEIGHT = 28
OPERATIONAL_TAB_GAP = 3
OPERATIONAL_AREA_ACCENT_WIDTH = 9


def configure_operational_page_layout(layout: QVBoxLayout | QLayout, *, spacing: int = OPERATIONAL_PAGE_SPACING) -> QLayout:
    layout.setContentsMargins(*OPERATIONAL_PAGE_MARGINS)
    layout.setSpacing(spacing)
    return layout


def configure_operational_page(widget: QWidget, *, spacing: int = OPERATIONAL_PAGE_SPACING) -> QVBoxLayout:
    layout = QVBoxLayout(widget)
    configure_operational_page_layout(layout, spacing=spacing)
    return layout
