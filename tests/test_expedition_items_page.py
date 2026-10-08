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
from app.ui.expedition_items_page import ExpeditionAreaPage, ExpeditionItemsPage, group_by_product, summary_text
from app.ui.process_page import ProcessPage
from app.ui.refresh_coordinator import RefreshCoordinator

API_ROW = {
    "id": 31, "proposal_id": 7, "proposal_version": 4, "proposal_number": "CP 05515", "customer_name": "MNS ENGENHARIA",
    "project_name": "MSTRS008_A", "lot": "L1", "proposal_item_id": 311, "item_number": "2", "product_code": "300.23",
    "description": "PECA W17", "unit": "UN", "available_quantity": "12.0000", "separated_quantity": "5.0000",
    "delivered_quantity": "2.0000", "remanaged_quantity": "1.5000", "pending_quantity": "8.5000",
    "origin": "PRODUCAO", "status": "SEPARACAO_INICIADA", "version": 9,
}


def _api_row(**changes) -> dict:
    return {**API_ROW, **changes}


def _row(**changes) -> dict:
    return _api_expedition_item_row_to_process_item(_api_row(**changes))


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
        self.rows = list(rows if rows is not None else [_row()])
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
        row = _row()
        self.assertEqual((row["proposta"], row["cliente"], row["obra_site"], row["lote"]), ("CP 05515", "MNS ENGENHARIA", "MSTRS008_A", "L1"))
        self.assertEqual((row["numero_item"], row["codigo_produto"], row["descricao"], row["unidade"]), ("2", "300.23", "PECA W17", "UN"))
        self.assertEqual(row["status_expedicao_item"], "SEPARACAO_INICIADA")
        self.assertEqual(row["origem_expedicao"], "PRODUCAO")
        self.assertEqual((row["api_proposal_id"], row["processo_atual_id"], row["api_proposal_version"]), (7, 7, 4))
        self.assertEqual((row["id"], row["api_expedition_item_id"], row["api_id"]), (31, 31, 311))

    def test_quantity_is_the_balance_to_deliver_without_trailing_zeros(self):
        row = _row()
        self.assertEqual(row["quantidade"], "8.5")
        self.assertEqual(
            (row["quantidade_disponivel"], row["quantidade_separada"], row["quantidade_entregue"], row["quantidade_remanejada"]),
            ("12", "5", "2", "1.5"),
        )

    def test_a_row_with_missing_fields_does_not_break(self):
        row = _api_expedition_item_row_to_process_item({"id": 1})
        self.assertEqual((row["proposta"], row["descricao"], row["quantidade"]), ("", "", "0"))


