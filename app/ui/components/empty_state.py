from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.ui.icons import make_icon


class EmptyState(QWidget):
    def __init__(self, title: str, description: str, palette: dict, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(7)
        icon = QLabel()
        icon.setPixmap(make_icon("chart", palette["muted"], 34).pixmap(34, 34))
        icon.setAlignment(Qt.AlignCenter)
        heading = QLabel(title)
        heading.setAlignment(Qt.AlignCenter)
        heading.setStyleSheet("font-weight: 800;")
        caption = QLabel(description)
        caption.setAlignment(Qt.AlignCenter)
        caption.setWordWrap(True)
        caption.setStyleSheet(f"color: {palette['muted']}; font-size: 10px;")
        layout.addWidget(icon)
        layout.addWidget(heading)
        layout.addWidget(caption)
