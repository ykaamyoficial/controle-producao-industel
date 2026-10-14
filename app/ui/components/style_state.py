from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


def set_style_state(widget: QWidget, **properties) -> None:
    """Muda propriedades de estado (`active`, `flash`, `dropActive`...) e
    reaplica a folha de estilo, para o QSS por seletor de propriedade valer.
    Troca de estado nunca reescreve o stylesheet do widget."""
    for name, value in properties.items():
        widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class StatusDot(QWidget):
    """Ponto de cor pintado a mao. A cor muda por status (dinamica), por isso
    entra no construtor em vez de virar regra de QSS."""

    def __init__(self, color: str, size: int = 8, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(size, size)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self._color))
        painter.drawEllipse(QRectF(self.rect()))
        painter.end()
