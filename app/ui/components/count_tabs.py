from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.ui.animations import animate_value
from app.ui.theme_tokens import active_tokens

_KEYBOARD_FOCUS_REASONS = (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)
_HEIGHT = 40
_RADIUS = 10
_GAP = 4


class CountTabs(QWidget):
    """Barra de abas das telas sobrepostas (skill qt-industrial-ui): nome +
    contagem opcional, aba ativa em negrito sobre fundo branco e um traco na
    cor de destaque que desliza ate ela.

    So a barra: ligue `changed` ao `setCurrentIndex` do QStackedLayout/
    QStackedWidget que guarda as paginas. Setas esquerda/direita trocam de aba.
    """

    changed = Signal(int)

    def __init__(self, tabs: list[tuple[str, int | None]] | None = None, parent=None):
        super().__init__(parent)
        self._tabs: list[tuple[str, int | None]] = list(tabs or [])
        self._current = 0
        self._hovered = -1
        self._keyboard_focus = False
        self._marker_x, self._marker_width = self._span(0)
        self.setFixedHeight(_HEIGHT)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    # ---- API -------------------------------------------------------------
    def set_tabs(self, tabs: list[tuple[str, int | None]]) -> None:
        self._tabs = list(tabs)
        self._current = min(self._current, max(0, len(self._tabs) - 1))
        self._marker_x, self._marker_width = self._span(self._current)
        self.update()

    def set_count(self, index: int, count: int | None) -> None:
        if 0 <= index < len(self._tabs):
            self._tabs[index] = (self._tabs[index][0], count)
            self._marker_x, self._marker_width = self._span(self._current)
            self.update()

    def current_index(self) -> int:
        return self._current

    def set_current_index(self, index: int, animated: bool = True) -> None:
        if not 0 <= index < len(self._tabs) or index == self._current:
            return
        self._current = index
        x, width = self._span(index)
        animate_value(self, "_marker_x", x, 240 if animated else 0)
        animate_value(self, "_marker_width", width, 240 if animated else 0)
        self.changed.emit(index)

    # ---- geometria -------------------------------------------------------
    def _font(self, size: int, weight: QFont.Weight) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(size)
        font.setWeight(weight)
        return font

    def _tab_width(self, index: int) -> float:
        name, count = self._tabs[index]
        width = QFontMetricsF(self._font(13, QFont.Weight.Bold)).horizontalAdvance(name) + 32
        if count is not None:
            width += QFontMetricsF(self._font(11, QFont.Weight.Bold)).horizontalAdvance(str(count)) + 12 + 8
        return width

    def _span(self, index: int) -> tuple[float, float]:
        if not self._tabs:
            return 0.0, 0.0
        x = 2.0
        for previous in range(index):
            x += self._tab_width(previous) + _GAP
        return x, self._tab_width(index)

    def _index_at(self, x: float) -> int:
        for index in range(len(self._tabs)):
            start, width = self._span(index)
            if start <= x < start + width:
                return index
        return -1

    # ---- interacao -------------------------------------------------------
    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        index = self._index_at(event.position().x())
        if index != self._hovered:
            self._hovered = index
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = -1
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.set_current_index(self._index_at(event.position().x()))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Right:
            self.set_current_index(self._current + 1)
        elif event.key() == Qt.Key_Left:
            self.set_current_index(self._current - 1)
        else:
            super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802
        self._keyboard_focus = event.reason() in _KEYBOARD_FOCUS_REASONS
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self._keyboard_focus = False
        self.update()
        super().focusOutEvent(event)

    # ---- pintura ---------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802
        tokens = active_tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        height = self.height()
        painter.fillRect(QRectF(0, height - 1, self.width(), 1), QColor(tokens["border"]))
        painter.setClipRect(QRectF(0, 0, self.width(), height))
        name_metrics = QFontMetricsF(self._font(13, QFont.Weight.Bold))
        count_font = self._font(11, QFont.Weight.Bold)
        count_metrics = QFontMetricsF(count_font)
        for index, (name, count) in enumerate(self._tabs):
            x, width = self._span(index)
            active = index == self._current
            body = QRectF(x + 0.5, 4.5, width - 1, height + 12)
            if active:
                painter.setPen(QPen(QColor(tokens["border"]), 1))
                painter.setBrush(QColor(tokens["surface"]))
                painter.drawRoundedRect(body, _RADIUS, _RADIUS)
            elif index == self._hovered:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(tokens["surface_alt"]))
                painter.drawRoundedRect(body.adjusted(0, 0, 0, -14), _RADIUS, _RADIUS)
            painter.setFont(self._font(13, QFont.Weight.Bold if active else QFont.Weight.Medium))
            painter.setPen(QColor(tokens["text"] if active or index == self._hovered else tokens["muted"]))
            name_width = name_metrics.horizontalAdvance(name)
            painter.drawText(QRectF(x + 16, 4, name_width + 2, height - 6), Qt.AlignVCenter | Qt.AlignLeft, name)
            if count is None:
                continue
            pill = QRectF(x + 16 + name_width + 8, height / 2 - 8, count_metrics.horizontalAdvance(str(count)) + 12, 18)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(tokens["accent"] if active else tokens["border"]))
            painter.drawRoundedRect(pill, 9, 9)
            painter.setFont(count_font)
            painter.setPen(QColor(tokens["accent_text"] if active else tokens["text"]))
            painter.drawText(pill, Qt.AlignCenter, str(count))
        if self._tabs:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(tokens["accent"]))
            painter.drawRoundedRect(QRectF(self._marker_x + 10, height - 3, self._marker_width - 20, 3), 1.5, 1.5)
            if self._keyboard_focus:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(tokens["ring"]), 2))
                painter.drawRoundedRect(
                    QRectF(self._marker_x + 2, 6, self._marker_width - 4, height - 12), _RADIUS - 2, _RADIUS - 2
                )
        painter.end()
