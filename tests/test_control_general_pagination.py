from __future__ import annotations

import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.services import backend_adapter
from app.services.backend_adapter import CONTROL_GENERAL_PAGE_SIZE, AppError, BackendService
from app.ui.process_page import ProcessPage
from tests.test_process_batch_selection import FakeProductionService, _run_synchronously


def _row(index: int) -> dict:
    return {
        "id": index, "proposta": f"CP{index:05d}", "cliente": f"Cliente {index % 7}", "obra_site": "Site", "lote": "L1",
        "status_producao": "INICIADO", "prazo_entrega": "", "prazo_bucket": "",
    }


class FakeGeneralService(FakeProductionService):
    """445 propostas: 3 paginas de 200 (200, 200, 45)."""

    def __init__(self, total: int = 445):
        super().__init__()
        self.all_rows = [_row(index) for index in range(1, total + 1)]
        self.page_calls: list[tuple[dict, int]] = []

    def visible_areas(self):
        return ["CONTROLE GERAL"]

    def control_general_page(self, filters=None, *, page=0, page_size=CONTROL_GENERAL_PAGE_SIZE):
        filters = dict(filters or {})
        self.page_calls.append((filters, page))
        needle = str(filters.get("text") or "").upper()
        rows = [row for row in self.all_rows if not needle or needle in row["proposta"] or needle in row["cliente"].upper()]
        return {"items": rows[page * page_size : (page + 1) * page_size], "total": len(rows), "page": page, "page_size": page_size}


class ControlGeneralPagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _page(self, service=None, area="CONTROLE GERAL"):
        service = service or FakeGeneralService()
        page = ProcessPage(service, area, "Controle Geral")
        with patch("app.ui.process_page.start_worker", side_effect=_run_synchronously):
            page.refresh()
        return page, service

    def _click(self, button):
        with patch("app.ui.process_page.start_worker", side_effect=_run_synchronously):
            button.click()

    def test_first_page_shows_200_rows_and_the_totals(self):
        page, service = self._page()
        self.assertFalse(page.pager.isHidden())
        self.assertEqual(page.model.rowCount(), 200)
        self.assertEqual(page.page_label.text(), "Página 1 de 3  |  445 propostas")
        self.assertFalse(page.previous_page_btn.isEnabled())
        self.assertTrue(page.next_page_btn.isEnabled())
        self.assertEqual(service.page_calls[-1][1], 0)

    def test_next_and_previous_walk_through_the_pages(self):
        page, service = self._page()
        self._click(page.next_page_btn)
        self.assertEqual(page.page_label.text(), "Página 2 de 3  |  445 propostas")
        self.assertEqual(page.model.process_id_at(0), 201)
        self.assertTrue(page.previous_page_btn.isEnabled())
        self._click(page.next_page_btn)
        self.assertEqual(page.model.rowCount(), 45)
        self.assertEqual(page.page_label.text(), "Página 3 de 3  |  445 propostas")
        self.assertFalse(page.next_page_btn.isEnabled())
        self._click(page.next_page_btn)  # desabilitado: nao sai da ultima pagina
        self.assertEqual(service.page_calls[-1][1], 2)
        self._click(page.previous_page_btn)
        self.assertEqual(page.page_label.text(), "Página 2 de 3  |  445 propostas")

    def test_search_goes_to_the_service_and_returns_to_the_first_page(self):
        page, service = self._page()
        self._click(page.next_page_btn)
        page.search.setText("CP00444")
        with patch("app.ui.process_page.start_worker", side_effect=_run_synchronously):
            page.refresh()
        filters, requested_page = service.page_calls[-1]
        self.assertEqual((filters["text"], requested_page), ("CP00444", 0))
        # A proposta esta na 3a pagina da lista completa e mesmo assim e encontrada.
        self.assertEqual(page.model.rowCount(), 1)
        self.assertEqual(page.model.process_id_at(0), 444)
        self.assertEqual(page.page_label.text(), "Página 1 de 1  |  1 propostas")

    def test_refresh_without_filter_change_keeps_the_current_page(self):
        page, service = self._page()
        self._click(page.next_page_btn)
        with patch("app.ui.process_page.start_worker", side_effect=_run_synchronously):
            page.refresh()
        self.assertEqual(service.page_calls[-1][1], 1)
        self.assertEqual(page.page_label.text(), "Página 2 de 3  |  445 propostas")

    def test_clear_returns_to_the_first_page(self):
        page, service = self._page()
        page.search.setText("cliente 3")
        with patch("app.ui.process_page.start_worker", side_effect=_run_synchronously):
            page.refresh()
            page.clear()
        self.assertEqual(service.page_calls[-1], ({"text": "", "cliente": "", "status": "", "prazo": ""}, 0))
        self.assertEqual(page.page_label.text(), "Página 1 de 3  |  445 propostas")

    def test_list_that_shrank_falls_back_to_the_last_valid_page(self):
        page, service = self._page()
        self._click(page.next_page_btn)
        self._click(page.next_page_btn)
        service.all_rows = service.all_rows[:150]
        with patch("app.ui.process_page.start_worker", side_effect=_run_synchronously):
            page.refresh()
            # O novo pedido nasce dentro do retorno do anterior; o coordenador o dispara em seguida.
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not page.page_label.text().startswith("Página 1 de 1"):
                self.app.processEvents()
                time.sleep(0.01)
        self.assertEqual(page.page_label.text(), "Página 1 de 1  |  150 propostas")
        self.assertEqual(page.model.rowCount(), 150)

    def test_empty_result_shows_a_single_page(self):
        page, _service = self._page(FakeGeneralService(total=0))
        self.assertEqual(page.page_label.text(), "Página 1 de 1  |  0 propostas")
        self.assertFalse(page.previous_page_btn.isEnabled())
        self.assertFalse(page.next_page_btn.isEnabled())

    def test_other_areas_and_services_without_paging_have_no_pager(self):
        page, service = self._page(area="PRODUCAO")
        self.assertTrue(page.pager.isHidden())
        self.assertEqual(service.page_calls, [])
        legacy = FakeProductionService()
        legacy_page = ProcessPage(legacy, "CONTROLE GERAL", "Controle Geral")
        self.assertTrue(legacy_page.pager.isHidden())
        with patch("app.ui.process_page.start_worker", side_effect=_run_synchronously):
            legacy_page.refresh()
        self.assertEqual(legacy_page.model.rowCount(), 3)


class ControlGeneralPageServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = BackendService.__new__(BackendService)
        self.calls: list[dict] = []
        self.payload = {"items": [{"id": 1, "proposta": "CP1", "cliente": "Alfa", "obra_site": "Obra", "lote": "L1"}], "total": 401}
        self.service.official_proposal_storage = SimpleNamespace(list_proposals_page=self._list)

    def _list(self, **filters):
        self.calls.append(filters)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    def test_requests_the_page_with_search_and_newest_first(self):
        result = self.service.control_general_page({"text": " alfa ", "cliente": "", "status": "EM_PRODUCAO", "prazo": ""}, page=2)
        self.assertEqual(
            self.calls,
            [{"customer": None, "current_status": "EM_PRODUCAO", "search": "alfa", "sort_by": "updated_at", "sort_dir": "desc", "limit": 200, "offset": 400}],
        )
        self.assertEqual((result["total"], result["page"], result["page_size"], len(result["items"])), (401, 2, 200, 1))

    def test_children_are_dropped_and_old_api_without_search_is_filtered_locally(self):
        self.payload = {
            "items": [
                {"id": 1, "proposta": "CP1", "cliente": "Alfa"},
                {"id": 2, "proposta": "CP2", "cliente": "Beta"},
                {"id": 3, "proposta": "CP3", "cliente": "Alfa", "parent_proposal_id": 1},
            ],
            "total": 3,
        }
        result = self.service.control_general_page({"text": "alfa"})
        self.assertEqual([row["id"] for row in result["items"]], [1])

    def test_same_request_within_two_seconds_is_served_from_cache(self):
        self.service.control_general_page({"text": "x"}, page=0)
        self.service.control_general_page({"text": "x"}, page=0)
        self.service.control_general_page({"text": "x"}, page=1)
        self.assertEqual(len(self.calls), 2)

    def test_negative_page_is_clamped_and_missing_total_falls_back_to_the_rows(self):
        self.payload = {"items": [{"id": 1, "proposta": "CP1"}], "total": None}
        result = self.service.control_general_page({}, page=-3)
        self.assertEqual((self.calls[0]["offset"], result["page"], result["total"]), (0, 0, 1))

    def test_api_error_becomes_an_app_error(self):
        self.payload = RuntimeError("api fora")
        with patch.object(backend_adapter, "user_message_for_api_error", return_value="Falha"):
            with self.assertRaises(AppError):
                self.service.control_general_page({})


if __name__ == "__main__":
    unittest.main()
