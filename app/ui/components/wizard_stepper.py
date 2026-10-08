"""Trilha de passos de um assistente em tela sobreposta (skill qt-industrial-ui).

Pintada a mao: cada passo e um circulo (numero, ou check quando ja foi feito)
seguido do nome; os passos ficam distribuidos pela largura e ligados por uma
linha. O estado nunca depende so da cor: o atual tem o nome em negrito e os
feitos mostram o check. Um passo ja feito pode ser clicado para voltar a ele.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.ui.fonts import scaled_px
from app.ui.styles import _contrast_text
from app.ui.theme_tokens import active_tokens

CIRCLE = 30.0
GAP = 10.0
HEIGHT = 48


class WizardStepper(QWidget):
    """`set_steps(["Destino", "Itens", ...])` e `set_current(indice)`."""

    step_clicked = Signal(int)

    def __init__(self, steps: list[str] | None = None, parent=None):
        super().__init__(parent)
        self._steps: list[str] = list(steps or [])
        self._current = 0
        self.setFixedHeight(HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self._hover = -1

    # -- estado -----------------------------------------------------------

    def set_steps(self, steps: list[str]) -> None:
        self._steps = list(steps)
        self._current = min(self._current, max(0, len(self._steps) - 1))
        self.update()

    def set_current(self, index: int) -> None:
        self._current = max(0, min(int(index), max(0, len(self._steps) - 1)))
        self.update()
        self.setAccessibleName(self.accessible_text())

    def current(self) -> int:
        return self._current

    def steps(self) -> list[str]:
        return list(self._steps)

    def state_of(self, index: int) -> str:
        if index < self._current:
            return "done"
        return "current" if index == self._current else "pending"

    def accessible_text(self) -> str:
        if not self._steps:
            return ""
        return f"Passo {self._current + 1} de {len(self._steps)}: {self._steps[self._current]}"

    # -- geometria --------------------------------------------------------

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        return QSize(120 * max(1, len(self._steps)), HEIGHT)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(80 * max(1, len(self._steps)), HEIGHT)

    def _cells(self) -> list[QRectF]:
        count = max(1, len(self._steps))
        width = self.width() / count
        return [QRectF(index * width, 0, width, self.height()) for index in range(count)]

    def _name_font(self, state: str) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(scaled_px(13))
        font.setWeight(QFont.Weight.Bold if state == "current" else QFont.Weight.DemiBold)
        return font

    # -- interacao --------------------------------------------------------

    def _index_at(self, x: float) -> int:
        for index, cell in enumerate(self._cells()):
            if cell.left() <= x < cell.right():
                return index
        return -1

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        index = self._index_at(event.position().x())
        clickable = 0 <= index < self._current
        self._hover = index if clickable else -1
        self.setCursor(Qt.PointingHandCursor if clickable else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = -1
        self.unsetCursor()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        index = self._index_at(event.position().x())
        if event.button() == Qt.LeftButton and 0 <= index < self._current:
            self.step_clicked.emit(index)
        super().mouseReleaseEvent(event)

    # -- pintura ----------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802
        if not self._steps:
            return
        tokens = active_tokens()
        accent = QColor(tokens["accent"])
        done = QColor(tokens.get("success", tokens["accent"]))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        center_y = self.height() / 2
        cells = self._cells()
        # Trechos de ligacao primeiro, para os circulos ficarem por cima.
        text_ends: list[float] = []
        for index, cell in enumerate(cells):
            state = self.state_of(index)
            metrics = QFontMetricsF(self._name_font(state))
            text_ends.append(cell.left() + CIRCLE + GAP + metrics.horizontalAdvance(self._steps[index]))
        for index in range(len(cells) - 1):
            start = text_ends[index] + 14
            end = cells[index + 1].left() - 4
            if end <= start:
                continue
            finished = index + 1 <= self._current
            painter.setPen(QPen(done if finished else QColor(tokens["border"]), 2))
            painter.drawLine(QPointF(start, center_y), QPointF(end, center_y))
        for index, cell in enumerate(cells):
            state = self.state_of(index)
            circle = QRectF(cell.left() + 1, center_y - CIRCLE / 2, CIRCLE, CIRCLE)
            if state == "pending":
                painter.setPen(QPen(QColor(tokens["input_border"]), 1.5))
                painter.setBrush(QColor(tokens["surface"]))
                painter.drawEllipse(circle.adjusted(0.5, 0.5, -0.5, -0.5))
                glyph = QColor(tokens["muted"])
            else:
                fill = done if state == "done" else accent
                painter.setPen(Qt.NoPen)
                painter.setBrush(fill)
                painter.drawEllipse(circle)
                glyph = QColor(_contrast_text(fill.name()))
            if state == "done":
                pen = QPen(glyph, 2.2)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                x, y = circle.center().x(), circle.center().y()
                path = QPainterPath(QPointF(x - 5.5, y))
                path.lineTo(x - 1.5, y + 4)
                path.lineTo(x + 5.5, y - 4)
                painter.drawPath(path)
            else:
                number_font = QFont(self.font())
                number_font.setPixelSize(scaled_px(13))
                number_font.setWeight(QFont.Weight.Bold)
                painter.setFont(number_font)
                painter.setPen(glyph)
                painter.drawText(circle, Qt.AlignCenter, str(index + 1))
            name_font = self._name_font(state)
            painter.setFont(name_font)
            if state == "pending":
                painter.setPen(QColor(tokens["muted"]))
            else:
                painter.setPen(QColor(tokens["accent"] if index == self._hover else tokens["text"]))
            name_rect = QRectF(circle.right() + GAP, 0, cell.right() - circle.right() - GAP - 4, self.height())
            painter.drawText(name_rect, Qt.AlignVCenter | Qt.AlignLeft, self._steps[index])
        painter.end()
