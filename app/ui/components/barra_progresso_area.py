from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from app.ui.theme_tokens import dashboard_tokens


class BarraProgressoArea(QWidget):
    clicked = Signal(str)

    def __init__(self, label: str, value: int, total: int, color: str, palette: dict, parent=None):
        super().__init__(parent)
        self.area_label = label
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"Clique para visualizar as propostas de {label}")
        tokens = dashboard_tokens(palette)
        percent = round((value / total) * 100) if total else 0
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 1, 0, 1)
        root.setSpacing(5)
        line = QHBoxLayout()
        name = QLabel(label)
        name.setStyleSheet("font-weight: 700;")
        metric = QLabel(f"{value}  |  {percent}%")
        metric.setStyleSheet(f"color: {tokens['muted']}; font-size: 10px; font-weight: 700;")
        line.addWidget(name)
        line.addStretch()
        line.addWidget(metric)
        bar = QProgressBar()
        bar.setRange(0, max(total, 1))
        bar.setValue(value)
        bar.setTextVisible(False)
        bar.setFixedHeight(9)
        bar.setStyleSheet(
            f"""
            QProgressBar {{ background: {tokens['track']}; border: 0; border-radius: 4px; }}
            QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}
            """
        )
        root.addLayout(line)
        root.addWidget(bar)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.area_label)
        super().mouseReleaseEvent(event)
