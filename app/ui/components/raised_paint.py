"""Pintura "em relevo" das bolhas e cartoes do chat.

Sombra suave, degrade vertical, filete de luz no topo e linha de sombra no
pe, mais o "rabinho" estilo WhatsApp nas bolhas. Tudo e pintado a mao (nada
de QGraphicsEffect, que nao pode ser empilhado com o fade das linhas).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF

BUBBLE_RADIUS = 11
BUBBLE_TAIL = 8
BUBBLE_MIN_WIDTH = 96
BUBBLE_MIN_HEIGHT = 36


def bubble_path(body: QRectF, *, tail_on_right: bool, with_tail: bool) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(body, BUBBLE_RADIUS, BUBBLE_RADIUS)
    if with_tail:
        # "Rabinho" no canto superior: triangulo que se funde ao corpo.
        top = body.top()
        if tail_on_right:
            edge = body.right()
            tail = QPolygonF([QPointF(edge - 12, top), QPointF(edge + BUBBLE_TAIL, top), QPointF(edge, top + 11)])
        else:
            edge = body.left()
            tail = QPolygonF([QPointF(edge + 12, top), QPointF(edge - BUBBLE_TAIL, top), QPointF(edge, top + 11)])
        tail_path = QPainterPath()
        tail_path.addPolygon(tail)
        tail_path.closeSubpath()
        path = path.united(tail_path)
    return path


def paint_bubble(
    painter: QPainter,
    body: QRectF,
    *,
    fill_top: QColor,
    fill_bottom: QColor,
    border: QColor | None,
    tail_on_right: bool,
    with_tail: bool,
    dashed: bool = False,
) -> QPainterPath:
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    for offset, alpha in ((3.0, 14), (2.0, 20), (1.0, 26)):
        painter.setBrush(QColor(15, 23, 42, alpha))
        painter.drawPath(bubble_path(body.translated(0, offset), tail_on_right=tail_on_right, with_tail=with_tail))
    path = bubble_path(body, tail_on_right=tail_on_right, with_tail=with_tail)
    gradient = QLinearGradient(body.topLeft(), body.bottomLeft())
    gradient.setColorAt(0.0, fill_top)
    gradient.setColorAt(1.0, fill_bottom)
    painter.setBrush(gradient)
    painter.drawPath(path)
    if border is not None:
        painter.setBrush(Qt.NoBrush)
        pen = QPen(border)
        pen.setWidthF(1.2)
        if dashed:
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.drawPath(path)
    painter.setClipPath(path)
    painter.setPen(QColor(255, 255, 255, 90))
    painter.drawLine(QPointF(body.left() + BUBBLE_RADIUS, body.top() + 0.8), QPointF(body.right() - BUBBLE_RADIUS, body.top() + 0.8))
    painter.setPen(QColor(15, 23, 42, 38))
    painter.drawLine(QPointF(body.left() + BUBBLE_RADIUS, body.bottom() - 0.8), QPointF(body.right() - BUBBLE_RADIUS, body.bottom() - 0.8))
    painter.setClipping(False)
    return path


class RaisedCardMixin:
    """Cartoes de nota interna e de pergunta com o volume das bolhas: sombra,
    degrade, filete de luz e barra colorida a esquerda. O fundo/borda do QSS
    do cartao e anulado so na instancia (propriedade `raised`)."""

    accent_key = "accent"
    dashed = False

    def raise_card(self) -> None:
        self.setProperty("raised", True)  # QSS: QFrame#<cartao>[raised="true"] tira o fundo
        margins = self.layout().contentsMargins()
        self.layout().setContentsMargins(margins.left() + 4, margins.top() + 1, margins.right() + 2, margins.bottom() + 5)

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        palette = self.service.palette
        accent = QColor(palette.get(self.accent_key, palette.get("accent", "#0078d4")))
        base = QColor(palette.get("surface", "#ffffff"))
        body = QRectF(self.rect()).adjusted(1, 1, -2, -4)
        painter = QPainter(self)
        path = paint_bubble(
            painter, body, fill_top=base.lighter(104), fill_bottom=base.darker(103),
            border=accent, tail_on_right=False, with_tail=False, dashed=self.dashed,
        )
        painter.setClipPath(path)
        painter.fillRect(QRectF(body.left(), body.top(), 4, body.height()), accent)
        painter.end()
        super().paintEvent(event)