class TransportTests(unittest.TestCase):
    def test_client_calls_the_items_endpoint_and_drops_empty_filters(self):
        client = MagicMock()
        ProposalsApiClient(client).list_expedition_items("tok", search="abc", status=None, pending_only="false", limit=500)
        path = client.get.call_args.args[0]
        self.assertTrue(path.startswith("/api/v1/shipping/items?"))
        self.assertIn("search=abc", path)
        self.assertIn("pending_only=false", path)
        self.assertNotIn("status", path)

    def _storage(self, *, replica=None):
        storage = OfficialProposalApiStorage.__new__(OfficialProposalApiStorage)
        proposals = MagicMock()
        storage._client = lambda: (MagicMock(), proposals, "tok")
        storage._read_from_replica = MagicMock(return_value=replica)
        return storage, proposals

    def test_storage_sends_pending_only_as_true_or_false_text(self):
        storage, proposals = self._storage()
        proposals.list_expedition_items.return_value = {"items": [API_ROW], "total": 1}
        rows = storage.expedition_items_queue(search="x", pending_only=False)
        self.assertEqual(proposals.list_expedition_items.call_args.kwargs["pending_only"], "false")
        self.assertEqual(rows[0]["proposta"], "CP 05515")
        storage.expedition_items_queue(pending_only=True)
        self.assertEqual(proposals.list_expedition_items.call_args.kwargs["pending_only"], "true")

    def test_storage_fetches_every_page_up_to_the_ceiling(self):
        storage, proposals = self._storage()
        everything = [_api_row(id=n) for n in range(620)]
        proposals.list_expedition_items.side_effect = lambda token, **kw: {
            "items": everything[kw["offset"]:kw["offset"] + kw["limit"]], "total": len(everything),
        }
        rows = storage.expedition_items_queue()
        self.assertEqual(len(rows), 620)
        self.assertEqual([call.kwargs["offset"] for call in proposals.list_expedition_items.call_args_list], [0, 500])
        proposals.list_expedition_items.reset_mock()
        capped = storage.expedition_items_queue(max_rows=300)
        self.assertEqual(len(capped), 300)
        self.assertEqual(proposals.list_expedition_items.call_args.kwargs["limit"], 300)

    def test_storage_stops_on_an_empty_page(self):
        storage, proposals = self._storage()
        proposals.list_expedition_items.return_value = {"items": [], "total": 9}
        self.assertEqual(storage.expedition_items_queue(), [])
        self.assertEqual(proposals.list_expedition_items.call_count, 1)

    def test_storage_reads_the_local_replica_first_in_a_single_call(self):
        storage, proposals = self._storage(replica={"items": [_api_row(id=n) for n in range(900)], "total": 900, "limit": 2000, "offset": 0})
        rows = storage.expedition_items_queue(search="x", pending_only=False)
        self.assertEqual(len(rows), 900)
        proposals.list_expedition_items.assert_not_called()
        name, entities, _reader = storage._read_from_replica.call_args.args
        self.assertEqual(name, "Itens em expedicao")
        # Com busca a replica precisa tambem das NFs (a busca olha o numero da nota).
        self.assertIn("fiscal_invoices", entities)
        self.assertIn("expedition_items", entities)

    def test_without_a_search_the_replica_does_not_need_the_invoices(self):
        storage, _ = self._storage(replica={"items": [], "total": 0})
        storage.expedition_items_queue(pending_only=True)
        self.assertNotIn("fiscal_invoices", storage._read_from_replica.call_args.args[1])

    def test_a_closed_replica_falls_back_to_the_api(self):
        storage, proposals = self._storage(replica=None)
        proposals.list_expedition_items.return_value = {"items": [API_ROW], "total": 1}
        self.assertEqual(len(storage.expedition_items_queue()), 1)
        proposals.list_expedition_items.assert_called_once()

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
    def test_columns_are_the_ones_asked_for_in_that_order(self):
        columns = AREA_ITEM_COLUMNS["EXPEDICAO"]
        self.assertEqual([key for key, _label in columns], ["codigo_produto", "descricao", "quantidade", "proposta", "status_expedicao_item"])
        self.assertEqual([label for _key, label in columns], ["Código", "Descrição", "Quantidade", "Proposta", "Situação"])

    def test_status_shows_the_label_and_is_marked_as_an_expedition_status(self):
        model = ItemTableModel(FakeItemsService(), "EXPEDICAO", [_row()])
        column = [key for key, _label in model.columns].index("status_expedicao_item")
        index = model.index(0, column)
        self.assertEqual(model.data(index, Qt.DisplayRole), "Separação iniciada")
        self.assertEqual(model.data(index, Qt.UserRole + 3), "EXPEDICAO")

    def test_quantity_shows_the_unit_of_the_item_when_it_has_one(self):
        model = ItemTableModel(FakeItemsService(), "EXPEDICAO", [_row()])
        column = [key for key, _label in model.columns].index("quantidade")
        self.assertEqual(model.data(model.index(0, column), Qt.DisplayRole), "8.5 UN")
        model.set_rows([_row(unit=None)])
        self.assertEqual(model.data(model.index(0, column), Qt.DisplayRole), "8.5")

    def test_other_areas_keep_the_plain_quantity(self):
        model = ItemTableModel(FakeItemsService(), "PRODUCAO", [{"id": 1, "quantidade": "25"}])
        column = [key for key, _label in model.columns].index("quantidade")
        self.assertEqual(model.data(model.index(0, column), Qt.DisplayRole), "25")

    def test_quantity_column_sorts_as_numbers(self):
        rows = [{"id": 1, "quantidade": "1600"}, {"id": 2, "quantidade": "40"}, {"id": 3, "quantidade": "7.5"}]
        model = ItemTableModel(FakeItemsService(), "EXPEDICAO", rows)
        column = [key for key, _label in model.columns].index("quantidade")
        model.sort(column, Qt.AscendingOrder)
        self.assertEqual([row["id"] for row in model.rows], [3, 2, 1])
        model.sort(column, Qt.DescendingOrder)
        self.assertEqual([row["id"] for row in model.rows], [1, 2, 3])


