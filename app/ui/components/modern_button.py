from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen

from app.ui.animations import animate_value
from app.ui.components.app_icon_button import AppIconButton
from app.ui.icons import IconSize
from app.ui.styles import _contrast_text
from app.ui.theme_tokens import active_tokens, mix

_STOCK_OBJECT_NAMES = ("AccentButton", "GhostButton")
_KEYBOARD_FOCUS_REASONS = (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)
_RADIUS = 10


class ModernButton(AppIconButton):
    """Botao padrao do app, pintado a mao para ter hover/clique animados e
    anel de foco (skill qt-industrial-ui). Variantes:

    - "primary": fundo na cor de destaque. Uma por tela. `accent=True` cai aqui.
    - "secondary" (padrao): fundo azul-claro, icone na cor de destaque.
    - "ghost": sem fundo; para Limpar, Cancelar, Fechar, paginacao.
    - "danger": so para confirmar acao irreversivel.

    Se a tela trocar o objectName ou aplicar stylesheet proprio no botao, ele
    volta a ser desenhado pelo QSS - personalizacoes existentes continuam
    valendo ate a tela ser migrada.
    """

    def __init__(
        self,
        text: str = "",
        icon_name: str | None = None,
        accent: bool = False,
        parent=None,
        *,
        variant: str | None = None,
    ):
        self._variant = variant or ("primary" if accent else "secondary")
        self._hover = 0.0
        self._press = 0.0
        self._keyboard_focus = False
        super().__init__(
            icon_name,
            text,
            color=self._icon_color(),
            size=IconSize.MD,
            accent=accent,
            parent=parent,
        )
        self.setMinimumHeight(34)
        if text:
            icon_space = 28 if icon_name else 0
            self.setMinimumWidth(max(82, self.fontMetrics().horizontalAdvance(text) + icon_space + 30))

    def variant(self) -> str:
        return self._variant

    def set_variant(self, variant: str) -> None:
        self._variant = variant
        self.set_color_override(self._icon_color())
        self.update()

    def _foreground(self) -> str:
        tokens = active_tokens()
        if self._variant == "primary":
            return tokens["accent_text"]
        if self._variant == "danger":
            return _contrast_text(tokens["danger"])
        return tokens["text"]

    def _icon_color(self) -> str:
        tokens = active_tokens()
        return self._foreground() if self._variant in ("primary", "danger") else tokens["accent"]

    def _uses_custom_paint(self) -> bool:
        return self.objectName() in _STOCK_OBJECT_NAMES and not self.styleSheet()

    # ---- interacao -------------------------------------------------------
    def changeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # Troca de tema reaplica a folha de estilo na janela: recolore o icone.
        if event.type() == QEvent.StyleChange and getattr(self, "_color_override", None) is not None:
            color = self._icon_color()
            if color != self._color_override:
                self.set_color_override(color)
        super().changeEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        animate_value(self, "_hover", 1.0, 140)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        animate_value(self, "_hover", 0.0, 180)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        animate_value(self, "_press", 1.0, 80)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        animate_value(self, "_press", 0.0, 180)
        super().mouseReleaseEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802
        self._keyboard_focus = event.reason() in _KEYBOARD_FOCUS_REASONS
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self._keyboard_focus = False
        super().focusOutEvent(event)

    # ---- pintura ---------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if not self._uses_custom_paint():
            super().paintEvent(event)
            return
        tokens = active_tokens()
        enabled = self.isEnabled()
        hover = self._hover if enabled else 0.0
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if not enabled:
            painter.setOpacity(0.5)
        bounds = QRectF(self.rect())
        center = bounds.center()
        scale = 1.0 - 0.03 * self._press
        painter.translate(center)
        painter.scale(scale, scale)
        painter.translate(-center)

        body = bounds.adjusted(2, 2, -2, -2)
        if self._variant == "primary":
            background = QColor(mix(tokens["accent"], tokens["accent_hover"], hover))
        elif self._variant == "danger":
            background = QColor(mix(tokens["danger"], tokens["text"], 0.14 * hover))
        elif self._variant == "ghost":
            background = QColor(tokens["surface_alt"])
            background.setAlphaF(hover)
        else:
            background = QColor(mix(tokens["surface_alt"], tokens["surface_hover"], hover))
        painter.setPen(Qt.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(body, _RADIUS, _RADIUS)
        if self._keyboard_focus and self.hasFocus():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(tokens["ring"]), 2))
            painter.drawRoundedRect(bounds.adjusted(1, 1, -1, -1), _RADIUS + 1, _RADIUS + 1)

        font = QFont(self.font())
        font.setWeight(QFont.Weight.DemiBold)
        metrics = QFontMetricsF(font)
        text = self.text().replace("&", "")
        icon = self.icon()
        icon_size = self.iconSize() if not icon.isNull() else None
        icon_width = icon_size.width() if icon_size else 0
        gap = 7 if icon_size and text else 0
        available = body.width() - 16 - icon_width - gap
        if text and metrics.horizontalAdvance(text) > available:
            text = metrics.elidedText(text, Qt.ElideRight, max(0.0, available))
        text_width = metrics.horizontalAdvance(text) if text else 0.0
        x = body.center().x() - (icon_width + gap + text_width) / 2
        if icon_size:
            pixmap = icon.pixmap(icon_size)
            painter.drawPixmap(
                QRectF(x, body.center().y() - icon_size.height() / 2, icon_size.width(), icon_size.height()),
                pixmap,
                QRectF(pixmap.rect()),
            )
            x += icon_width + gap
        if text:
            painter.setFont(font)
            painter.setPen(QColor(self._foreground()))
            painter.drawText(QRectF(x, body.top(), text_width + 2, body.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.end()
        self._paint_badge()
