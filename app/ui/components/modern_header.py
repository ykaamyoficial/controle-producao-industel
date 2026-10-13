"""Cabecalho padrao das tabelas operacionais (plano em docs/architecture/CABECALHO_TABELA_PLANO.md).

Pintado por token (claro/escuro/qualquer paleta): faixa azul-clara com o titulo em negrito
centralizado, como sempre foi; o que muda e o acabamento - seta de ordem propria so na coluna
ordenada (fantasma no hover das outras), barra de destaque, hover suave, separadores curtos, icone
nas colunas sem titulo e caixa de selecao igual a das linhas. Mantem o contrato do antigo
`BatchSelectionHeader` (modo lote): `set_batch_state`, `check_state`, `toggle_visible_requested`.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QHeaderView, QToolTip

from app.ui.animations import STANDARD_CURVE, motion_duration
from app.ui.icons import AppIcons
from app.ui.icons.icon_provider import render_pixmap
from app.ui.theme_tokens import active_tokens, mix

HEADER_HEIGHT = 38
_ARROW_SLOT = 14  # espaco da seta reservado ao lado do titulo: ele nao "pula" quando a seta aparece
_EDGE_GRAB = 5  # px de cada lado da divisoria que continuam sendo "redimensionar"

# Colunas sem titulo: o cabecalho mostra o icone e a dica no lugar da faixa em branco.
ICON_COLUMNS: dict[str, tuple[AppIcons, str]] = {
    "status_icon": (AppIcons.CIRCLE_DOT, "Situação rápida da proposta"),
    "chat_icon": (AppIcons.CHAT, "Conversa da proposta"),
    "fiscal_action": (AppIcons.FISCAL, "Ação fiscal"),
}
_NOT_SORTABLE = {"batch_select", "acoes"}


def _color(token: str, alpha: float | None = None) -> QColor:
    color = QColor(active_tokens()[token])
    if alpha is not None:
        color.setAlphaF(max(0.0, min(1.0, alpha)))
    return color


class ModernHeaderView(QHeaderView):
    """Cabecalho tri-state que opera somente sobre as linhas visiveis (modo lote) e pinta o acabamento novo."""

    toggle_visible_requested = Signal(bool)

    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._batch_active = False
        self._check_state = Qt.Unchecked
        self._has_visible_rows = False
        self._hover: dict[int, float] = {}
        self._bar: dict[int, float] = {}
        self._animations: dict[tuple[str, int], QVariantAnimation] = {}
        self._hovered = -1
        self.setMouseTracking(True)
        self.setHighlightSections(False)
        self.setSectionsClickable(True)
        self.setFixedHeight(HEADER_HEIGHT)
        self.sortIndicatorChanged.connect(self._sort_changed)

    # -- contrato do modo lote ---------------------------------------------------------------------
    @property
    def check_state(self) -> Qt.CheckState:
        return self._check_state

    def set_batch_state(self, active: bool, state: Qt.CheckState = Qt.Unchecked, *, has_visible_rows: bool = False) -> None:
        self._batch_active = bool(active)
        self._check_state = state
        self._has_visible_rows = bool(has_visible_rows)
        self.viewport().update()

    # -- colunas -------------------------------------------------------------------------------------
    def column_key(self, section: int) -> str:
        model = self.model()
        while model is not None and hasattr(model, "sourceModel") and model.sourceModel() is not None:
            model = model.sourceModel()
        columns = getattr(model, "columns", None)
        try:
            return str(columns[section][0])
        except (TypeError, IndexError, KeyError):
            return ""

    def _title(self, section: int) -> str:
        model = self.model()
        value = model.headerData(section, self.orientation(), Qt.DisplayRole) if model is not None else ""
        return str(value or "")

    def is_sortable(self, section: int) -> bool:
        if self._is_batch_column(section):
            return False
        return bool(self._title(section)) and self.column_key(section) not in _NOT_SORTABLE

    def _is_batch_column(self, section: int) -> bool:
        return self._batch_active and section == 0

    def _is_interactive(self, section: int) -> bool:
        return self.is_sortable(section) or (self._is_batch_column(section) and self._has_visible_rows)

    # -- movimento -----------------------------------------------------------------------------------
    def _animate(self, store: dict[int, float], kind: str, section: int, end: float, duration: int) -> None:
        key = (kind, section)
        animation = self._animations.get(key)
        if animation is None:
            animation = QVariantAnimation(self)
            animation.setEasingCurve(STANDARD_CURVE)

            def apply(value, target=store, index=section):
                target[index] = float(value)
                self.viewport().update()

            animation.valueChanged.connect(apply)
            self._animations[key] = animation
        animation.stop()
        duration = motion_duration(duration)
        if duration <= 0:
            store[section] = float(end)
            self.viewport().update()
            return
        animation.setDuration(duration)
        animation.setStartValue(float(store.get(section, 0.0)))
        animation.setEndValue(float(end))
        animation.start()

    def _sort_changed(self, section: int, _order) -> None:
        for other in list(self._bar):
            if other != section:
                self._animate(self._bar, "bar", other, 0.0, 120)
        if self.is_sortable(section):
            self._bar[section] = 0.0
            self._animate(self._bar, "bar", section, 1.0, 240)
        self.viewport().update()

    def _set_hovered(self, section: int) -> None:
        if section == self._hovered:
            return
        if self._hovered >= 0:
            self._animate(self._hover, "hover", self._hovered, 0.0, 140)
        self._hovered = section
        if section >= 0 and self._is_interactive(section):
            self._animate(self._hover, "hover", section, 1.0, 140)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        position = event.position().toPoint()
        section = self.logicalIndexAt(position)
        self._set_hovered(section)
        if not self._near_edge(position, section) and section >= 0 and self._is_interactive(section):
            self.setCursor(Qt.PointingHandCursor)
        elif not self._near_edge(position, section):
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._set_hovered(-1)
        self.unsetCursor()
        super().leaveEvent(event)

    def _near_edge(self, position: QPoint, section: int) -> bool:
        """Perto da divisoria entre colunas: ali o cabecalho redimensiona em vez de ordenar."""
        if section < 0:
            return False
        left = self.sectionViewportPosition(section)
        right = left + self.sectionSize(section)
        return position.x() <= left + _EDGE_GRAB and section > 0 or position.x() >= right - _EDGE_GRAB

    def mousePressEvent(self, event) -> None:  # noqa: N802
        position = event.position().toPoint()
        section = self.logicalIndexAt(position)
        if section >= 0 and not self._near_edge(position, section):
            if self._is_batch_column(section):
                if self._has_visible_rows:
                    self.toggle_visible_requested.emit(self._check_state != Qt.Checked)
                event.accept()
                return
            if not self.is_sortable(section):
                event.accept()  # coluna de icone: nao ordena
                return
        super().mousePressEvent(event)

    def viewportEvent(self, event) -> bool:  # noqa: N802
        if event.type() == QEvent.ToolTip:
            section = self.logicalIndexAt(event.pos())
            tip = ""
            if section >= 0:
                key = self.column_key(section)
                if not self._title(section) and key in ICON_COLUMNS:
                    tip = ICON_COLUMNS[key][1]
                elif self.is_sortable(section):
                    tip = f"Ordenar por {self._title(section)}"
                elif self._is_batch_column(section):
                    tip = "Marcar ou desmarcar as propostas listadas"
            if tip:
                QToolTip.showText(event.globalPos(), tip, self)
            else:
                QToolTip.hideText()
            return True
        return super().viewportEvent(event)

    # -- pintura -------------------------------------------------------------------------------------
    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int) -> None:  # noqa: N802
        if not rect.isValid():
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        hover = self._hover.get(logical_index, 0.0)
        base = QColor(active_tokens()["table_header"])
        background = mix_colors(base, QColor(active_tokens()["surface_hover"]), hover)
        painter.fillRect(rect, background)

        # Linha de baixo mais firme: separa de verdade o cabecalho do corpo.
        painter.setPen(QPen(_color("border"), 1))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        # Separador curto entre colunas (some ao lado da coluna em hover).
        last = logical_index >= self.count() - 1
        next_hover = self._hover.get(self.logicalIndex(self.visualIndex(logical_index) + 1), 0.0) if not last else 0.0
        if not last and hover < 0.05 and next_hover < 0.05:
            middle = rect.center().y()
            painter.setPen(QPen(_color("border"), 1))
            painter.drawLine(rect.right(), middle - 8, rect.right(), middle + 8)

        title = self._title(logical_index)
        key = self.column_key(logical_index)
        sortable = self.is_sortable(logical_index)
        sorted_now = sortable and self.sortIndicatorSection() == logical_index

        if self._is_batch_column(logical_index):
            self._paint_checkbox(painter, QRectF(rect.center().x() - 8, rect.center().y() - 8.5, 16, 16), hover)
        elif not title and key in ICON_COLUMNS:
            color = mix_colors(QColor(active_tokens()["muted"]), QColor(active_tokens()["accent"]), hover)
            pixmap = render_pixmap(ICON_COLUMNS[key][0], 16, color.name())
            if pixmap is not None:
                painter.drawPixmap(QRect(rect.center().x() - 8, rect.center().y() - 8, 16, 16), pixmap)
        elif title:
            font = self.font()
            font.setBold(True)
            painter.setFont(font)
            metrics = QFontMetrics(font)
            area = rect.adjusted(8, 0, -8, -1)
            reserve = _ARROW_SLOT + 4 if sortable else 0
            text = metrics.elidedText(title, Qt.ElideRight, max(10, area.width() - reserve))
            text_width = metrics.horizontalAdvance(text)
            x = area.x() + (area.width() - (text_width + reserve)) / 2
            color = _color("accent") if sorted_now else mix_colors(QColor(active_tokens()["text"]), QColor(active_tokens()["accent"]), hover * 0.6)
            painter.setPen(color)
            painter.drawText(QRectF(x, rect.y(), text_width + 2, rect.height() - 1), Qt.AlignVCenter | Qt.AlignLeft, text)
            if sortable:
                box = QRectF(x + text_width + 4, rect.center().y() - 7, _ARROW_SLOT - 1, 13)
                if sorted_now:
                    self._paint_arrow(painter, box, self.sortIndicatorOrder() == Qt.DescendingOrder, _color("accent"))
                elif hover > 0.02:
                    self._paint_both(painter, box, _color("subtle", hover))

        # Barra de destaque da coluna ordenada: 2px, cresce do centro.
        bar = self._bar.get(logical_index, 1.0 if sorted_now else 0.0)
        if bar > 0.001:
            half = rect.width() * 0.5 * bar
            painter.setPen(Qt.NoPen)
            painter.setBrush(_color("accent"))
            painter.drawRoundedRect(QRectF(rect.center().x() - half, rect.bottom() - 1.5, half * 2, 2.5), 1.2, 1.2)

        # Pega de redimensionar na borda da coluna sob o mouse.
        if hover > 0.05 and not last:
            painter.setPen(QPen(_color("accent", 0.55 * hover), 2))
            painter.drawLine(rect.right() - 1, rect.top() + 8, rect.right() - 1, rect.bottom() - 8)
        painter.restore()

    @staticmethod
    def _paint_arrow(painter: QPainter, box: QRectF, descending: bool, color: QColor) -> None:
        painter.save()
        painter.setPen(QPen(color, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        x, top, bottom = box.center().x(), box.top() + 2, box.bottom() - 2
        painter.drawLine(QPointF(x, top), QPointF(x, bottom))
        tip = 3.6
        if descending:
            painter.drawLine(QPointF(x - tip, bottom - tip), QPointF(x, bottom))
            painter.drawLine(QPointF(x + tip, bottom - tip), QPointF(x, bottom))
        else:
            painter.drawLine(QPointF(x - tip, top + tip), QPointF(x, top))
            painter.drawLine(QPointF(x + tip, top + tip), QPointF(x, top))
        painter.restore()

    @staticmethod
    def _paint_both(painter: QPainter, box: QRectF, color: QColor) -> None:
        painter.save()
        painter.setPen(QPen(color, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        x, y = box.center().x(), box.center().y()
        painter.drawPolyline([QPointF(x - 3.5, y - 1.5), QPointF(x, y - 5), QPointF(x + 3.5, y - 1.5)])
        painter.drawPolyline([QPointF(x - 3.5, y + 1.5), QPointF(x, y + 5), QPointF(x + 3.5, y + 1.5)])
        painter.restore()

    def _paint_checkbox(self, painter: QPainter, box: QRectF, hover: float) -> None:
        checked = self._check_state == Qt.Checked
        partial = self._check_state == Qt.PartiallyChecked
        on = checked or partial
        enabled = self._has_visible_rows
        painter.save()
        border = _color("accent") if on else _color("input_border")
        if not enabled:
            border.setAlphaF(0.5)
        painter.setPen(QPen(border, 1.4))
        painter.setBrush(_color("accent") if on else _color("surface"))
        painter.drawRoundedRect(box, 4, 4)
        painter.setPen(QPen(_color("accent_text"), 1.9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if checked:
            painter.drawPolyline([
                QPointF(box.left() + 3.8, box.center().y() + 0.2),
                QPointF(box.left() + 6.8, box.center().y() + 3.2),
                QPointF(box.right() - 3.6, box.center().y() - 3.2),
            ])
        elif partial:
            painter.drawLine(QPointF(box.left() + 4, box.center().y()), QPointF(box.right() - 4, box.center().y()))
        painter.restore()


def mix_colors(a: QColor, b: QColor, t: float) -> QColor:
    """Mistura de duas cores (0 = a, 1 = b)."""
    return QColor(mix(a.name(), b.name(), max(0.0, min(1.0, t))))
