from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableWidgetItem

from app.ui.styles import status_color
from app.ui.theme_tokens import active_tokens

# Dado do item que liga o selo: (cor de fundo, cor do texto).
BADGE_ROLE = Qt.UserRole + 20
_BADGE_HEIGHT = 22
_SEPARATOR = " | "


def set_status_badge(item: QTableWidgetItem, status: str, palette: dict, area: str = "") -> QTableWidgetItem:
    """Marca a celula para ser desenhada como selo solido na cor do status.
    O texto do item nao muda - quem le `item.text()` continua lendo o mesmo."""
    background, foreground = status_color(status or "", palette, area)
    item.setData(BADGE_ROLE, (background, foreground))
    return item


class BadgeColumnDelegate(QStyledItemDelegate):
    """Desenha como selo solido de largura fixa as celulas marcadas com
    `set_status_badge()` (skill qt-industrial-ui); as demais ficam com o
    desenho padrao. Texto no formato "prefixo | status" mostra o prefixo como
    texto discreto e so o status dentro do selo."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        colors = index.data(BADGE_ROLE)
        if not colors:
            super().paint(painter, option, index)
            return
        background, foreground = colors[0], colors[1]
        text = str(index.data(Qt.DisplayRole) or "")
        prefix = ""
        if _SEPARATOR in text:
            prefix, text = text.rsplit(_SEPARATOR, 1)

        # Fundo da celula (zebra, hover, selecao) pelo estilo, sem o texto.
        blank = QStyleOptionViewItem(option)
        self.initStyleOption(blank, index)
        blank.text = ""
        style = blank.widget.style() if blank.widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, blank, painter, blank.widget)

        rect = QRectF(option.rect)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipRect(rect)
        left = rect.x() + 8
        available = max(20.0, rect.width() - 16)
        font = QFont(option.font)
        if prefix:
            metrics = QFontMetricsF(font)
            prefix_width = min(metrics.horizontalAdvance(prefix) + 10, available * 0.5)
            painter.setFont(font)
            painter.setPen(QColor(active_tokens()["muted"]))
            painter.drawText(
                QRectF(left, rect.y(), prefix_width, rect.height()),
                Qt.AlignVCenter | Qt.AlignLeft,
                metrics.elidedText(prefix, Qt.ElideRight, prefix_width - 4),
            )
            left += prefix_width
            available -= prefix_width
        badge = QRectF(left, rect.center().y() - _BADGE_HEIGHT / 2, available, _BADGE_HEIGHT)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(badge, _BADGE_HEIGHT / 2, _BADGE_HEIGHT / 2)
        painter.setFont(font)
        painter.setPen(QColor(foreground))
        painter.drawText(badge, Qt.AlignCenter, QFontMetricsF(font).elidedText(text, Qt.ElideRight, max(20.0, badge.width() - 14)))
        painter.restore()
