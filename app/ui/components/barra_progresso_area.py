from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui.components.detail_widgets import ThinProgressBar


class BarraProgressoArea(QWidget):
    clicked = Signal(str)

    def __init__(self, label: str, value: int, total: int, color: str, palette: dict, parent=None, *, display: str | None = None):
        super().__init__(parent)
        self.area_label = label
        self.setObjectName("AreaBarRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"Clique para visualizar as propostas de {label}")
        percent = round((value / total) * 100) if total else 0
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)
        line = QHBoxLayout()
        name = QLabel(display or label)
        name.setObjectName("ValueLabel")
        metric = QLabel(f"{value}  |  {percent}%")
        metric.setObjectName("KeyLabel")
        line.addWidget(name)
        line.addStretch()
        line.addWidget(metric)
        root.addLayout(line)
        root.addWidget(ThinProgressBar(value / total if total else 0.0, color=color, height=8))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.area_label)
        super().mouseReleaseEvent(event)
