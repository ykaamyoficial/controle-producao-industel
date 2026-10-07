from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.ui.animations import animate_value
from app.ui.theme_tokens import active_tokens

_KEYBOARD_FOCUS_REASONS = (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)
_HEIGHT = 34
_RADIUS = 10


class SegmentedControl(QWidget):
    """Filtro de escolha unica com contagem por opcao (skill qt-industrial-ui):
    o marcador desliza ate a opcao escolhida. Substitui um QComboBox de status
    quando as opcoes sao poucas e a contagem ajuda a decidir.

    `set_options([(chave, rotulo, contagem ou None), ...])`; `current_key()`
    devolve a chave; `changed` emite a chave nova. Setas esquerda/direita
    trocam a opcao pelo teclado.
    """

    changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._options: list[tuple[str, str, int | None]] = []
        self._current = 0
        self._hovered = -1
        self._marker_x = 0.0
        self._marker_width = 0.0
        self._keyboard_focus = False
        self.setFixedHeight(_HEIGHT)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    # ---- API -------------------------------------------------------------
    def set_options(self, options: list[tuple[str, str, int | None]]) -> None:
        key = self.current_key()
        self._options = list(options)
        keys = [option[0] for option in self._options]
        self._current = keys.index(key) if key in keys else 0
        self._marker_x, self._marker_width = self._span(self._current)
        self.updateGeometry()
        self.update()

    def current_key(self) -> str:
        return self._options[self._current][0] if self._options else ""

    def set_current_key(self, key: str, emit: bool = True) -> None:
        keys = [option[0] for option in self._options]
        if key in keys:
            self._select(keys.index(key), emit)

    # ---- geometria -------------------------------------------------------
    def _font(self, size: int, weight: QFont.Weight) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(size)
        font.setWeight(weight)
        return font

    def _option_width(self, index: int) -> float:
        _key, label, count = self._options[index]
        width = QFontMetricsF(self._font(13, QFont.Weight.DemiBold)).horizontalAdvance(label) + 24
        if count is not None:
            width += QFontMetricsF(self._font(11, QFont.Weight.Bold)).horizontalAdvance(str(count)) + 12 + 6
        return width

    def _span(self, index: int) -> tuple[float, float]:
        if not self._options:
            return 0.0, 0.0
        x = 3.0
        for previous in range(index):
            x += self._option_width(previous)
        return x, self._option_width(index)

    def _index_at(self, x: float) -> int:
        for index in range(len(self._options)):
            start, width = self._span(index)
            if start <= x < start + width:
                return index
        return -1

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        return QSize(int(sum(self._option_width(i) for i in range(len(self._options))) + 6), _HEIGHT)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    # ---- interacao -------------------------------------------------------
    def _select(self, index: int, emit: bool = True) -> None:
        if not 0 <= index < len(self._options) or index == self._current:
            return
        self._current = index
        x, width = self._span(index)
        animate_value(self, "_marker_x", x, 240)
        animate_value(self, "_marker_width", width, 240)
        if emit:
            self.changed.emit(self.current_key())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        index = self._index_at(event.position().x())
        if index != self._hovered:
            self._hovered = index
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = -1
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._select(self._index_at(event.position().x()))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Right:
            self._select(self._current + 1)
        elif event.key() == Qt.Key_Left:
            self._select(self._current - 1)
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
        track = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(tokens["surface_alt"]))
        painter.drawRoundedRect(track, _RADIUS, _RADIUS)
        if self._keyboard_focus:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(tokens["ring"]), 2))
            painter.drawRoundedRect(track.adjusted(0.5, 0.5, -0.5, -0.5), _RADIUS, _RADIUS)
        if self._options:
            painter.setPen(QPen(QColor(tokens["border"]), 1))
            painter.setBrush(QColor(tokens["surface"]))
            painter.drawRoundedRect(
                QRectF(self._marker_x, 3.5, self._marker_width, self.height() - 7), _RADIUS - 2, _RADIUS - 2
            )
        label_metrics = QFontMetricsF(self._font(13, QFont.Weight.DemiBold))
        count_font = self._font(11, QFont.Weight.Bold)
        count_metrics = QFontMetricsF(count_font)
        for index, (_key, label, count) in enumerate(self._options):
            x, _width = self._span(index)
            active = index == self._current
            emphasized = active or index == self._hovered
            painter.setFont(self._font(13, QFont.Weight.DemiBold if active else QFont.Weight.Medium))
            painter.setPen(QColor(tokens["text"] if emphasized else tokens["muted"]))
            label_width = label_metrics.horizontalAdvance(label)
            painter.drawText(QRectF(x + 12, 0, label_width + 2, self.height()), Qt.AlignVCenter | Qt.AlignLeft, label)
            if count is None:
                continue
            pill = QRectF(x + 12 + label_width + 6, self.height() / 2 - 9, count_metrics.horizontalAdvance(str(count)) + 12, 18)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(tokens["accent_soft"] if active else tokens["border"]))
            painter.drawRoundedRect(pill, 9, 9)
            painter.setFont(count_font)
            painter.setPen(QColor(tokens["text"]))
            painter.drawText(pill, Qt.AlignCenter, str(count))
        painter.end()
