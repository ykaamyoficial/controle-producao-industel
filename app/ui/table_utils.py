from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem


def item_product_code(row: dict[str, Any] | None) -> str:
    if not row:
        return "-"
    for key in ("codigo_produto", "product_code", "codigo", "cod_produto"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return "-"


def table_text(value: Any) -> str:
    if value in (None, ""):
        return "-"
    return str(value)


def make_cell(value: Any, *, align: Qt.AlignmentFlag | Qt.Alignment = Qt.AlignVCenter | Qt.AlignLeft) -> QTableWidgetItem:
    cell = QTableWidgetItem(table_text(value))
    cell.setTextAlignment(align)
    return cell


def configure_wrapping_table(
    table: QTableWidget,
    *,
    description_columns: tuple[int, ...] = (),
    code_columns: tuple[int, ...] = (),
    min_row_height: int = 42,
) -> None:
    table.setWordWrap(True)
    table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    table.verticalHeader().setDefaultSectionSize(min_row_height)
    for column in description_columns:
        if 0 <= column < table.columnCount():
            table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Stretch)
    for column in code_columns:
        if 0 <= column < table.columnCount():
            table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)


def resize_rows_to_contents(table: QTableWidget) -> None:
    table.resizeRowsToContents()
