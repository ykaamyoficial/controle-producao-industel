from __future__ import annotations

from PySide6.QtWidgets import QAbstractItemView, QFrame, QSizePolicy


def configure_operational_table(table: QAbstractItemView) -> QAbstractItemView:
    table.setObjectName("OperationalTable")
    table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    table.setFrameShape(QFrame.NoFrame)
    return table
