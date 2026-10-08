from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.integrations.api.proposals_client import ProposalsApiClient
from app.models.item_table_model import AREA_ITEM_COLUMNS, ItemTableModel
from app.services.api_proposal_storage import OfficialProposalApiStorage, _api_expedition_item_row_to_process_item
from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES, BackendService
from app.ui import expedition_items_page as page_module
from app.ui.expedition_items_page import ExpeditionAreaPage, ExpeditionItemsPage, summary_text
from app.ui.process_page import ProcessPage
from app.ui.refresh_coordinator import RefreshCoordinator

API_ROW = {
    "id": 31, "proposal_id": 7, "proposal_version": 4, "proposal_number": "CP 05515", "customer_name": "MNS ENGENHARIA",
    "project_name": "MSTRS008_A", "lot": "L1", "proposal_item_id": 311, "item_number": "2", "product_code": "300.23",
    "description": "PECA W17", "unit": "UN", "available_quantity": "12.0000", "separated_quantity": "5.0000",
    "delivered_quantity": "2.0000", "remanaged_quantity": "1.5000", "pending_quantity": "8.5000", "unit_weight": "3.5000",
    "total_weight": "42.0000", "origin": "PRODUCAO", "status": "SEPARACAO_INICIADA", "version": 9,
}


def _sync_worker(owner, operation, on_success, on_error, *, operation_name=None):
    try:
        result = operation()
    except Exception as exc:  # noqa: BLE001 - igual ao worker real: o erro vai para on_error
        on_error(exc)
    else:
        on_success(result)


class FakeItemsService:
    def __init__(self, rows=None):
        self.palette = OFFICIAL_COLOR_PALETTES["claro"]
        self.rows = list(rows if rows is not None else [_api_expedition_item_row_to_process_item(API_ROW)])
        self.calls: list[dict] = []
        self.error: Exception | None = None

    def expedition_items_queue(self, filters=None):
        self.calls.append(dict(filters or {}))
        if self.error is not None:
            raise self.error
        return list(self.rows)

    def area_status_label(self, _area, status):
        return {
            "EM_SEPARACAO": "Aguardando separação", "SEPARACAO_INICIADA": "Separação iniciada",
            "SEPARADO": "Separado", "ENTREGUE": "Entregue",
        }.get(status, status)

    def display_cell(self, _key, value, _row=None):
        return "" if value is None else str(value)

    def can_edit(self, _area):
        return True


def _page(service=None) -> tuple[ExpeditionItemsPage, FakeItemsService]:
    service = service or FakeItemsService()
    page = ExpeditionItemsPage(service)
    page._refresh_coordinator = RefreshCoordinator(page, start_worker=_sync_worker)
    return page, service


class QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])


class RowMappingTests(unittest.TestCase):
    def test_item_and_proposal_fields_reach_the_table_row(self):
        row = _api_expedition_item_row_to_process_item(API_ROW)
        self.assertEqual((row["proposta"], row["cliente"], row["obra_site"], row["lote"]), ("CP 05515", "MNS ENGENHARIA", "MSTRS008_A", "L1"))
        self.assertEqual((row["numero_item"], row["codigo_produto"], row["descricao"], row["unidade"]), ("2", "300.23", "PECA W17", "UN"))
        self.assertEqual(row["status_expedicao_item"], "SEPARACAO_INICIADA")
        self.assertEqual(row["origem_expedicao"], "PRODUCAO")
        self.assertEqual((row["api_proposal_id"], row["processo_atual_id"], row["api_proposal_version"]), (7, 7, 4))
        self.assertEqual((row["id"], row["api_expedition_item_id"], row["api_id"]), (31, 31, 311))

    def test_quantities_come_without_trailing_zeros(self):
        row = _api_expedition_item_row_to_process_item(API_ROW)
        self.assertEqual(
            (row["quantidade_disponivel"], row["quantidade_separada"], row["quantidade_entregue"], row["quantidade_remanejada"], row["saldo_pendente"]),
            ("12", "5", "2", "1.5", "8.5"),
        )
        self.assertEqual(row["peso_total"], "42")

    def test_a_row_with_missing_fields_does_not_break(self):
        row = _api_expedition_item_row_to_process_item({"id": 1})
        self.assertEqual((row["proposta"], row["descricao"], row["quantidade_disponivel"], row["saldo_pendente"]), ("", "", "0", "0"))


