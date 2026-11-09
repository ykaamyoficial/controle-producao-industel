from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import load_workbook
from PySide6.QtWidgets import QApplication

from app.ui import logistics_page as page_module
from app.ui.components.badge_delegate import BADGE_ROLE
from app.ui.logistics_dialogs import category_colors
from app.ui.logistics_page import LogisticsPage
from test_logistics_desktop import FakeLogisticsApi, FakeService, _log, _sync_worker


class CappedApi(FakeLogisticsApi):
    """Filtra como a API (etapa, estado, carga, busca) e corta cada pagina em 100, como o limite real."""

    def list_logs(self, *, search="", stage=None, state=None, in_load=None, limit=100, offset=0, **_kwargs):
        self.calls.append(("list_logs", {"search": search, "stage": stage, "state": state, "in_load": in_load, "limit": limit, "offset": offset}))
        if self.error is not None:
            raise self.error
        rows = [
            log for log in self.logs
            if (not stage or (log.get("display_stage") or log["stage"]) == stage)
            and (not state or log["state"] == state)
            and (in_load is None or bool(log.get("load_id")) == in_load)
            and (not search or search.lower() in log["code"].lower())
        ]
        page = rows[offset:offset + min(limit, 100)]
        return {"items": page, "total": len(rows)}


def _three_logs():
    return [
        _log(id=1, code="LOG101", stage="reservada", state="EQT-MA"),
        _log(id=2, code="LOG102", stage="aprovada", state="EQT-PA", load_id=5, load_code="CE-01"),
        _log(id=3, code="LOG103", stage="aprovada", display_stage="entregue", state="EQT-MA", load_id=5, load_code="CE-01", delivered_on="2026-11-09"),
    ]


class LogListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        item = patch.object(page_module, "start_worker", _sync_worker)
        item.start()
        self.addCleanup(item.stop)

    def _page(self, logs=None):
        api = CappedApi(logs=logs if logs is not None else _three_logs())
        page = LogisticsPage(FakeService(api))
        page.refresh()
        return page, api

    def _codes(self, page):
        return [page.logs_table.item(row, 0).text() for row in range(page.logs_table.rowCount())]

    def test_states_come_from_the_api(self):
        page, _api = self._page()
        self.assertEqual([page.state_filter.itemText(i) for i in range(page.state_filter.count())], ["Todos os estados", "EQT-MA", "EQT-PA"])

    def test_stage_filter_entregue_and_footer(self):
        page, api = self._page()
        self.assertEqual(page.count_label.text(), "3 LOGs")
        page.stage_filter.setCurrentIndex(page.stage_filter.findData("entregue"))
        self.assertEqual(self._codes(page), ["LOG103"])
        self.assertEqual(page.count_label.text(), "1 LOGs")
        self.assertEqual(api.calls[-1][1]["stage"], "entregue")
        self.assertEqual(page.logs_table.item(0, 5).text(), "Entregue")
        self.assertEqual(page.logs_table.item(0, 6).text(), "4 dias (2 úteis)")
        self.assertEqual(page.logs_table.item(0, 5).data(BADGE_ROLE), category_colors("final_done", page.service.palette))
        self.assertEqual(page.tabs._options[0], ("logs", "LOGs", 3))

    def test_combines_stage_state_and_load_with_search(self):
        page, _api = self._page()
        page.stage_filter.setCurrentIndex(page.stage_filter.findData("aprovada"))
        page.state_filter.setCurrentIndex(page.state_filter.findData("EQT-PA"))
        self.assertEqual(self._codes(page), ["LOG102"])
        page.state_filter.setCurrentIndex(0)
        page.load_filter.setCurrentIndex(page.load_filter.findData(False))
        self.assertEqual(self._codes(page), [])
        self.assertIs(page.stack.currentWidget(), page.empty_state)
        page.stage_filter.setCurrentIndex(0)
        page.load_filter.setCurrentIndex(page.load_filter.findData(True))
        page.search.setText("103")
        page._filters_changed()
        self.assertEqual(self._codes(page), ["LOG103"])
        self.assertEqual(page.count_label.text(), "1 LOGs")

    def test_without_load_filter(self):
        page, _api = self._page()
        page.load_filter.setCurrentIndex(page.load_filter.findData(False))
        self.assertEqual(self._codes(page), ["LOG101"])
        self.assertEqual(page.count_label.text(), "1 LOGs")

    def test_clear_filters_restores_everything(self):
        page, _api = self._page()
        page.stage_filter.setCurrentIndex(page.stage_filter.findData("entregue"))
        page.state_filter.setCurrentIndex(page.state_filter.findData("EQT-MA"))
        page.clear_filters()
        self.assertEqual(page.stage_filter.currentIndex(), 0)
        self.assertEqual(page.state_filter.currentIndex(), 0)
        self.assertEqual(page.count_label.text(), "3 LOGs")

    def test_filters_hidden_on_loads_tab(self):
        page, _api = self._page()
        page.tabs.set_current_key("loads")
        self.assertTrue(page.stage_filter.isHidden())
        self.assertTrue(page.export_button.isHidden())
        page.tabs.set_current_key("logs")
        self.assertFalse(page.stage_filter.isHidden())

    def test_export_writes_every_page_of_the_filter(self):
        logs = [_log(id=i, code=f"LOG{i:04d}", state="EQT-MA") for i in range(1, 231)] + [_log(id=999, code="OUTRO", state="EQT-PA")]
        page, _api = self._page(logs)
        page.state_filter.setCurrentIndex(page.state_filter.findData("EQT-MA"))
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "lista.xlsx")
            with patch("app.ui.logistics_page.QFileDialog.getSaveFileName", return_value=(path, "")), \
                    patch("app.ui.logistics_page.open_file") as opened:
                page.export_logs()
            opened.assert_called_once()
            sheet = load_workbook(path).active
            self.assertEqual(sheet.max_row, 231)
            self.assertEqual(sheet["A2"].value, "LOG0001")
            self.assertEqual(sheet["A231"].value, "LOG0230")
        self.assertTrue(all(c[1].get("state") in (None, "EQT-MA") for c in _api.calls if c[0] == "list_logs"))

    def test_export_cancelled_does_not_fetch(self):
        page, api = self._page()
        before = len(api.calls)
        with patch("app.ui.logistics_page.QFileDialog.getSaveFileName", return_value=("", "")):
            page.export_logs()
        self.assertEqual(len(api.calls), before)

    def test_export_failure_warns(self):
        page, api = self._page()
        api.error = RuntimeError("servidor fora do ar")
        with patch("app.ui.logistics_page.QFileDialog.getSaveFileName", return_value=("x.xlsx", "")), \
                patch("app.ui.logistics_page.QMessageBox.warning") as warning:
            page.export_logs()
        warning.assert_called_once()
