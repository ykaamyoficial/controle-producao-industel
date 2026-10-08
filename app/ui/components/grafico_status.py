from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.ui.components.empty_state import EmptyState
from app.ui.fonts import scaled_px


class DonutCanvas(QWidget):
    segment_clicked = Signal(str)

    def __init__(self, rows, colors, palette, parent=None):
        super().__init__(parent)
        self.rows = rows
        self.colors = colors
        self.palette = palette
        self.setMinimumSize(150, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)
        self._segments = []

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        available = max(80, min(self.width(), self.height()))
        pen_width = max(14, int(available * .105))
        margin = pen_width / 2 + 12
        size = max(48, available - (margin * 2))
        rect = QRectF((self.width() - size) / 2, (self.height() - size) / 2, size, size)
        total = sum(value for _label, value in self.rows)
        pen = QPen()
        pen.setWidth(pen_width)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        start = 90 * 16
        self._segments = []
        for index, (_label, value) in enumerate(self.rows):
            span = -int((value / total) * 360 * 16) if total else 0
            pen.setColor(QColor(self.colors[index % len(self.colors)]))
            painter.setPen(pen)
            painter.drawArc(rect, start, span)
            self._segments.append((_label, start / 16, (start + span) / 16))
            start += span
        # Total no centro, com a legenda "processos" logo abaixo.
        number_font = QFont(painter.font())
        number_font.setPixelSize(scaled_px(28))
        number_font.setWeight(QFont.Weight.Bold)
        painter.setFont(number_font)
        painter.setPen(QColor(self.palette["text"]))
        painter.drawText(rect.adjusted(0, -10, 0, -10), Qt.AlignCenter, str(total))
        caption_font = QFont(painter.font())
        caption_font.setPixelSize(scaled_px(12))
        caption_font.setWeight(QFont.Weight.Normal)
        painter.setFont(caption_font)
        painter.setPen(QColor(self.palette["muted"]))
        painter.drawText(rect.adjusted(0, 28, 0, 28), Qt.AlignCenter, "processos")
        painter.end()

    def mouseReleaseEvent(self, event):
        center_x = self.width() / 2
        center_y = self.height() / 2
        dx = event.position().x() - center_x
        dy = event.position().y() - center_y
        distance = (dx * dx + dy * dy) ** 0.5
        radius = min(self.width(), self.height()) / 2
        if radius * .42 <= distance <= radius * .92 and self._segments:
            import math
            angle = math.degrees(math.atan2(-dy, dx))
            if angle < 0:
                angle += 360
            for label, start, end in self._segments:
                start %= 360
                end %= 360
                hit = end <= angle <= start if end <= start else angle >= end or angle <= start
                if hit:
                    self.segment_clicked.emit(label)
                    break
        super().mouseReleaseEvent(event)


class _Dot(QWidget):
    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(10, 10)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self._color))
        painter.drawEllipse(QRectF(self.rect()))
        painter.end()


class _LegendRow(QWidget):
    """Linha da legenda: ponto da cor, nome e total. A linha inteira e clicavel."""

    clicked = Signal(str)

    def __init__(self, key: str, label: str, value: int, color: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.setObjectName("LegendRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        line = QHBoxLayout(self)
        line.setContentsMargins(8, 4, 8, 4)
        line.setSpacing(10)
        name = QLabel(label.replace("_", " ").title())
        number = QLabel(str(value))
        number.setObjectName("ValueLabel")
        line.addWidget(_Dot(color))
        line.addWidget(name, 1)
        line.addWidget(number)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.key)
        super().mouseReleaseEvent(event)


class GraficoStatus(QWidget):
    item_clicked = Signal(str)

    def __init__(self, rows, colors, palette, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)
        normalized = [(str(row["label"] if isinstance(row, dict) else row[0]), int(row["total"] if isinstance(row, dict) else row[1])) for row in rows]
        normalized = [(label, value) for label, value in normalized if value > 0]
        if not normalized:
            root.addWidget(EmptyState("Sem dados de status", "Os indicadores aparecerão assim que houver processos ativos.", palette))
            return
        donut = DonutCanvas(normalized, colors, palette)
        donut.segment_clicked.connect(self.item_clicked)
        root.addWidget(donut, 1)
        legend = QVBoxLayout()
        legend.setSpacing(2)
        legend.addStretch()
        for index, (label, value) in enumerate(normalized[:7]):
            row = _LegendRow(label, label, value, colors[index % len(colors)])
            row.clicked.connect(self.item_clicked)
            legend.addWidget(row)
        legend.addStretch()
        root.addLayout(legend, 1)
