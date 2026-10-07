from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QPushButton

from app.ui.animations import animate_value
from app.ui.components.count_badge import format_count_badge
from app.ui.icons import make_icon
from app.ui.styles import _contrast_text
from app.ui.theme_tokens import active_tokens, mix

_SIZE = 56
_ICON_SIZE = 24


class FloatingChatButton(QPushButton):
    """Botao redondo de chat no canto da janela. Pintado a mao: o contador de
    nao lidas e uma bolha sobreposta (nunca via setText), o circulo cresce de
    leve no hover e ha anel de foco pelo teclado."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._badge_count = 0
        self._hover = 0.0
        self.setObjectName("AccentButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(_SIZE, _SIZE)
        self.setAccessibleName("Chats")
        self.set_unread_count(0)

    def set_unread_count(self, count: int):
        self._badge_count = max(0, int(count))
        self.setToolTip(f"{count} mensagem(ns) não lida(s)" if count else "Abrir chats")
        self.setAccessibleDescription(self.toolTip())
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802 (Qt override)
        animate_value(self, "_hover", 1.0, 160)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        animate_value(self, "_hover", 0.0, 200)
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        tokens = active_tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        center = QPointF(self.width() / 2, self.height() / 2)
        radius = 23 + 3 * self._hover
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(mix(tokens["accent"], tokens["accent_hover"], self._hover)))
        painter.drawEllipse(center, radius, radius)
        if self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(tokens["ring"]), 2))
            painter.drawEllipse(center, 27, 27)
        pixmap = make_icon("chat", tokens["accent_text"], _ICON_SIZE).pixmap(_ICON_SIZE, _ICON_SIZE)
        painter.drawPixmap(
            QRectF(center.x() - _ICON_SIZE / 2, center.y() - _ICON_SIZE / 2, _ICON_SIZE, _ICON_SIZE),
            pixmap,
            QRectF(pixmap.rect()),
        )
        text = format_count_badge(self._badge_count)
        if text:
            font = QFont(self.font())
            font.setPixelSize(11)
            font.setWeight(QFont.Weight.Bold)
            width = max(20.0, QFontMetricsF(font).horizontalAdvance(text) + 10)
            bubble = QRectF(self.width() - width - 1, 1, width, 20)
            painter.setPen(QPen(QColor(tokens["bg"]), 2))
            painter.setBrush(QColor(tokens["danger"]))
            painter.drawRoundedRect(bubble, 10, 10)
            painter.setFont(font)
            painter.setPen(QColor(_contrast_text(tokens["danger"])))
            painter.drawText(bubble, Qt.AlignCenter, text)
        painter.end()