class TransportTests(unittest.TestCase):
    def test_client_calls_the_items_endpoint_and_drops_empty_filters(self):
        client = MagicMock()
        ProposalsApiClient(client).list_expedition_items("tok", search="abc", status=None, pending_only="false", limit=500)
        path = client.get.call_args.args[0]
        self.assertTrue(path.startswith("/api/v1/shipping/items?"))
        self.assertIn("search=abc", path)
        self.assertIn("pending_only=false", path)
        self.assertNotIn("status", path)

    def test_storage_sends_pending_only_as_true_or_false_text(self):
        storage = OfficialProposalApiStorage.__new__(OfficialProposalApiStorage)
        proposals = MagicMock()
        proposals.list_expedition_items.return_value = {"items": [API_ROW], "total": 1}
        client = MagicMock()
        storage._client = lambda: (client, proposals, "tok")
        rows = storage.expedition_items_queue(search="x", pending_only=False)
        self.assertEqual(proposals.list_expedition_items.call_args.kwargs["pending_only"], "false")
        self.assertEqual(rows[0]["proposta"], "CP 05515")
        storage.expedition_items_queue(pending_only=True)
        self.assertEqual(proposals.list_expedition_items.call_args.kwargs["pending_only"], "true")
        client.close.assert_called()

    def test_storage_fetches_every_page_up_to_the_ceiling(self):
        storage = OfficialProposalApiStorage.__new__(OfficialProposalApiStorage)
        proposals = MagicMock()
        everything = [{**API_ROW, "id": n} for n in range(620)]
        proposals.list_expedition_items.side_effect = lambda token, **kw: {
            "items": everything[kw["offset"]:kw["offset"] + kw["limit"]], "total": len(everything),
        }
        storage._client = lambda: (MagicMock(), proposals, "tok")
        rows = storage.expedition_items_queue()
        self.assertEqual(len(rows), 620)
        self.assertEqual([call.kwargs["offset"] for call in proposals.list_expedition_items.call_args_list], [0, 500])
        self.assertEqual([call.kwargs["limit"] for call in proposals.list_expedition_items.call_args_list], [500, 500])
        proposals.list_expedition_items.reset_mock()
        capped = storage.expedition_items_queue(max_rows=300)
        self.assertEqual(len(capped), 300)
        self.assertEqual(proposals.list_expedition_items.call_args.kwargs["limit"], 300)

    def test_storage_stops_on_an_empty_page(self):
        storage = OfficialProposalApiStorage.__new__(OfficialProposalApiStorage)
        proposals = MagicMock()
        proposals.list_expedition_items.return_value = {"items": [], "total": 9}
        storage._client = lambda: (MagicMock(), proposals, "tok")
        self.assertEqual(storage.expedition_items_queue(), [])
        self.assertEqual(proposals.list_expedition_items.call_count, 1)

    def test_adapter_maps_the_screen_filters_and_defaults_to_pending_only(self):
        service = BackendService.__new__(BackendService)
        storage = MagicMock()
        storage.expedition_items_queue.return_value = [{"id": 1}]
        service.official_proposal_storage = storage
        self.assertEqual(service.expedition_items_queue({"text": "beta", "status": "SEPARADO", "pending": False}), [{"id": 1}])
        storage.expedition_items_queue.assert_called_once_with(search="beta", status="SEPARADO", pending_only=False)
        storage.reset_mock()
        service.expedition_items_queue({})
        storage.expedition_items_queue.assert_called_once_with(search=None, status=None, pending_only=True)


