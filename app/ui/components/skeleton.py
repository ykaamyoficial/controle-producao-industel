from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget

from app.ui.animations import reduced_motion
from app.ui.theme_tokens import active_tokens, mix

_ROW_HEIGHT = 40
# (inicio, largura) de cada barra: > 1 e pixel, <= 1 e fracao da largura.
_BARS = ((16, 18), (52, 76), (180, 0.26), (0.56, 150), (0.72, 84), (0.83, 0.12))


class SkeletonRows(QWidget):
    """Estado de carregamento (skill qt-industrial-ui): linhas-fantasma com um
    brilho que atravessa, no lugar de um texto "Carregando...". Coloque no
    mesmo QStackedLayout da tabela/painel e troque para ele enquanto o
    `start_worker` busca os dados. O brilho so roda com o widget visivel."""

    def __init__(self, parent=None, *, top_offset: int = 34):
        super().__init__(parent)
        self._phase = 0.0
        self._top_offset = top_offset
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(1300)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setLoopCount(-1)
        self._animation.valueChanged.connect(self._advance)

    def _advance(self, value) -> None:
        self._phase = value
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if not reduced_motion():
            self._animation.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._animation.stop()
        super().hideEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        tokens = active_tokens()
        base = QColor(tokens["surface_alt"])
        shine = QColor(mix(tokens["surface_alt"], tokens["surface"], 0.75))
        moving = self._animation.state() == QVariantAnimation.Running
        width = self.width()
        gradient = QLinearGradient(width * (self._phase * 2 - 1), 0, width * (self._phase * 2 - 0.4), 0)
        gradient.setColorAt(0.0, base)
        gradient.setColorAt(0.5, shine if moving else base)
        gradient.setColorAt(1.0, base)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        y = self._top_offset
        row = 0
        while y + _ROW_HEIGHT <= self.height():
            painter.setBrush(gradient)
            for start, size in _BARS:
                x = start if start > 1 else width * start
                bar_width = size if size > 1 else width * size
                bar_width *= 0.7 + 0.3 * ((row * 7 + int(x)) % 5) / 4
                painter.drawRoundedRect(QRectF(x, y + 13, bar_width, 14), 5, 5)
            y += _ROW_HEIGHT
            row += 1
        painter.end()
