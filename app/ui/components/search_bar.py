from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit

from app.ui.icons import make_icon


class SearchBar(QFrame):
    def __init__(self, placeholder: str = "Pesquisar", parent=None):
        super().__init__(parent)
        self.setObjectName("FilterBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(make_icon("search", "#2563eb", 18).pixmap(18, 18))
        self.input = QLineEdit()
        self.input.setPlaceholderText(placeholder)
        layout.addWidget(icon)
        layout.addWidget(self.input)

    def text(self) -> str:
        return self.input.text()
