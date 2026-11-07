from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget

from app.models.item_table_model import ItemTableModel
from app.services.api_proposal_storage import _api_warehouse_item_row_to_process_item
from app.ui import warehouse_items_page as page_module
from app.ui.main_window import MainWindow
from app.ui.process_page import ProcessPage
from app.ui.refresh_coordinator import RefreshCoordinator
from app.ui.warehouse_items_page import WarehouseAreaPage, WarehouseItemsPage, summary_text
from test_visual_pages import FakeService as ProposalService

API_ITEM = {
    "proposal_id": 7, "proposal_number": "CP 05515", "customer_name": "MNS ENGENHARIA", "item_number": "2",
    "product_code": "300.23", "description": "PARAFUSO M8", "quantity": "10.0000", "unit": "UN", "total_weight": "1.5",
    "warehouse_status": "SEPARADO",
}


def _item(**changes) -> dict:
    return _api_warehouse_item_row_to_process_item({**API_ITEM, **changes})


def _sync_worker(owner, operation, on_success, on_error, *, operation_name=None):
    try:
        result = operation()
    except Exception as exc:  # noqa: BLE001 - igual ao worker real: o erro vai para on_error
        on_error(exc)
    else:
        on_success(result)


class FakeWarehouseService(ProposalService):
    """Servico completo para as duas abas: sem metodo faltando, nenhum QMessageBox real abre."""

    def __init__(self, items=None):
        super().__init__(["EM_SEPARACAO", "SEPARADO"])
        self.items = list(items if items is not None else [_item()])
        self.item_calls: list[dict] = []
        self.item_error: Exception | None = None
        self.pending = 0

    def warehouse_items_queue(self, filters=None):
        self.item_calls.append(dict(filters or {}))
        if self.item_error is not None:
            raise self.item_error
        return list(self.items)

    def warehouse_pending_count(self):
        return self.pending

    def area_status_label(self, _area, status):
        return {"SEPARADO": "Separado", "EM_SEPARACAO": "Em separação"}.get(status, status)

    def can_edit(self, _area):
        return True


class QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])


class ItemRowTests(unittest.TestCase):
    def test_summary_counts_items_and_proposals(self):
        self.assertEqual(summary_text([]), "")
        self.assertEqual(summary_text([_item()]), "1 item em 1 proposta")
        self.assertEqual(summary_text([_item(), _item(item_number="3"), _item(proposal_id=8, proposal_number="CP2")]), "3 itens em 2 propostas")


class ItemsPageTests(QtCase):
    def _page(self, service=None):
        service = service or FakeWarehouseService()
        page = WarehouseItemsPage(service)
        page._refresh_coordinator = RefreshCoordinator(page, start_worker=_sync_worker)
        return page, service

    def test_refresh_loads_rows_into_the_table_with_unit_and_status(self):
        page, service = self._page()
        page.refresh()
        self.assertEqual(service.item_calls, [{"text": None}])
        model = page.table.model()
        self.assertEqual(model.rowCount(), 1)
        cells = {model.columns[c][0]: model.index(0, c).data() for c in range(model.columnCount())}
        self.assertEqual(cells["proposta"], "CP 05515")
        self.assertEqual(cells["quantidade"], "10 UN")
        self.assertEqual(cells["status_almoxarifado_item"], "Separado")
        self.assertEqual(page.count_label.text(), "1 item em 1 proposta")
        self.assertIs(page.table_stack.currentWidget(), page.table)

    def test_no_rows_shows_the_empty_state(self):
        page, _ = self._page(FakeWarehouseService(items=[]))
        page.refresh()
        self.assertIs(page.table_stack.currentWidget(), page.empty_state)
        self.assertEqual(page.count_label.text(), "")

    def test_search_text_goes_to_the_service(self):
        page, service = self._page()
        page.search.setText("  CP7 ")
        page.refresh()
        self.assertEqual(service.item_calls[-1], {"text": "CP7"})
        page.clear()
        self.assertEqual(service.item_calls[-1], {"text": None})

    def test_error_is_reported_and_the_page_unlocks(self):
        service = FakeWarehouseService()
        service.item_error = RuntimeError("API fora")
        page, _ = self._page(service)
        with patch.object(page_module, "show_operation_error") as show:
            page.refresh()
        show.assert_called_once()
        self.assertTrue(page.table.isEnabled())

    def test_details_without_selection_warns_and_with_selection_opens_the_proposal(self):
        page, _ = self._page()
        page.refresh()
        with patch.object(page_module, "ToastNotification") as toast, patch.object(page_module, "ProcessDetailDialog") as dialog:
            page.open_proposal_details()
            toast.assert_called_once()
            dialog.assert_not_called()
            page.table.selectRow(0)
            dialog.return_value.exec.return_value = 0
            dialog.return_value.changed = False
            page.open_proposal_details()
        dialog.assert_called_once_with(page.service, 7, page, area="ALMOXARIFADO")

    def test_item_model_has_the_warehouse_columns(self):
        model = ItemTableModel(FakeWarehouseService(), "ALMOXARIFADO")
        self.assertEqual([key for key, _label in model.columns][0], "proposta")
        self.assertEqual(model.columns[page_module._DESCRIPTION_COLUMN][0], "descricao")


