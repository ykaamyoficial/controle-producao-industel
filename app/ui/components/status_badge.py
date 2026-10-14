from __future__ import annotations

import re

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QLabel, QSizePolicy
from app.ui.fonts import scaled_px

_RGBA = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)")
_HEIGHT = 24


def _to_color(value: str) -> QColor:
    """Aceita "#rrggbb" e tambem "rgba(r, g, b, a)" (formato de
    `theme_tokens.with_alpha`), que o QColor sozinho nao entende."""
    match = _RGBA.fullmatch(str(value or "").strip())
    if not match:
        return QColor(value)
    red, green, blue = (int(match.group(index)) for index in (1, 2, 3))
    alpha = match.group(4)
    if alpha is None:
        return QColor(red, green, blue)
    alpha_value = float(alpha)
    return QColor(red, green, blue, int(alpha_value if alpha_value > 1 else alpha_value * 255))


def area_badge(text: str, color: str) -> "StatusBadge":
    """Selo solido na cor de uma area, com o texto que der mais contraste."""
    from app.ui.styles import _contrast_text

    return StatusBadge(text, color, _contrast_text(_to_color(color).name()))


def neutral_badge(text: str, palette: dict) -> "StatusBadge":
    """Selo neutro (informacao que nao e status: contagem, rotulo auxiliar)."""
    return StatusBadge(text, palette.get("surface_alt", "#e8f1ff"), palette.get("text", "#0f172a"))


class StatusBadge(QLabel):
    """Selo de status (skill qt-industrial-ui): pilula pintada, de altura
    fixa, com o texto centralizado. Continua sendo um QLabel - `text()` e
    `setText()` funcionam como antes.

    Cores entram pelo construtor ou por `set_colors()`. Se alguma tela ainda
    aplicar `setStyleSheet()` no selo, ele volta a ser desenhado pelo QSS,
    entao personalizacoes existentes continuam valendo ate serem migradas.
    """

    def __init__(self, text: str, bg: str, fg: str = "#ffffff", parent=None):
        super().__init__(text, parent)
        self._background = bg
        self._foreground = fg
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setAlignment(Qt.AlignCenter)

    def set_colors(self, bg: str, fg: str) -> None:
        self._background = bg
        self._foreground = fg
        self.update()

    def colors(self) -> tuple[str, str]:
        """(fundo, texto) atuais do selo."""
        return self._background, self._foreground

    def _font(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(scaled_px(12))
        font.setWeight(QFont.Weight.Bold)
        return font

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        if self.styleSheet():
            return super().sizeHint()
        return QSize(int(QFontMetricsF(self._font()).horizontalAdvance(self.text()) + 28), _HEIGHT)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        self.updateGeometry()

    def paintEvent(self, event) -> None:  # noqa: N802
        if self.styleSheet():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(_to_color(self._background))
        painter.drawRoundedRect(QRectF(self.rect()), _HEIGHT / 2, _HEIGHT / 2)
        painter.setFont(self._font())
        painter.setPen(_to_color(self._foreground))
        painter.drawText(self.rect(), Qt.AlignCenter, self.text())
        painter.end()


class StageChip(QLabel):
    """Etapa de uma linha do tempo (ex.: etapas de uma carga): "current" na cor
    do status, "done" em superficie alternativa e "pending" so com contorno.
    Pintada a mao: a cor da etapa atual vem do status, que e dinamico."""

    def __init__(self, text: str, state: str, bg: str | None = None, fg: str | None = None, parent=None):
        super().__init__(text, parent)
        self.setObjectName("StageChip")
        self.state = state
        self._background = bg
        self._foreground = fg
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(36)

    def paintEvent(self, event) -> None:  # noqa: N802
        from app.ui.theme_tokens import active_tokens

        tokens = active_tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        font = QFont(self.font())
        if self.state == "current" and self._background:
            painter.setPen(Qt.NoPen)
            painter.setBrush(_to_color(self._background))
            text_color = _to_color(self._foreground or tokens["text"])
            font.setWeight(QFont.Weight.Bold)
        elif self.state == "done":
            painter.setPen(_to_color(tokens["border"]))
            painter.setBrush(_to_color(tokens["surface_alt"]))
            text_color = _to_color(tokens["text"])
        else:
            painter.setPen(_to_color(tokens["border"]))
            painter.setBrush(Qt.NoBrush)
            text_color = _to_color(tokens["muted"])
        painter.drawRoundedRect(rect, 9, 9)
        painter.setFont(font)
        painter.setPen(text_color)
        painter.drawText(self.rect().adjusted(8, 0, -8, 0), Qt.AlignCenter | Qt.TextWordWrap, self.text())
        painter.end()
