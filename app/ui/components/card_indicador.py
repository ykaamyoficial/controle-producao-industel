from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QVBoxLayout

from app.ui.icons import make_icon
from app.ui.theme_tokens import dashboard_tokens, with_alpha


class CardIndicador(QFrame):
    clicked = Signal(str)

    def __init__(self, title: str, value: int, icon_name: str, tone: str, palette: dict, parent=None):
        super().__init__(parent)
        self.tokens = dashboard_tokens(palette)
        self.tone = tone
        self.metric_key = title
        self.setObjectName("IndicatorCard")
        self.setMinimumHeight(112)
        self.setCursor(Qt.PointingHandCursor)
        self._apply_style(False)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(14)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(self.tokens["shadow"]))
        self.setGraphicsEffect(shadow)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)
        icon = QLabel()
        icon.setPixmap(make_icon(icon_name, tone, 32).pixmap(32, 32))
        icon.setFixedSize(52, 52)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(f"background: {with_alpha(tone, 30)}; border-radius: 14px;")
        copy = QVBoxLayout()
        copy.setSpacing(1)
        label = QLabel(title)
        label.setStyleSheet(f"color: {self.tokens['muted']}; font-size: 11px; font-weight: 700;")
        label.setWordWrap(True)
        label.setMinimumHeight(28)
        number = QLabel(str(value))
        number.setStyleSheet(f"color: {self.tokens['text']}; font-size: 27px; font-weight: 800;")
        copy.addWidget(label)
        copy.addWidget(number)
        layout.addWidget(icon)
        layout.addLayout(copy, 1)

    def _apply_style(self, hovered: bool):
        background = self.tokens["hover"] if hovered else self.tokens["surface"]
        border = self.tone if hovered else self.tokens["border"]
        self.setStyleSheet(
            f"QFrame#IndicatorCard {{ background: {background}; border: 1px solid {border}; border-radius: 16px; }}"
        )

    def enterEvent(self, event):
        self._apply_style(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply_style(False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.metric_key)
        super().mouseReleaseEvent(event)