class GroupingTests(unittest.TestCase):
    def _rows(self):
        return [
            _row(id=1, proposal_id=7, proposal_number="CP 05515", product_code="450.8", description="GRADE", pending_quantity="2.0000", status="EM_SEPARACAO"),
            _row(id=2, proposal_id=8, proposal_number="CP 05527", product_code="450.8", description="GRADE", pending_quantity="3.0000", status="EM_SEPARACAO"),
            _row(id=3, proposal_id=7, proposal_number="CP 05515", product_code="300.23", description="PECA", pending_quantity="12.0000", status="SEPARADO"),
            _row(id=4, proposal_id=9, proposal_number="CP 05600", product_code="450.8", description="GRADE", pending_quantity="1.5000", status="SEPARADO"),
        ]

    def test_one_row_per_product_code_sorted_by_code(self):
        groups = group_by_product(self._rows())
        self.assertEqual([row["codigo_produto"] for row in groups], ["300.23", "450.8"])
        self.assertTrue(all(row["_group"] for row in groups))
        self.assertEqual(len(groups[1]["_items"]), 3)

    def test_a_product_in_one_proposal_shows_its_number_and_in_several_shows_the_count(self):
        groups = {row["codigo_produto"]: row for row in group_by_product(self._rows())}
        self.assertEqual(groups["300.23"]["proposta"], "CP 05515")
        self.assertEqual(groups["300.23"]["api_proposal_id"], 7)
        self.assertEqual(groups["450.8"]["proposta"], "3 propostas")
        self.assertIsNone(groups["450.8"]["api_proposal_id"])

    def test_two_items_of_the_same_proposal_still_count_as_one_proposal(self):
        rows = [_row(id=1, product_code="X", pending_quantity="1.0000"), _row(id=2, product_code="X", pending_quantity="2.0000")]
        group = group_by_product(rows)[0]
        self.assertEqual(group["proposta"], "CP 05515")
        self.assertEqual(group["quantidade"], "3")

    def test_quantity_is_the_sum_of_the_balances_with_the_unit_when_it_is_the_same(self):
        groups = {row["codigo_produto"]: row for row in group_by_product(self._rows())}
        self.assertEqual((groups["450.8"]["quantidade"], groups["450.8"]["unidade"]), ("6.5", "UN"))
        mixed = group_by_product([_row(id=1, product_code="X", unit="UN"), _row(id=2, proposal_id=8, product_code="X", unit="kg")])[0]
        self.assertEqual(mixed["unidade"], "")

    def test_status_is_kept_when_every_item_has_it_and_summarized_when_they_differ(self):
        groups = {row["codigo_produto"]: row for row in group_by_product(self._rows())}
        self.assertEqual(groups["300.23"]["status_expedicao_item"], "SEPARADO")
        self.assertEqual(groups["450.8"]["status_expedicao_item"], "Em separação (1/3 separados)")

    def test_separated_and_delivered_together_count_as_separated(self):
        rows = [_row(id=1, product_code="X", status="SEPARADO"), _row(id=2, proposal_id=8, product_code="X", status="ENTREGUE")]
        self.assertEqual(group_by_product(rows)[0]["status_expedicao_item"], "SEPARADO")

    def test_items_without_a_code_group_by_description_and_unnamed_ones_stay_alone(self):
        rows = [
            _row(id=1, product_code=None, description="CHAPA"), _row(id=2, proposal_id=8, product_code="", description="CHAPA"),
            _row(id=3, product_code=None, description=""), _row(id=4, product_code=None, description=""),
        ]
        groups = group_by_product(rows)
        self.assertEqual(len(groups), 3)
        self.assertEqual(next(row for row in groups if row["descricao"] == "CHAPA")["proposta"], "2 propostas")

    def test_summary_text_counts_products_or_items_and_distinct_proposals(self):
        rows = self._rows()
        self.assertEqual(summary_text(rows), "4 itens em 3 propostas")
        self.assertEqual(summary_text(group_by_product(rows), grouped=True), "2 produtos em 3 propostas")
        self.assertEqual(summary_text([_row()]), "1 item em 1 proposta")
        self.assertEqual(summary_text([]), "")


