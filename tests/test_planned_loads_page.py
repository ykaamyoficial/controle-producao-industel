from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.ui.planned_loads_page import PlannedLoadsPage


def _run_synchronously(_owner, operation, on_success, on_error, **_kwargs):
    # `RefreshCoordinator.request(..., immediate=True)` normally hands off to
    # `start_worker`, which runs the loader on a real QThread and delivers the
    # result via a queued signal (i.e. only once the event loop is pumped
    # again). Patching `start_worker` itself to run inline keeps the whole
    # loader/success/error cycle synchronous for the test.
    try:
        result = operation()
    except Exception as exc:
        on_error(exc)
    else:
        on_success(result)
    return None


class FakePlannedLoadService:
    def __init__(self, *, can_edit: bool = True):
        self._can_edit = can_edit
        self.rows = [
            {
                "id": 1,
                "code": "PL-0001",
                "status": "Planejamento",
                "expected_ship_date": "2026-08-25",
                "carrier_name": "Transportes Ana",
                "responsible_user_name": "Bruno",
                "total_planned_quantity": "10",
                "total_available_quantity": "6",
                "total_missing_quantity": "4",
                "version": 1,
            },
            {
                "id": 2,
                "code": "PL-0002",
                "status": "Pronta para montar",
                "expected_ship_date": "2026-08-20",
                "carrier_name": "Transportes Bia",
                "responsible_user_name": "Carla",
                "total_planned_quantity": "5",
                "total_available_quantity": "5",
                "total_missing_quantity": "0",
                "version": 1,
            },
        ]
        self.palette = {"danger": "#dc2626", "text": "#0f172a"}
        self.detail_calls: list[int] = []

    def can_edit(self, area):
        return self._can_edit

    def planned_loads_page(self, **filters):
        rows = self.rows
        search = filters.get("search")
        if search:
            needle = search.lower()
            rows = [row for row in rows if needle in row["code"].lower()]
        status = filters.get("status")
        if status:
            rows = [row for row in rows if row["status"] == status]
        return {"items": rows, "total": len(rows), "limit": 200, "offset": 0}

    def planned_load_detail(self, planned_load_id):
        self.detail_calls.append(planned_load_id)
        row = next(item for item in self.rows if item["id"] == planned_load_id)
        return {**row, "items": [], "history": []}


class PlannedLoadsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.service = FakePlannedLoadService()

    def _build_page(self, service=None):
        with patch("app.ui.planned_loads_page.start_worker", side_effect=_run_synchronously):
            page = PlannedLoadsPage(service or self.service)
        return page

    def test_refresh_populates_table_from_service(self):
        page = self._build_page()
        with patch("app.ui.planned_loads_page.start_worker", side_effect=_run_synchronously):
            page.refresh()
        self.assertEqual(page.model.rowCount(), 2)
        self.assertEqual(page.model.load_id_at(0), 1)
        self.assertEqual(page.model.load_id_at(1), 2)
        self.assertFalse(page.loading.isVisible())

    def test_refresh_applies_search_and_status_filters(self):
        page = self._build_page()
        page.search.setText("PL-0002")
        with patch("app.ui.planned_loads_page.start_worker", side_effect=_run_synchronously):
            page.refresh()
        self.assertEqual(page.model.rowCount(), 1)
        self.assertEqual(page.model.load_id_at(0), 2)

    def test_new_button_hidden_when_user_cannot_edit(self):
        service = FakePlannedLoadService(can_edit=False)
        page = self._build_page(service)
        # `isVisible()` reflete a visibilidade real na tela (sempre False
        # para um widget top-level nunca exibido via `.show()`, independente
        # de `setVisible`); `isHidden()` reflete so o flag explicito deste
        # widget, que e o que `_build()` de fato manipula aqui.
        self.assertTrue(page.new_button.isHidden())

    def test_new_button_visible_when_user_can_edit(self):
        page = self._build_page()
        self.assertFalse(page.new_button.isHidden())

    def test_open_selected_without_selection_shows_warning(self):
        page = self._build_page()
        with patch("app.ui.planned_loads_page.QMessageBox.warning") as warning:
            page.open_selected()
        warning.assert_called_once()

    def test_open_selected_opens_dialog_for_selected_row(self):
        page = self._build_page()
        with patch("app.ui.planned_loads_page.start_worker", side_effect=_run_synchronously):
            page.refresh()
        page.table.selectRow(1)

        opened_ids = []

        class FakeDialog:
            def __init__(self, service, planned_load_id=None, parent=None):
                opened_ids.append(planned_load_id)

            def exec(self):
                return 0

        with patch("app.ui.planned_loads_page.PlannedLoadDialog", FakeDialog):
            page.open_selected()

        self.assertEqual(opened_ids, [2])

    def test_double_click_opens_dialog_and_accept_triggers_refresh(self):
        page = self._build_page()
        with patch("app.ui.planned_loads_page.start_worker", side_effect=_run_synchronously):
            page.refresh()

        refresh_calls = []
        original_refresh = page.refresh

        def spy_refresh(*args, **kwargs):
            refresh_calls.append(True)
            return original_refresh(*args, **kwargs)

        page.refresh = spy_refresh

        class FakeAcceptingDialog:
            def __init__(self, service, planned_load_id=None, parent=None):
                self.planned_load_id = planned_load_id

            def exec(self):
                return 1

        with patch("app.ui.planned_loads_page.PlannedLoadDialog", FakeAcceptingDialog), patch(
            "app.ui.planned_loads_page.start_worker", side_effect=_run_synchronously
        ):
            page._open_from_index(page.model.index(0, 0))

        self.assertEqual(refresh_calls, [True])

    def test_refresh_sets_divergence_badge_count_from_missing_quantity(self):
        page = self._build_page()
        with patch("app.ui.planned_loads_page.start_worker", side_effect=_run_synchronously):
            page.refresh()
        # So a linha "PL-0001" tem total_missing_quantity="4" (> 0);
        # "PL-0002" tem "0" -- nao entra na contagem (FASE_PL6).
        from app.ui.components.count_badge import format_count_badge

        self.assertEqual(format_count_badge(page.divergence_badge._badge_count), "1")

    def test_refresh_with_no_divergence_hides_badge_count(self):
        service = FakePlannedLoadService()
        service.rows = [row for row in service.rows if row["id"] != 1]
        page = self._build_page(service)
        with patch("app.ui.planned_loads_page.start_worker", side_effect=_run_synchronously):
            page.refresh()
        from app.ui.components.count_badge import format_count_badge

        self.assertEqual(format_count_badge(page.divergence_badge._badge_count), "")

    def test_refresh_error_resets_divergence_badge(self):
        page = self._build_page()
        with patch("app.ui.planned_loads_page.start_worker", side_effect=_run_synchronously):
            page.refresh()
        from app.ui.components.count_badge import format_count_badge

        self.assertEqual(format_count_badge(page.divergence_badge._badge_count), "1")

        def failing_page(**_filters):
            raise RuntimeError("falha de rede")

        service_with_failure = self.service
        service_with_failure.planned_loads_page = failing_page
        with patch("app.ui.planned_loads_page.start_worker", side_effect=_run_synchronously), patch(
            "app.ui.planned_loads_page.QMessageBox.critical"
        ):
            page.refresh()
        self.assertEqual(format_count_badge(page.divergence_badge._badge_count), "")

    def test_open_new_planned_load_refreshes_when_dialog_accepted(self):
        page = self._build_page()

        class FakeAcceptingDialog:
            def __init__(self, service, planned_load_id=None, parent=None):
                pass

            def exec(self):
                return 1

        with patch("app.ui.planned_loads_page.PlannedLoadDialog", FakeAcceptingDialog), patch(
            "app.ui.planned_loads_page.start_worker", side_effect=_run_synchronously
        ):
            page.open_new_planned_load()

        self.assertEqual(page.model.rowCount(), 2)


if __name__ == "__main__":
    unittest.main()