class ModelTests(QtCase):
    def test_what_matters_most_comes_first_and_the_labels_are_accented(self):
        columns = AREA_ITEM_COLUMNS["EXPEDICAO"]
        keys = [key for key, _label in columns]
        self.assertEqual(keys[:8], [
            "proposta", "cliente", "numero_item", "codigo_produto", "descricao", "status_expedicao_item",
            "quantidade_disponivel", "saldo_pendente",
        ])
        for key in ("quantidade_separada", "quantidade_entregue", "quantidade_remanejada", "origem_expedicao", "obra_site", "lote"):
            self.assertIn(key, keys)
        labels = dict(columns)
        self.assertEqual((labels["codigo_produto"], labels["descricao"], labels["status_expedicao_item"]), ("Código", "Descrição", "Situação"))

    def test_quantities_show_the_unit_of_the_item(self):
        model = ItemTableModel(FakeItemsService(), "EXPEDICAO", [_api_expedition_item_row_to_process_item(API_ROW)])
        keys = [key for key, _label in model.columns]
        self.assertEqual(model.data(model.index(0, keys.index("quantidade_disponivel")), Qt.DisplayRole), "12 UN")
        self.assertEqual(model.data(model.index(0, keys.index("saldo_pendente")), Qt.DisplayRole), "8.5 UN")
        row = _api_expedition_item_row_to_process_item({**API_ROW, "unit": None})
        model.set_rows([row])
        self.assertEqual(model.data(model.index(0, keys.index("saldo_pendente")), Qt.DisplayRole), "8.5")

    def test_quantity_columns_sort_as_numbers(self):
        rows = [
            {"id": 1, "quantidade_disponivel": "1600"}, {"id": 2, "quantidade_disponivel": "40"}, {"id": 3, "quantidade_disponivel": "7.5"},
        ]
        model = ItemTableModel(FakeItemsService(), "EXPEDICAO", rows)
        column = [key for key, _label in model.columns].index("quantidade_disponivel")
        model.sort(column, Qt.AscendingOrder)
        self.assertEqual([row["id"] for row in model.rows], [3, 2, 1])
        model.sort(column, Qt.DescendingOrder)
        self.assertEqual([row["id"] for row in model.rows], [1, 2, 3])

    def test_status_shows_the_label_and_is_marked_as_an_expedition_status(self):
        model = ItemTableModel(FakeItemsService(), "EXPEDICAO", [_api_expedition_item_row_to_process_item(API_ROW)])
        keys = [key for key, _label in model.columns]
        column = keys.index("status_expedicao_item")
        index = model.index(0, column)
        self.assertEqual(model.data(index, Qt.DisplayRole), "Separação iniciada")
        self.assertEqual(model.data(index, Qt.UserRole + 3), "EXPEDICAO")
        saldo = model.index(0, keys.index("saldo_pendente"))
        self.assertEqual(model.data(saldo, Qt.DisplayRole), "8.5 UN")


class ItemsPageTests(QtCase):
    def test_refresh_loads_the_rows_and_counts_items_and_proposals(self):
        page, service = _page()
        page.refresh()
        self.assertEqual(page.model.rowCount(), 1)
        self.assertEqual(page.table_stack.currentWidget(), page.table)
        self.assertEqual(page.count_label.text(), "1 item em 1 proposta")
        self.assertFalse(page.loading.isVisibleTo(page))
        self.assertTrue(page.table.isEnabled())

    def test_default_filters_ask_only_for_items_with_balance_to_deliver(self):
        page, service = _page()
        page.refresh()
        self.assertEqual(service.calls[-1], {"text": None, "status": None, "pending": True})

    def test_search_status_and_pending_checkbox_travel_to_the_service(self):
        page, service = _page()
        page.search.blockSignals(True)
        page.search.setText("  300.23 ")
        page.search.blockSignals(False)
        page.status.setCurrentIndex(page.status.findData("SEPARADO"))
        self.assertEqual(service.calls[-1], {"text": "300.23", "status": "SEPARADO", "pending": True})
        page.only_pending.setChecked(False)
        self.assertEqual(service.calls[-1], {"text": "300.23", "status": "SEPARADO", "pending": False})

    def test_status_filter_offers_every_item_status_with_its_label(self):
        page, _ = _page()
        self.assertEqual(page.status.itemText(0), "Todas as situações")
        self.assertEqual(
            [page.status.itemText(i) for i in range(1, page.status.count())],
            ["Aguardando separação", "Separação iniciada", "Separado", "Entregue"],
        )

    def test_clear_resets_the_filters_and_reloads(self):
        page, service = _page()
        page.search.blockSignals(True)
        page.search.setText("abc")
        page.search.blockSignals(False)
        page.status.blockSignals(True)
        page.status.setCurrentIndex(2)
        page.status.blockSignals(False)
        page.only_pending.blockSignals(True)
        page.only_pending.setChecked(False)
        page.only_pending.blockSignals(False)
        page.clear()
        self.assertEqual(service.calls[-1], {"text": None, "status": None, "pending": True})
        self.assertEqual(page.search.text(), "")
        self.assertEqual(page.status.currentIndex(), 0)
        self.assertTrue(page.only_pending.isChecked())

    def test_no_items_shows_the_empty_state(self):
        page, _ = _page(FakeItemsService(rows=[]))
        page.refresh()
        self.assertEqual(page.table_stack.currentWidget(), page.empty_state)
        self.assertEqual(page.count_label.text(), "")

    def test_a_failed_load_reports_the_error_and_reenables_the_page(self):
        service = FakeItemsService()
        service.error = RuntimeError("API fora do ar")
        page, _ = _page(service)
        with patch.object(page_module, "show_operation_error") as report:
            page.refresh()
        report.assert_called_once()
        self.assertIsInstance(report.call_args.args[1], RuntimeError)
        self.assertTrue(page.table.isEnabled())

    def test_details_without_a_selected_item_only_warns(self):
        page, _ = _page()
        page.refresh()
        with patch.object(page_module, "ToastNotification") as toast, patch.object(page_module, "ProcessDetailDialog") as dialog:
            page.open_proposal_details()
        toast.assert_called_once()
        dialog.assert_not_called()

    def test_details_open_the_proposal_of_the_selected_item(self):
        page, service = _page()
        page.refresh()
        page.table.selectRow(0)
        with patch.object(page_module, "ProcessDetailDialog") as dialog:
            dialog.return_value.exec.return_value = 0
            dialog.return_value.changed = False
            page.open_proposal_details()
        dialog.assert_called_once_with(service, 7, page, area="EXPEDICAO")

    def test_details_refresh_the_list_when_the_dialog_changed_something(self):
        page, service = _page()
        page.refresh()
        page.table.selectRow(0)
        calls = len(service.calls)
        with patch.object(page_module, "ProcessDetailDialog") as dialog:
            dialog.return_value.exec.return_value = 0
            dialog.return_value.changed = True
            page.open_proposal_details()
        self.assertEqual(len(service.calls), calls + 1)

    def test_summary_text_counts_distinct_proposals(self):
        rows = [{"api_proposal_id": 1}, {"api_proposal_id": 1}, {"api_proposal_id": 2}]
        self.assertEqual(summary_text(rows), "3 itens em 2 propostas")
        self.assertEqual(summary_text([{"api_proposal_id": 1}]), "1 item em 1 proposta")
        self.assertEqual(summary_text([]), "")


