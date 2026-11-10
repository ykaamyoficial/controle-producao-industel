from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QAction, QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QHeaderView, QMenu, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableWidget

from app.ui.icons import AppIcons, IconSize, make_icon, status_icon
from app.ui.theme_tokens import active_tokens

ACTION_COLUMN = 0
ACTION_COLUMN_WIDTH = 44


@dataclass(frozen=True)
class RowAction:
    """Uma acao possivel da linha. A mesma lista alimenta o menu de contexto e a Central de Acoes."""

    label: str
    icon: AppIcons | str | None
    enabled: bool
    callback: Callable[[], None]
    description: str = ""
    primary: bool = False
    destructive: bool = False


class RowActionIconDelegate(QStyledItemDelegate):
    """Icone de status em circulo na coluna 0, igual ao da ModernTable."""

    def __init__(self, palette: dict, parent=None):
        super().__init__(parent)
        self.palette = palette

    def paint(self, painter: QPainter, option, index) -> None:
        blank = QStyleOptionViewItem(option)
        self.initStyleOption(blank, index)
        blank.text = ""
        style = blank.widget.style() if blank.widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, blank, painter, blank.widget)
        tokens = active_tokens()
        size = int(IconSize.TABLE_STATUS)
        center = option.rect.center()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(tokens["border"]), 1))
        painter.setBrush(QBrush(QColor(tokens["surface"])))
        painter.drawEllipse(QPointF(center.x(), center.y()), 13, 13)
        pix = status_icon("status", palette=self.palette, size=size).pixmap(size, size)
        painter.drawPixmap(int(center.x() - size / 2), int(center.y() - size / 2), pix)
        painter.restore()


class _HandCursor(QObject):
    """Cursor de mao sobre a coluna do icone."""

    def __init__(self, table: QTableWidget):
        super().__init__(table)
        self.table = table
        table.viewport().setMouseTracking(True)
        table.viewport().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt override)
        if event.type() == QEvent.MouseMove:
            x, y = int(event.position().x()), int(event.position().y())
            on_icon = self.table.columnAt(x) == ACTION_COLUMN and self.table.rowAt(y) >= 0
            self.table.viewport().setCursor(Qt.PointingHandCursor if on_icon else Qt.ArrowCursor)
        return False


def install_row_actions(
    table: QTableWidget,
    palette: dict,
    build_actions: Callable[[int], list[RowAction]],
    open_center: Callable[[int, list[RowAction]], None],
) -> None:
    """Coluna 0 vira o icone que abre a Central de Acoes; botao direito abre o menu.
    Em ambos a linha e selecionada antes. `build_actions(row)` decide o que a linha permite."""
    table.setItemDelegateForColumn(ACTION_COLUMN, RowActionIconDelegate(palette, table))
    table.horizontalHeader().setSectionResizeMode(ACTION_COLUMN, QHeaderView.Fixed)
    table.setColumnWidth(ACTION_COLUMN, ACTION_COLUMN_WIDTH)
    _HandCursor(table)

    def clicked(row: int, column: int) -> None:
        if column != ACTION_COLUMN:
            return
        table.selectRow(row)
        actions = build_actions(row)
        if actions:
            open_center(row, actions)

    def context_menu(position) -> None:
        row = table.rowAt(position.y())
        if row < 0:
            return
        table.selectRow(row)
        actions = build_actions(row)
        if not actions:
            return
        menu = QMenu(table)
        for action in actions:
            qaction = QAction(action.label, menu)
            if action.icon:
                qaction.setIcon(make_icon(action.icon, active_tokens()["text"], 16))
            qaction.setEnabled(action.enabled)
            qaction.triggered.connect(lambda _checked=False, callback=action.callback: callback())
            menu.addAction(qaction)
        menu.exec(table.viewport().mapToGlobal(position))
        menu.deleteLater()

    table.cellClicked.connect(clicked)
    table.setContextMenuPolicy(Qt.CustomContextMenu)
    table.customContextMenuRequested.connect(context_menu)
