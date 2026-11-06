from __future__ import annotations

import time
import unittest

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QLabel

from app.ui.process_detail.inspecao_logistica_tab import fetch_inspection_logistics
from tests.test_process_detail_dialog import FakeDetailService, ProcessDetailDialog

TAB = "Inspeção e Logística"


class FakeInspection:
    def __init__(self, fail=False):
        self.fail = fail

    def list_inspections(self, **kw):
        if self.fail:
            raise RuntimeError("403")
        return {"items": [
            {"id": 1, "pd_code": "PD-100", "proposal_numbers": ["CP 05389"], "nqt_code": "NQT-9", "stage": "doc",
             "days_in_stage": 4, "doc_link": "https://doc.example/x", "finished": False},
            {"id": 2, "pd_code": "PD-200", "proposal_numbers": ["CP 053890"], "stage": "fim", "days_in_stage": 1, "finished": True},
        ]}


class FakeLogistics:
    def list_logs(self, **kw):
        return {"items": [{"id": 7, "code": "LOG7", "state": "SP", "stage": "aprovada", "loading_date": "2026-09-01",
                           "delivery_date": "2026-09-03", "load_code": "CE-12", "proposal_count": 1},
                          {"id": 8, "code": "LOG8", "state": "RJ", "stage": "docs", "loading_date": "2026-09-01",
                           "delivery_date": "2026-09-03", "load_code": None, "proposal_count": 1}]}

    def get_log(self, log_id):
        return {"items": [{"proposal_number": "CP 05389" if log_id == 7 else "CP 053890"}]}


class Service(FakeDetailService):
    def __init__(self, views=("inspection", "logistics"), fail=False):
        super().__init__()
        self.views = views
        self.fail = fail

    def can_view(self, area):
        return area in self.views

    def inspection_service(self):
        return FakeInspection(self.fail)

    def logistics_service(self):
        return FakeLogistics()


class InspectionLogisticsTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _open(self, service):
        dialog = ProcessDetailDialog(service, service.process["id"], None)
        deadline = time.monotonic() + 5
        while dialog.inspecao_logistica_tab is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
            tab = dialog.inspecao_logistica_tab
            texts = " ".join(label.text() for label in tab.findChildren(QLabel))
            if "Carregando" not in texts and dialog.process:
                break
        self.addCleanup(self._close, dialog)
        return dialog

    def _close(self, dialog):
        for thread in dialog.findChildren(QThread):
            thread.quit()
            thread.wait(2000)
        dialog.deleteLater()

    @staticmethod
    def _texts(dialog):
        return [label.text() for label in dialog.inspecao_logistica_tab.findChildren(QLabel)]

    def test_exact_proposal_match_only(self):
        result = fetch_inspection_logistics(Service(), ["CP 05389"], inspection=True, logistics=True)
        self.assertEqual([i["id"] for i in result["inspection"]["data"]], [1])
        self.assertEqual([i["code"] for i in result["logistics"]["data"]], ["LOG7"])

    def test_no_view_permission_hides_tab(self):
        dialog = self._open(Service(views=()))
        self.assertIsNone(dialog.inspecao_logistica_tab)
        self.assertNotIn(TAB, [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())])

    def test_tab_is_last_and_shows_data(self):
        dialog = self._open(Service())
        self.assertEqual(dialog.tabs.tabText(dialog.tabs.count() - 1), TAB)
        texts = self._texts(dialog)
        for expected in ("PD-100", "NQT-9", "4 d", "LOG7", "CE-12", "01/09/2026", "03/09/2026"):
            self.assertIn(expected, texts)

    def test_only_logistics_permission_has_no_inspection_section(self):
        dialog = self._open(Service(views=("logistics",)))
        self.assertIsNone(dialog.inspecao_logistica_tab.inspection_panel)
        self.assertIn("LOG7", self._texts(dialog))

    def test_inspection_error_is_discreet_and_logistics_still_loads(self):
        dialog = self._open(Service(fail=True))
        texts = self._texts(dialog)
        self.assertIn("Não foi possível carregar estes dados agora.", texts)
        self.assertIn("LOG7", texts)


if __name__ == "__main__":
    unittest.main()