class AreaPageTests(QtCase):
    def _area_page(self):
        service = FakeWarehouseService()
        page = WarehouseAreaPage(service)
        # Sem thread de verdade: uma thread ainda viva no fim do teste derruba o Qt ao encerrar.
        for tab in (page.items_page, page.proposals_page):
            tab._refresh_coordinator = RefreshCoordinator(tab, start_worker=_sync_worker)
        return page, service

    def test_has_a_proposals_tab_and_an_items_tab(self):
        page, _ = self._area_page()
        self.assertEqual([page.tabs.tabText(i) for i in range(page.tabs.count())], ["Propostas", "Itens"])
        self.assertIsInstance(page.proposals_page, ProcessPage)
        self.assertEqual(page.proposals_page.area, "ALMOXARIFADO")
        self.assertIsInstance(page.items_page, WarehouseItemsPage)
        self.assertIs(page.tabs.currentWidget(), page.proposals_page)

    def test_switching_to_the_items_tab_refreshes_it(self):
        page, service = self._area_page()
        self.assertEqual(service.item_calls, [])
        page.tabs.setCurrentIndex(1)
        self.assertEqual(len(service.item_calls), 1)

    def test_refresh_reloads_only_the_visible_tab(self):
        page, service = self._area_page()
        page.refresh()
        self.assertEqual(service.item_calls, [])
        page.tabs.setCurrentIndex(1)
        service.item_calls.clear()
        page.refresh()
        self.assertEqual(len(service.item_calls), 1)

    def test_leaving_the_proposals_tab_turns_off_its_transient_modes(self):
        page, _ = self._area_page()
        with patch.object(page.proposals_page, "deactivate_transient_modes") as deactivate:
            page.tabs.setCurrentIndex(1)
        deactivate.assert_called_once()
        with patch.object(page.proposals_page, "deactivate_transient_modes") as deactivate:
            page.deactivate_transient_modes()
        deactivate.assert_called_once()


class MainWindowRegistrationTests(QtCase):
    def test_almoxarifado_is_registered_as_the_two_tab_page(self):
        service = FakeWarehouseService()
        service.visible_areas = lambda: ["ALMOXARIFADO"]
        service.user_profile = lambda: "Usuario"
        service.saved_reports = lambda: []
        window = SimpleNamespace(service=service, pages={}, stack=QStackedWidget(), _can_view=lambda *_args: False)
        with patch("app.ui.main_window.DataPage", lambda *_args, **_kwargs: QWidget()):
            MainWindow._create_pages(window)
        self.assertIsInstance(window.pages["ALMOXARIFADO"], WarehouseAreaPage)


if __name__ == "__main__":
    unittest.main()
