from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLayout, QSizePolicy

from app.ui.components.area_identity import style_area_header
from app.ui.components.operational_layout import OPERATIONAL_HEADER_MARGINS, OPERATIONAL_HEADER_SPACING


def configure_operational_header(
    frame: QFrame,
    layout: QLayout | None = None,
    *,
    margins: tuple[int, int, int, int] = OPERATIONAL_HEADER_MARGINS,
    spacing: int = OPERATIONAL_HEADER_SPACING,
    area: str | None = None,
    palette: dict | None = None,
) -> QFrame:
    frame.setObjectName("OperationalHeader")
    frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    if layout is not None:
        layout.setContentsMargins(*margins)
        layout.setSpacing(spacing)
    if area and palette:
        style_area_header(frame, area, palette)
    return frame
