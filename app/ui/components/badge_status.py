from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QLabel, QSizePolicy

from app.ui.animations import animate_value
from app.ui.styles import _contrast_text
from app.ui.theme_tokens import active_tokens, mix

_HEIGHT = 36
_RADIUS = 10


class BadgeStatus(QLabel):
    """Selo clicavel de prazo ("Vencidos  3"). Solido na cor do status quando ha
    propostas; com contagem zero fica neutro, para o vermelho/laranja nao
    alarmar sem motivo. Pintado a mao: sem estilo inline."""

    clicked = Signal(str)

    def __init__(self, text: str, value: int, color: str, palette: dict, parent=None, *, display: str | None = None):
        # `text` e a chave que o clique devolve; `display` e so o que aparece.
        super().__init__(f"{display or text}  {value}", parent)
        self.badge_key = text
        self.value = value
        self._color = color
        self._hover = 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"Clique para visualizar: {text}")
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(_HEIGHT)

    def _font(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.Bold)
        return font

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        return QSize(int(QFontMetricsF(self._font()).horizontalAdvance(self.text()) + 32), _HEIGHT)

    def enterEvent(self, event):  # noqa: N802
        animate_value(self, "_hover", 1.0, 140)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        animate_value(self, "_hover", 0.0, 140)
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        tokens = active_tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.value > 0:
            background = mix(self._color, tokens["text"], 0.12 * self._hover)
            foreground = _contrast_text(background)
            painter.setPen(Qt.NoPen)
        else:
            background = mix(tokens["surface_alt"], tokens["accent"], 0.10 * self._hover)
            foreground = tokens["muted"]
            painter.setPen(QPen(QColor(tokens["border"]), 1))
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(rect, _RADIUS, _RADIUS)
        painter.setFont(self._font())
        painter.setPen(QColor(foreground))
        painter.drawText(self.rect(), Qt.AlignCenter, self.text())
        painter.end()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.badge_key)
        super().mouseReleaseEvent(event)
