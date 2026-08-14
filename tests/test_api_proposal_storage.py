from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from app.integrations.api.client import ApiResponse
from app.integrations.api.config import DesktopApiSettings
from app.integrations.api.exceptions import ApiBusinessError, ApiConnectionError
from app.integrations.api.models import ApiSessionState
from app.services.api_proposal_storage import (
    OfficialProposalApiStorage,
    _api_galvanization_item_row_to_process_item,
    _api_partial_to_process,
    _api_production_item_row_to_process_item,
    _expedition_item_payload,
    _expedition_remanagement_item_payload,
    _filter_fiscal_rows,
    _api_history_to_legacy,
    _item_create_payload,
    _proposal_create_payload,
    user_message_for_api_error,
)


class ApiProposalStorageTests(unittest.TestCase):
    def test_galvanization_load_details_uses_one_official_read_and_maps_all_sections(self):
        storage = OfficialProposalApiStorage.__new__(OfficialProposalApiStorage)
        client = MagicMock()
        proposals = MagicMock()
        proposals.get_galvanization_load.return_value = {
            "id": 4,
            "status": "RETORNO_PARCIAL",
            "driver_name": "Motorista",
            "created_by_name": "Maria",
            "proposals": [{"proposal_id": 10, "proposal_number": "CP10", "customer_name": "Cliente"}],
            "items": [{"id": 20, "proposal_id": 10, "proposal_number": "CP10", "description": "Item"}],
            "returns": [{"id": 30, "occurred_at": "2026-08-11T12:00:00Z", "return_type": "PARCIAL", "items": []}],
            "history": [{"id": 40, "event_type": "GALVANIZATION_LOAD_CREATED", "created_at": "2026-08-11T11:00:00Z"}],
        }
        storage._client = lambda: (client, proposals, "token")

        details = storage.galvanization_load_details(4)

        proposals.get_galvanization_load.assert_called_once_with("token", 4)
        client.close.assert_called_once()
        self.assertEqual(details["load"]["criado_por"], "Maria")
        self.assertEqual(details["proposals"][0]["processo_id"], 10)
        self.assertEqual(details["items"][0]["id"], 20)
        self.assertEqual(details["returns"][0]["numero_retorno"], 1)
        self.assertEqual(details["history"][0]["evento"], "GALVANIZATION_LOAD_CREATED")

    def test_galvanization_load_edit_uses_version_captured_when_dialog_opened(self):
        storage = OfficialProposalApiStorage.__new__(OfficialProposalApiStorage)
        client = MagicMock()
        proposals = MagicMock()
        proposals.update_galvanization_load.return_value = {"id": 7}
        storage._client = lambda: (client, proposals, "token")

        saved_id = storage.save_galvanization_load(
            "Motorista",
            "",
            "",
            [{"item_id": 11, "sent_quantity": "1.0000"}],
            7,
            expected_version=4,
        )

        self.assertEqual(saved_id, 7)
        proposals.get_galvanization_load.assert_not_called()
        payload = proposals.update_galvanization_load.call_args.args[2]
        self.assertEqual(payload["version"], 4)
        client.close.assert_called_once()

    def test_blank_or_legacy_zero_weight_is_serialized_as_unknown(self):
        base = {"numero_item": "1", "descricao": "Item", "quantidade": "2"}

        for value in ("", None, "0", "0,0000"):
            payload = _item_create_payload({**base, "peso": value})
            self.assertIsNone(payload["unit_weight"])
            self.assertIsNone(payload["total_weight"])

    def test_positive_weight_keeps_deterministic_total(self):
        payload = _item_create_payload({"numero_item": "1", "descricao": "Item", "quantidade": "3", "peso": "2,5"})
        self.assertEqual(payload["unit_weight"], "2.5000")
        self.assertEqual(payload["total_weight"], "7.5000")

    def test_official_storage_reuses_persistent_client_without_refreshing_valid_token(self):
        settings = DesktopApiSettings(enabled=True, base_url="http://127.0.0.1:8000", connect_timeout=1, read_timeout=1)
        client = _FakePersistentClient()
        storage = OfficialProposalApiStorage(config_store=_FakeConfigStore(settings), client_factory=lambda _settings: client)
        storage._persistent_client = client
        storage._settings_key = (settings.enabled, settings.base_url, settings.connect_timeout, settings.read_timeout)
        storage._session = _FakeSession("access-token")

        storage.list_proposals(limit=10)
        storage.list_proposals(limit=10)

        self.assertEqual(client.request_count, 2)
        self.assertEqual(client.close_count, 0)
        self.assertEqual(storage.refresh_count, 0)
        self.assertEqual(storage._session.refresh_calls, [False, False])

    def test_create_payload_uses_official_contract_and_omits_financial_fields(self):
        data = {
            "proposta": " CP00001 ",
            "cliente": "Cliente",
            "obra_site": "Site",
            "pedido_compra": "OC1",
            "lote": "L1",
            "data_entrada": "21/07/2026",
            "prazo_entrega": "30/07/2026",
            "observacoes_gerais": "Obs",
            "necessita_almoxarifado": "SIM",
            "valor_total": "999",
            "itens": [
                {
                    "numero_item": "1",
                    "codigo_produto": "COD",
                    "descricao": "Linha 1\nLinha 2",
                    "quantidade": "2",
                    "peso": "3,5",
                    "produzir_internamente": "sim",
                    "precisa_galvanizacao": "nao",
                }
            ],
        }

        payload = _proposal_create_payload(data, {"origem": "NOMUS_PDF"})

        self.assertEqual(payload["proposal_number"], "CP00001")
        self.assertEqual(payload["proposal_date"], "2026-07-21")
        self.assertEqual(payload["deadline_date"], "2026-07-30")
        self.assertEqual(payload["source"], "NOMUS_PDF")
        self.assertEqual(payload["warehouse_status"], "AGUARDANDO_CONFIRMACAO")
        self.assertEqual(payload["items"][0]["description"], "Linha 1\nLinha 2")
        self.assertEqual(payload["items"][0]["quantity"], "2.0000")
        self.assertEqual(payload["items"][0]["unit_weight"], "3.5000")
        self.assertEqual(payload["items"][0]["total_weight"], "7.0000")
        self.assertTrue(payload["items"][0]["produce_internally"])
        self.assertFalse(payload["items"][0]["requires_galvanization"])
        self.assertNotIn("valor_total", payload)

    def test_user_messages_are_clear_for_conflict_and_connection(self):
        conflict = ApiBusinessError("PROPOSAL_VERSION_CONFLICT", "conflito", status_code=409)
        duplicate = ApiBusinessError("PROPOSAL_NUMBER_ALREADY_EXISTS", "duplicado", status_code=409)
        offline = ApiConnectionError("offline")

        self.assertIn("alterada por outro usuario", user_message_for_api_error(conflict))
        self.assertIn("Ja existe", user_message_for_api_error(duplicate))
        self.assertIn("servidor esta indisponivel", user_message_for_api_error(offline))

    def test_expedition_payload_uses_proposal_item_ids_and_remanagement_quantity(self):
        # item_ids passed to these helpers come from the desktop selection UI, which stores
        # ProposalItem.id (see _api_expedition_item_to_process_item's "id"), not
        # ExpeditionItem.id, so the payload must key them as proposal_item_id.
        self.assertEqual(_expedition_item_payload([7]), [{"proposal_item_id": 7}])
        self.assertEqual(
            _expedition_remanagement_item_payload([7], [{"proposal_item_id": 7, "pending_quantity": "2.0000"}]),
            [{"proposal_item_id": 7, "quantity": "2.0000"}],
        )

    def test_production_item_row_maps_proposal_context_and_item_fields(self):
        row = _api_production_item_row_to_process_item(
            {
                "proposal_id": 1,
                "proposal_number": "CP05228",
                "customer_name": "MNS ENGENHARIA",
                "project_name": "SITE 1",
                "lot": "L1",
                "proposal_version": 4,
                "proposal_status": "INICIADO",
                "item_id": 7,
                "item_number": "1",
                "product_code": "450.983",
                "description": "VIGA METALICA",
                "quantity": "1.0000",
                "unit": "un",
                "unit_weight": "69.5000",
                "total_weight": "69.5000",
                "produce_internally": "SIM",
                "requires_galvanization": "SIM",
                "flow_defined": True,
                "produced": False,
                "notes": None,
                "version": 2,
            }
        )
        self.assertEqual(row["id"], 7)
        self.assertEqual(row["api_id"], 7)
        self.assertEqual(row["api_version"], 2)
        self.assertEqual(row["api_proposal_id"], 1)
        self.assertEqual(row["api_proposal_version"], 4)
        self.assertEqual(row["proposta"], "CP05228")
        self.assertEqual(row["cliente"], "MNS ENGENHARIA")
        self.assertEqual(row["status_producao"], "INICIADO")
        self.assertEqual(row["status_producao_item"], "INICIADO")
        self.assertEqual(row["produzir_internamente"], "sim")
        self.assertEqual(row["precisa_galvanizacao"], "sim")
        self.assertFalse(row["produzido"])

    def test_undefined_production_item_is_identified_as_flow_pending(self):
        row = _api_production_item_row_to_process_item(
            {
                "proposal_id": 12,
                "proposal_number": "CP 05236",
                "proposal_version": 2,
                "proposal_status": "NAO_INICIADO",
                "item_id": 41,
                "item_number": "1",
                "description": "Item sem fluxo",
                "quantity": "2.0000",
                "produce_internally": "INDEFINIDO",
                "requires_galvanization": "INDEFINIDO",
                "flow_defined": False,
                "produced": False,
                "version": 1,
            }
        )

        self.assertFalse(row["fluxo_definido"])
        self.assertEqual(row["status_producao"], "NAO_INICIADO")
        self.assertEqual(row["status_producao_item"], "FLUXO_INDEFINIDO")

    def test_galvanization_item_row_exposes_situation_under_status_column_key(self):
        api_row = {
            "proposal_id": 23,
            "proposal_number": "CP05239",
            "customer_name": "MNS ENGENHARIA",
            "project_name": None,
            "lot": None,
            "item_id": 41,
            "item_number": "1",
            "product_code": "6.37",
            "description": "GRAMPO",
            "quantity": "12.0000",
            "available_quantity": "12.0000",
            "unit_weight": "0.0000",
            "available_weight": "0.0000",
            "sent_quantity": "0.0000",
            "sent_weight": "0.0000",
            "version": 3,
            "situation": "DISPONIVEL",
        }
        available = _api_galvanization_item_row_to_process_item(api_row)
        # A tabela por item (ItemTableModel) usa a coluna "status_galvanizacao" pra
        # colorir/traduzir a situacao — regressao encontrada em revisao: a funcao
        # so preenchia "situacao", deixando aquela coluna sempre vazia.
        self.assertEqual(available["status_galvanizacao"], "DISPONIVEL")
        self.assertEqual(available["situacao"], "DISPONIVEL")
        self.assertEqual(available["quantidade_disponivel"], "12.0000")
        self.assertEqual(available["quantidade_em_galvanizacao"], "0.0000")

        in_galvanization = _api_galvanization_item_row_to_process_item(
            {**api_row, "situation": "EM_GALVANIZACAO", "available_quantity": "0.0000", "sent_quantity": "5.0000"}
        )
        self.assertEqual(in_galvanization["status_galvanizacao"], "EM_GALVANIZACAO")

    def test_official_fiscal_rows_apply_desktop_filters_locally(self):
        rows = [
            {"fiscal_processo_id": 1, "data_entrada_fiscal": "27/07/2026", "pendencia_critica": 1, "mais_7_dias_sem_emissao": 0, "situacao_fiscal": "PENDENCIA_FISCAL_CRITICA"},
            {"fiscal_processo_id": 2, "data_entrada_fiscal": "26/07/2026", "pendencia_critica": 0, "mais_7_dias_sem_emissao": 1, "situacao_fiscal": "AGUARDANDO_NF"},
            {"fiscal_processo_id": 3, "data_entrada_fiscal": "27/07/2026", "pendencia_critica": 0, "mais_7_dias_sem_emissao": 0, "situacao_fiscal": "NF_RETIRADA_CLIENTE"},
        ]

        self.assertEqual(
            [row["fiscal_processo_id"] for row in _filter_fiscal_rows(rows, {"data_entrada_fiscal": "2026-07-27", "excluir_retiradas": "1"})],
            [1],
        )
        self.assertEqual(
            [row["fiscal_processo_id"] for row in _filter_fiscal_rows(rows, {"mais_7_dias_sem_emissao": "1"})],
            [2],
        )
        self.assertEqual(
            [row["fiscal_processo_id"] for row in _filter_fiscal_rows(rows, {"pendencia_critica": "1"})],
            [1],
        )

    def test_official_history_payload_maps_to_desktop_legacy_columns(self):
        row = _api_history_to_legacy(
            {
                "id": 9,
                "source": "expedition",
                "proposal_id": 60,
                "proposal_number": "CP00060",
                "area": "CONTROLE_GERAL",
                "from_status": "SEPARADO",
                "to_status": "ENTREGUE",
                "event_type": "EXPEDITION_DELIVERY_RECALCULATED",
                "actor_user_id": 1,
                "actor_name": "Administrador",
                "observation": "Entrega",
                "created_at": "2026-07-27T12:00:00Z",
                "request_id": "REQ",
            }
        )

        self.assertEqual(row["proposta"], "CP00060")
        self.assertEqual(row["area"], "CONTROLE GERAL")
        self.assertEqual(row["status_anterior"], "SEPARADO")
        self.assertEqual(row["status_novo"], "ENTREGUE")
        self.assertEqual(row["usuario"], "Administrador")
        self.assertEqual(row["computador"], "API")

    def test_official_partial_payload_maps_balances_to_desktop_columns(self):
        row = _api_partial_to_process(
            {
                "id": 70,
                "proposal_number": "CP00070",
                "customer_name": "ACME",
                "project_name": "Site",
                "lot": "L1",
                "current_area": "EXPEDICAO",
                "current_status": "ENTREGUE_PARCIAL",
                "production_status": "FINALIZADO",
                "galvanization_status": "RETORNOU_GALVANIZACAO",
                "shipping_status": "ENTREGUE_PARCIAL",
                "fiscal_status": "NOTA_FISCAL_PARCIAL",
                "flow_situation": "PARCIAL_COM_PENDENCIA",
                "partial_stage": "FISCAL",
                "total_items": 2,
                "produced_items": 2,
                "production_pending_items": 0,
                "galvanization_pending_items": 0,
                "expedition_pending_items": 1,
                "fiscal_pending_items": 1,
                "total_weight": "20.0000",
                "produced_weight": "20.0000",
                "production_pending_weight": "0",
                "galvanization_returned_weight": "20.0000",
                "galvanization_pending_weight": "0",
                "expedition_delivered_weight": "10.0000",
                "expedition_pending_weight": "10.0000",
                "fiscal_billed_weight": "10.0000",
                "fiscal_pending_weight": "10.0000",
                "version": 3,
            }
        )

        self.assertEqual(row["proposta"], "CP00070")
        self.assertEqual(row["localizacao_atual"], "FISCAL")
        self.assertEqual(row["status_localizacao"], "NOTA_FISCAL_PARCIAL")
        self.assertEqual(row["peso_parcial"], "10")
        self.assertEqual(row["saldo_pendente"], "10")
        self.assertEqual(row["itens_fiscais_pendentes"], 1)


class _FakeConfigStore:
    def __init__(self, settings: DesktopApiSettings):
        self._settings = settings

    def load_settings(self) -> DesktopApiSettings:
        return self._settings


class _FakeSession:
    def __init__(self, access_token: str):
        self.state = ApiSessionState(
            access_token=access_token,
            access_token_expires_at=datetime.now() + timedelta(hours=1),
            api_session_active=True,
        )
        self.refresh_calls: list[bool] = []

    def refresh_if_needed(self, *, force: bool = False) -> ApiSessionState:
        self.refresh_calls.append(force)
        return self.state


class _FakePersistentClient:
    def __init__(self):
        self.request_count = 0
        self.close_count = 0

    def request(self, method: str, path: str, *, json_payload=None, access_token=None, retries: int = 0):
        self.request_count += 1
        return ApiResponse(
            status_code=200,
            data={"items": [], "total": 0, "limit": 10, "offset": 0},
            request_id=f"REQ-{self.request_count}",
            duration_ms=1,
        )

    def close(self) -> None:
        self.close_count += 1


if __name__ == "__main__":
    unittest.main()