class ItemsPageTests(QtCase):
    def _service(self):
        return FakeItemsService([
            _row(id=1, proposal_id=7, proposal_number="CP 05515", product_code="450.8", pending_quantity="2.0000"),
            _row(id=2, proposal_id=8, proposal_number="CP 05527", product_code="450.8", pending_quantity="3.0000"),
            _row(id=3, proposal_id=7, proposal_number="CP 05515", product_code="300.23", pending_quantity="12.0000"),
        ])

    def test_by_default_the_items_come_grouped_by_product(self):
        page, _ = _page(self._service())
        page.refresh()
        self.assertTrue(page.group_by_product.isChecked())
        self.assertEqual(page.model.rowCount(), 2)
        keys = [key for key, _label in page.model.columns]
        self.assertEqual(
            [page.model.data(page.model.index(row, keys.index("proposta")), Qt.DisplayRole) for row in range(2)],
            ["CP 05515", "2 propostas"],
        )
        self.assertEqual(page.count_label.text(), "2 produtos em 2 propostas")
        self.assertEqual(page.table_stack.currentWidget(), page.table)

    def test_unchecking_the_grouping_lists_one_line_per_item_in_proposal_order(self):
        page, service = _page(self._service())
        page.refresh()
        calls = len(service.calls)
        page.group_by_product.setChecked(False)
        self.assertEqual(len(service.calls), calls)  # reagrupar nao busca de novo
        self.assertEqual(page.model.rowCount(), 3)
        self.assertEqual([row["id"] for row in page.model.rows], [1, 3, 2])
        self.assertEqual(page.count_label.text(), "3 itens em 2 propostas")

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

    def _select(self, page, code):
        keys = [key for key, _label in page.model.columns]
        row = next(i for i, data in enumerate(page.model.rows) if data[keys[0]] == code)
        page.table.selectRow(row)

    def test_details_of_a_product_in_one_proposal_open_that_proposal(self):
        page, service = _page(self._service())
        page.refresh()
        self._select(page, "300.23")
        with patch.object(page_module, "ProcessDetailDialog") as dialog:
            dialog.return_value.exec.return_value = 0
            dialog.return_value.changed = False
            page.open_proposal_details()
        dialog.assert_called_once_with(service, 7, page, area="EXPEDICAO")

    def test_details_of_a_product_in_several_proposals_show_the_distribution(self):
        page, _ = _page(self._service())
        page.refresh()
        self._select(page, "450.8")
        with patch.object(page, "show_distribution") as distribution, patch.object(page_module, "ProcessDetailDialog") as dialog:
            page.open_proposal_details()
        distribution.assert_called_once()
        self.assertEqual(len(distribution.call_args.args[0]["_items"]), 2)
        dialog.assert_not_called()

    def test_details_of_an_ungrouped_item_open_its_proposal(self):
        page, service = _page(self._service())
        page.refresh()
        page.group_by_product.setChecked(False)
        page.table.selectRow(2)  # ultima linha: item 2, da proposta 8
        with patch.object(page_module, "ProcessDetailDialog") as dialog:
            dialog.return_value.exec.return_value = 0
            dialog.return_value.changed = False
            page.open_proposal_details()
        dialog.assert_called_once_with(service, 8, page, area="EXPEDICAO")

    def test_details_refresh_the_list_when_the_dialog_changed_something(self):
        page, service = _page(self._service())
        page.refresh()
        self._select(page, "300.23")
        calls = len(service.calls)
        with patch.object(page_module, "ProcessDetailDialog") as dialog:
            dialog.return_value.exec.return_value = 0
            dialog.return_value.changed = True
            page.open_proposal_details()
        self.assertEqual(len(service.calls), calls + 1)

    def test_the_distribution_dialog_lists_each_proposal_of_the_product(self):
        page, _ = _page(self._service())
        page.refresh()
        self._select(page, "450.8")
        group = page.selected_row()
        shown = {}

        def fake_exec(dialog):
            from PySide6.QtWidgets import QTableWidget

            table = dialog.findChild(QTableWidget)
            shown["rows"] = [[table.item(r, c).text() for c in range(table.columnCount())] for r in range(table.rowCount())]
            shown["title"] = dialog.windowTitle()
            return 0

        with patch.object(page_module.QDialog, "exec", fake_exec):
            page.show_distribution(group)
        self.assertIn("450.8", shown["title"])
        self.assertEqual([row[0] for row in shown["rows"]], ["CP 05515", "CP 05527"])
        self.assertEqual([row[3] for row in shown["rows"]], ["2 UN", "3 UN"])


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
