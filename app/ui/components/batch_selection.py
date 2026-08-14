from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from PySide6.QtCore import QObject, QRect, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QHeaderView, QStyle, QStyleOptionButton


class BatchSelectionController(QObject):
    """Estado temporário e reutilizável de seleção acumulativa por ID estável."""

    active_changed = Signal(bool)
    selection_changed = Signal()

    def __init__(self, id_getter: Callable[[dict[str, Any]], int | None] | None = None, parent=None):
        super().__init__(parent)
        self._id_getter = id_getter or (lambda row: row.get("id"))
        self._active = False
        self._selected_ids: set[int] = set()
        self._selection_order: list[int] = []
        self._entity_cache: dict[int, dict[str, Any]] = {}

    @property
    def active(self) -> bool:
        return self._active

    @property
    def selected_ids(self) -> set[int]:
        return set(self._selected_ids)

    @property
    def ordered_selected_ids(self) -> list[int]:
        return [entity_id for entity_id in self._selection_order if entity_id in self._selected_ids]

    @property
    def count(self) -> int:
        return len(self._selected_ids)

    def activate(self) -> None:
        if self._active:
            return
        self._active = True
        self.active_changed.emit(True)
        self.selection_changed.emit()

    def deactivate(self, *, clear: bool = True) -> None:
        changed = False
        if clear and self._selected_ids:
            self._selected_ids.clear()
            self._selection_order.clear()
            changed = True
        if not self._active:
            if changed:
                self.selection_changed.emit()
            return
        self._active = False
        if changed:
            self.selection_changed.emit()
        self.active_changed.emit(False)

    def remember_rows(self, rows: Iterable[dict[str, Any]]) -> None:
        for row in rows:
            entity_id = self._row_id(row)
            if entity_id is not None:
                self._entity_cache[entity_id] = dict(row)

    def select(self, entity_id: int, row: dict[str, Any] | None = None) -> None:
        entity_id = int(entity_id)
        if row is not None:
            self._entity_cache[entity_id] = dict(row)
        if entity_id in self._selected_ids:
            return
        self._selected_ids.add(entity_id)
        self._selection_order.append(entity_id)
        self.selection_changed.emit()

    def deselect(self, entity_id: int) -> None:
        entity_id = int(entity_id)
        if entity_id not in self._selected_ids:
            return
        self._selected_ids.remove(entity_id)
        self._selection_order = [value for value in self._selection_order if value != entity_id]
        self.selection_changed.emit()

    def toggle(self, entity_id: int, row: dict[str, Any] | None = None) -> None:
        if self.is_selected(entity_id):
            self.deselect(entity_id)
        else:
            self.select(entity_id, row)

    def select_many(self, rows: Iterable[dict[str, Any]]) -> None:
        changed = False
        for row in rows:
            entity_id = self._row_id(row)
            if entity_id is None:
                continue
            self._entity_cache[entity_id] = dict(row)
            if entity_id not in self._selected_ids:
                self._selected_ids.add(entity_id)
                self._selection_order.append(entity_id)
                changed = True
        if changed:
            self.selection_changed.emit()

    def deselect_many(self, entity_ids: Iterable[int]) -> None:
        previous = len(self._selected_ids)
        removed = {int(entity_id) for entity_id in entity_ids}
        self._selected_ids.difference_update(removed)
        if len(self._selected_ids) != previous:
            self._selection_order = [value for value in self._selection_order if value not in removed]
            self.selection_changed.emit()

    def clear(self) -> None:
        if not self._selected_ids:
            return
        self._selected_ids.clear()
        self._selection_order.clear()
        self.selection_changed.emit()

    def is_selected(self, entity_id: int | None) -> bool:
        return entity_id is not None and int(entity_id) in self._selected_ids

    def entity(self, entity_id: int) -> dict[str, Any]:
        return dict(self._entity_cache.get(int(entity_id), {"id": int(entity_id)}))

    def selected_entities(self) -> list[dict[str, Any]]:
        return [self.entity(entity_id) for entity_id in self.ordered_selected_ids]

    def header_state(self, visible_ids: Iterable[int]) -> Qt.CheckState:
        ids = {int(entity_id) for entity_id in visible_ids}
        if not ids:
            return Qt.Unchecked
        selected = len(ids & self._selected_ids)
        if selected == 0:
            return Qt.Unchecked
        if selected == len(ids):
            return Qt.Checked
        return Qt.PartiallyChecked

    def _row_id(self, row: dict[str, Any]) -> int | None:
        value = self._id_getter(row)
        if value in (None, ""):
            return None
        return int(value)


class BatchSelectionHeader(QHeaderView):
    """Cabeçalho tri-state que opera somente sobre as linhas visíveis."""

    toggle_visible_requested = Signal(bool)

    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._batch_active = False
        self._check_state = Qt.Unchecked
        self._has_visible_rows = False

    @property
    def check_state(self) -> Qt.CheckState:
        return self._check_state

    def set_batch_state(
        self,
        active: bool,
        state: Qt.CheckState = Qt.Unchecked,
        *,
        has_visible_rows: bool = False,
    ) -> None:
        self._batch_active = bool(active)
        self._check_state = state
        self._has_visible_rows = bool(has_visible_rows)
        self.viewport().update()

    def paintSection(self, painter: QPainter, rect: QRect, logical_index: int) -> None:  # noqa: N802
        super().paintSection(painter, rect, logical_index)
        if not self._batch_active or logical_index != 0:
            return
        option = QStyleOptionButton()
        indicator = self.style().subElementRect(QStyle.SE_CheckBoxIndicator, option, self)
        option.rect = QRect(
            rect.x() + (rect.width() - indicator.width()) // 2,
            rect.y() + (rect.height() - indicator.height()) // 2,
            indicator.width(),
            indicator.height(),
        )
        option.state = QStyle.State_Enabled if self._has_visible_rows else QStyle.State_None
        if self._check_state == Qt.Checked:
            option.state |= QStyle.State_On
        elif self._check_state == Qt.PartiallyChecked:
            option.state |= QStyle.State_NoChange
        else:
            option.state |= QStyle.State_Off
        self.style().drawControl(QStyle.CE_CheckBox, option, painter, self)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        logical_index = self.logicalIndexAt(event.position().toPoint())
        if self._batch_active and self._has_visible_rows and logical_index == 0:
            self.toggle_visible_requested.emit(self._check_state != Qt.Checked)
            event.accept()
            return
        super().mousePressEvent(event)
