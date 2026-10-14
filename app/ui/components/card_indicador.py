from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from app.ui.components.detail_widgets import IconChip
from app.ui.theme_tokens import dashboard_tokens


class CardIndicador(QFrame):
    """Cartao de indicador do Painel geral. Clicavel (mouse ou Enter/Espaco);
    cor e hover vem da folha de estilo (`IndicatorCard`), sem estilo inline."""

    clicked = Signal(str)

    def __init__(self, title: str, value: int, icon_name: str, tone: str, palette: dict, parent=None):
        super().__init__(parent)
        self.tokens = dashboard_tokens(palette)
        self.tone = tone
        self.metric_key = title
        self.setObjectName("IndicatorCard")
        self.setMinimumHeight(96)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(f"{title}: {value}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)
        copy = QVBoxLayout()
        copy.setSpacing(0)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("IndicatorLabel")
        self.title_label.setWordWrap(True)
        self.number_label = QLabel(str(value))
        self.number_label.setObjectName("IndicatorValue")
        copy.addWidget(self.title_label)
        copy.addWidget(self.number_label)
        layout.addWidget(IconChip(icon_name, tone, size=44), 0, Qt.AlignVCenter)
        layout.addLayout(copy, 1)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.metric_key)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit(self.metric_key)
            return
        super().keyPressEvent(event)
