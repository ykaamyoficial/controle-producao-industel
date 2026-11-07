"""Desktop: cliente/storage/servico do Almoxarifado (entrada por numero, baixa no estoque, itens)
contra o contrato real da API (/api/v1/warehouse/*)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from app.integrations.api.exceptions import ApiBusinessError
from app.integrations.api.proposals_client import ProposalsApiClient
from app.services.api_proposal_storage import OfficialProposalApiStorage, _api_warehouse_to_process
from app.services.backend_adapter import AppError, BackendService


def _row(**overrides):
    row = {
        "id": 7, "proposal_number": "CP7", "customer_name": "ACME", "warehouse_status": "SEPARADO", "warehouse_required": "SIM",
        "total_items": 3, "total_weight": "12.500", "version": 4, "stock_deducted": False, "stock_deducted_at": None,
    }
    row.update(overrides)
    return row


class WarehouseClientTests(unittest.TestCase):
    def test_enter_posts_numbers_in_the_contract_body(self):
        client = MagicMock()
        ProposalsApiClient(client).enter_warehouse("tok", ["CP1", "CP2"])
        client.post.assert_called_once_with(
            "/api/v1/warehouse/proposals/enter", json_payload={"numbers": ["CP1", "CP2"]}, access_token="tok",
        )

    def test_stock_deduction_posts_version_and_flag(self):
        client = MagicMock()
        ProposalsApiClient(client).set_stock_deduction("tok", 7, {"version": 4, "deducted": True})
        client.post.assert_called_once_with(
            "/api/v1/warehouse/proposals/7/stock-deduction", json_payload={"version": 4, "deducted": True}, access_token="tok",
        )

    def test_items_get_drops_empty_filters(self):
        client = MagicMock()
        ProposalsApiClient(client).list_warehouse_items("tok", search="CP7", limit=500, offset=0)
        client.get.assert_called_once_with("/api/v1/warehouse/items?search=CP7&limit=500&offset=0", access_token="tok")
        client.get.reset_mock()
        ProposalsApiClient(client).list_warehouse_items("tok", search=None, limit=500)
        client.get.assert_called_once_with("/api/v1/warehouse/items?limit=500", access_token="tok")


class WarehouseStorageTests(unittest.TestCase):
    @staticmethod
    def _storage(proposals):
        storage = OfficialProposalApiStorage.__new__(OfficialProposalApiStorage)
        client = MagicMock()
        storage._client = lambda: (client, proposals, "tok")
        return storage, client

    def test_row_mapping_carries_stock_deduction_fields(self):
        pending = _api_warehouse_to_process(_row())
        done = _api_warehouse_to_process(_row(stock_deducted=True, stock_deducted_at="2026-11-07T13:30:00Z"))
        no_stock = _api_warehouse_to_process(_row(warehouse_status="SEM_PARAFUSOS"))
        starting = _api_warehouse_to_process(_row(warehouse_status="EM_SEPARACAO"))
        self.assertFalse(pending["baixa_estoque"])
        self.assertEqual(pending["baixa_estoque_status"], "BAIXA_PENDENTE")
        self.assertEqual(pending["baixa_estoque_em"], "")
        self.assertTrue(done["baixa_estoque"])
        self.assertEqual(done["baixa_estoque_status"], "BAIXA_CONFIRMADA")
        self.assertEqual(done["baixa_estoque_em"], "07/11/2026 13:30:00")
        self.assertEqual(done["api_version"], 4)
        # Sem material separado nao ha baixa a dar: a coluna fica vazia.
        self.assertEqual(no_stock["baixa_estoque_status"], "")
        self.assertEqual(starting["baixa_estoque_status"], "")

    def test_warehouse_rows_keeps_the_200_row_ceiling_and_reads_the_count_from_the_api(self):
        # Foco de revisao 4: com mais de 200 propostas na aba a lista corta em 200, mas o contador vem da API.
        proposals = MagicMock()
        proposals.list_warehouse_proposals.return_value = {
            "items": [_row(id=n) for n in range(200)], "total": 350, "limit": 200, "offset": 0, "pending_stock_deduction": 321,
        }
        storage, client = self._storage(proposals)
        rows = storage.warehouse_rows({"text": "CP", "status": "SEPARADO"})
        proposals.list_warehouse_proposals.assert_called_once_with("tok", search="CP", status="SEPARADO", limit=200, offset=0)
        self.assertEqual(len(rows), 200)
        self.assertEqual(storage.warehouse_pending_stock_deduction, 321)
        client.close.assert_called_once()

    def test_warehouse_rows_without_the_field_counts_zero(self):
        proposals = MagicMock()
        proposals.list_warehouse_proposals.return_value = {"items": [_row()], "total": 1}
        storage, _client = self._storage(proposals)
        storage.warehouse_pending_stock_deduction = 9
        storage.warehouse_rows()
        self.assertEqual(storage.warehouse_pending_stock_deduction, 0)

    def test_enter_returns_the_result_list_in_order(self):
        results = [
            {"number": "CP1", "result": "ENTROU", "proposal_id": 1, "message": "ok"},
            {"number": "CP2", "result": "NAO_ENCONTRADA", "proposal_id": None, "message": "nao existe"},
        ]
        proposals = MagicMock()
        proposals.enter_warehouse.return_value = {"items": results}
        storage, client = self._storage(proposals)
        self.assertEqual(storage.warehouse_enter(["CP1", "CP2"]), results)
        proposals.enter_warehouse.assert_called_once_with("tok", ["CP1", "CP2"])
        client.close.assert_called_once()

    def test_set_stock_deduction_sends_contract_fields_and_maps_the_row(self):
        proposals = MagicMock()
        proposals.set_stock_deduction.return_value = _row(stock_deducted=True, stock_deducted_at="2026-11-07T13:30:00Z", version=5)
        storage, client = self._storage(proposals)
        row = storage.warehouse_set_stock_deduction(7, 4, True)
        proposals.set_stock_deduction.assert_called_once_with("tok", 7, {"version": 4, "deducted": True})
        self.assertTrue(row["baixa_estoque"])
        self.assertEqual(row["api_version"], 5)
        client.close.assert_called_once()

    def test_set_stock_deduction_error_still_closes_the_client(self):
        proposals = MagicMock()
        proposals.set_stock_deduction.side_effect = ApiBusinessError("PROPOSAL_VERSION_CONFLICT", "x", status_code=409)
        storage, client = self._storage(proposals)
        with self.assertRaises(ApiBusinessError):
            storage.warehouse_set_stock_deduction(7, 1, False)
        client.close.assert_called_once()

    def test_items_queue_pages_by_500_and_maps_rows(self):
        def item(n):
            return {
                "proposal_id": 7, "proposal_number": "CP7", "customer_name": "ACME", "item_number": str(n), "product_code": None,
                "description": "Parafuso", "quantity": "10.0000", "unit": "UN", "total_weight": None, "warehouse_status": "EM_SEPARACAO",
            }

        proposals = MagicMock()
        proposals.list_warehouse_items.side_effect = [
            {"items": [item(n) for n in range(500)], "total": 501, "limit": 500, "offset": 0},
            {"items": [item(500)], "total": 501, "limit": 500, "offset": 500},
        ]
        storage, client = self._storage(proposals)
        rows = storage.warehouse_items_queue(search="CP7")
        self.assertEqual(len(rows), 501)
        first_call, second_call = proposals.list_warehouse_items.call_args_list
        self.assertEqual(first_call.kwargs, {"limit": 500, "offset": 0, "search": "CP7"})
        self.assertEqual(second_call.kwargs["offset"], 500)
        self.assertEqual(rows[0]["quantidade"], "10")
        self.assertEqual(rows[0]["proposta"], "CP7")
        self.assertEqual(rows[0]["codigo_produto"], "")
        self.assertEqual(rows[0]["status_almoxarifado_item"], "EM_SEPARACAO")
        self.assertEqual(rows[0]["api_proposal_id"], 7)
        client.close.assert_called_once()


class WarehouseServiceTests(unittest.TestCase):
    @staticmethod
    def _service(user=True, can_edit=True):
        service = BackendService.__new__(BackendService)
        service.user = {"id": 1} if user else None
        service.official_proposal_storage = MagicMock()
        service.can_edit = lambda area: can_edit
        return service

    def test_filter_options_no_longer_offer_hidden_statuses(self):
        options = self._service().list_status("ALMOXARIFADO")
        self.assertNotIn("NAO_DEFINIDO", options)
        self.assertNotIn("AGUARDANDO_CONFIRMACAO", options)
        self.assertIn("EM_SEPARACAO", options)
        self.assertIn("SEM_PARAFUSOS", options)

    def test_em_separacao_can_go_to_sem_parafusos_but_separado_cannot(self):
        service = self._service()
        service.official_proposal_storage.get_process.return_value = {"status_almoxarifado": "EM_SEPARACAO"}
        self.assertEqual(service.next_status_options("ALMOXARIFADO", 7), ["SEPARADO", "SEM_PARAFUSOS"])
        service.official_proposal_storage.get_process.return_value = {"status_almoxarifado": "SEPARADO"}
        self.assertNotIn("SEM_PARAFUSOS", service.next_status_options("ALMOXARIFADO", 7))

    def test_pending_count_reads_the_storage_value(self):
        service = self._service()
        service.official_proposal_storage.warehouse_pending_stock_deduction = 12
        self.assertEqual(service.warehouse_pending_count(), 12)
        service.official_proposal_storage = object()
        self.assertEqual(service.warehouse_pending_count(), 0)

    def test_enter_requires_login_and_permission(self):
        with self.assertRaises(AppError):
            self._service(user=False).warehouse_enter(["CP1"])
        service = self._service(can_edit=False)
        with self.assertRaises(AppError):
            service.warehouse_enter(["CP1"])
        service.official_proposal_storage.warehouse_enter.assert_not_called()

    def test_enter_delegates_and_invalidates_the_cache(self):
        service = self._service()
        service._invalidate_operational_cache = MagicMock()
        service.official_proposal_storage.warehouse_enter.return_value = [{"number": "CP1", "result": "ENTROU"}]
        self.assertEqual(service.warehouse_enter(["CP1"]), [{"number": "CP1", "result": "ENTROU"}])
        self.assertGreaterEqual(service._invalidate_operational_cache.call_count, 1)

    def test_set_stock_deduction_uses_given_version(self):
        service = self._service()
        service._invalidate_operational_cache = MagicMock()
        service.warehouse_set_stock_deduction(7, 4, True)
        service.official_proposal_storage.warehouse_set_stock_deduction.assert_called_once_with(7, 4, True)
        service.official_proposal_storage.get_process.assert_not_called()

    def test_set_stock_deduction_without_version_reads_the_current_one(self):
        service = self._service()
        service._invalidate_operational_cache = MagicMock()
        service.official_proposal_storage.get_process.return_value = {"api_version": 9}
        service.warehouse_set_stock_deduction(7, None, False)
        service.official_proposal_storage.warehouse_set_stock_deduction.assert_called_once_with(7, 9, False)

    def test_set_stock_deduction_conflict_becomes_a_clear_app_error(self):
        service = self._service()
        service._invalidate_operational_cache = MagicMock()
        service.official_proposal_storage.warehouse_set_stock_deduction.side_effect = ApiBusinessError(
            "PROPOSAL_VERSION_CONFLICT", "versao", status_code=409,
        )
        with self.assertRaises(AppError) as caught:
            service.warehouse_set_stock_deduction(7, 1, True)
        self.assertIn("alterada por outro usuario", str(caught.exception))
        self.assertEqual(caught.exception.error_code, "PROPOSAL_VERSION_CONFLICT")

    def test_set_stock_deduction_requires_permission(self):
        service = self._service(can_edit=False)
        with self.assertRaises(AppError):
            service.warehouse_set_stock_deduction(7, 1, True)
        service.official_proposal_storage.warehouse_set_stock_deduction.assert_not_called()

    def test_items_queue_passes_search_and_wraps_errors(self):
        service = self._service()
        service._cached_read = lambda key, loader, ttl=None: loader()
        service.official_proposal_storage.warehouse_items_queue.return_value = [{"proposta": "CP7"}]
        self.assertEqual(service.warehouse_items_queue({"text": "CP7"}), [{"proposta": "CP7"}])
        service.official_proposal_storage.warehouse_items_queue.assert_called_once_with(search="CP7")
        service.official_proposal_storage.warehouse_items_queue.side_effect = ApiBusinessError("X", "falhou", status_code=500)
        with self.assertRaises(AppError):
            service.warehouse_items_queue({})


if __name__ == "__main__":
    unittest.main()