class AreaPageTests(QtCase):
    def _area_page(self):
        from test_visual_pages import FakeService as ProposalService

        class Service(FakeItemsService, ProposalService):
            def __init__(self):
                ProposalService.__init__(self, ["NAO_LIBERADO"])
                self.rows = []
                self.calls = []
                self.error = None

            area_status_label = FakeItemsService.area_status_label

        service = Service()
        page = ExpeditionAreaPage(service)
        # Sem thread de verdade: uma thread ainda viva no fim do teste derruba o Qt ao encerrar.
        for tab in (page.items_page, page.proposals_page):
            tab._refresh_coordinator = RefreshCoordinator(tab, start_worker=_sync_worker)
        return page, service

    def test_expedition_has_a_proposals_tab_and_an_items_tab(self):
        page, _ = self._area_page()
        self.assertEqual([page.tabs.tabText(i) for i in range(page.tabs.count())], ["Propostas", "Itens em expedição"])
        self.assertIsInstance(page.proposals_page, ProcessPage)
        self.assertEqual(page.proposals_page.area, "EXPEDICAO")
        self.assertIsInstance(page.items_page, ExpeditionItemsPage)
        self.assertIs(page.tabs.currentWidget(), page.proposals_page)

    def test_opening_the_items_tab_loads_it(self):
        page, service = self._area_page()
        self.assertEqual(service.calls, [])
        page.tabs.setCurrentIndex(1)
        self.assertEqual(len(service.calls), 1)

    def test_refresh_reloads_only_the_visible_tab(self):
        page, service = self._area_page()
        page.refresh()  # aba de propostas: nao consulta itens
        self.assertEqual(service.calls, [])
        page.tabs.setCurrentIndex(1)
        service.calls.clear()
        page.refresh()
        self.assertEqual(len(service.calls), 1)

    def test_leaving_the_proposals_tab_turns_off_its_transient_modes(self):
        page, _ = self._area_page()
        with patch.object(page.proposals_page, "deactivate_transient_modes") as deactivate:
            page.tabs.setCurrentIndex(1)
        deactivate.assert_called_once()
        with patch.object(page.proposals_page, "deactivate_transient_modes") as deactivate:
            page.deactivate_transient_modes()
        deactivate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
