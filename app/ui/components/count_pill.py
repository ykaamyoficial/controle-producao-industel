"""Selo de contagem discreto ao lado de um titulo (ex.: baixas pendentes do Almoxarifado).

Segue a convencao de `AppIconButton.set_badge_count`: o numero e pintado no `paintEvent`
(nunca via `setText`) e escondido com zero. Testes leem `format_count_badge(pill._badge_count)`."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.ui.components.count_badge import format_count_badge
from app.ui.fonts import scaled_px
from app.ui.theme_tokens import ui_tokens

_HEIGHT = 20


class CountPill(QWidget):
    def __init__(self, palette: dict, parent=None):
        super().__init__(parent)
        self._palette = palette
        self._badge_count = 0
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setVisible(False)

    def set_count(self, count: int, tooltip: str = "") -> None:
        count = max(0, int(count))
        self.setToolTip(tooltip if count else "")
        self.setAccessibleDescription(tooltip if count else "")
        if count != self._badge_count:
            self._badge_count = count
            self.updateGeometry()
            self.update()
        self.setVisible(count > 0)

    def _font(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(scaled_px(12))
        font.setWeight(QFont.Weight.Bold)
        return font

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        text = format_count_badge(self._badge_count)
        return QSize(max(_HEIGHT, int(QFontMetricsF(self._font()).horizontalAdvance(text)) + 14), _HEIGHT)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        text = format_count_badge(self._badge_count)
        if not text:
            return
        from app.ui.styles import _contrast_text

        background = ui_tokens(self._palette)["warning"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(QRectF(self.rect()), _HEIGHT / 2, _HEIGHT / 2)
        painter.setFont(self._font())
        painter.setPen(QColor(_contrast_text(background)))
        painter.drawText(self.rect(), Qt.AlignCenter, text)
        painter.end()
