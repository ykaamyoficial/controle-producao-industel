from __future__ import annotations

import unittest

from app.integrations.api.exceptions import ApiBusinessError, ApiConnectionError
from app.services.backend_adapter import AppError, BackendService


class FakeOfficialProposalStorage:
    def __init__(self):
        self.calls = []
        self.should_fail = False
        self.fiscal_batch_error = None
        self.production_status = "NAO_INICIADO"
        self.expedition_status = "EM_SEPARACAO"

    def user_rows(self):
        self.calls.append(("user_rows",))
        return [{"id": 1, "nome": "Admin"}]

    def get_user(self, user_id):
        self.calls.append(("get_user", user_id))
        return {"id": user_id, "nome": "Operador", "login": "operador", "permissions": {"users_permissions": "VIEW"}}

    def save_user(self, data, user_id=None):
        self.calls.append(("save_user", data, user_id))
        return {"id": user_id or 55}

    def toggle_user(self, user_id):
        self.calls.append(("toggle_user", user_id))
        return {"id": user_id}

    def administrative_correction_options(self, process_id):
        self.calls.append(("administrative_correction_options", process_id))
        return {
            "proposal_id": process_id,
            "version": 5,
            "current_state": {"current_area": "PRODUCAO", "current_status": "FINALIZADO"},
            "options": [{"target_area": "EXPEDICAO", "target_status": "EM_SEPARACAO"}],
        }

    def preview_administrative_correction(self, process_id, expected_version, new_area, new_status):
        self.calls.append(("preview_administrative_correction", process_id, expected_version, new_area, new_status))
        return {"allowed": True, "changes": [{"field": "current_area", "before": "PRODUCAO", "after": "EXPEDICAO"}]}

    def administrative_correction(self, process_id, expected_version, new_area, new_status, reason, idempotency_key):
        self.calls.append(("administrative_correction", process_id, expected_version, new_area, new_status, reason, idempotency_key))
        return {"id": process_id, "status_geral": "EM_PRODUCAO", "status_producao": new_status}

    def save_process(self, data, process_id=None, import_metadata=None):
        self.calls.append(("save_process", data, process_id, import_metadata))
        if self.should_fail:
            raise ApiConnectionError("offline")
        return 321

    def proposal_items(self, process_id):
        self.calls.append(("proposal_items", process_id))
        return [{"id": 9001, "numero_item": "1", "descricao": "Item oficial"}]

    def production_items(self, process_id, *, pending_production=False):
        self.calls.append(("production_items", process_id, pending_production))
        if pending_production:
            return [{"id": 9002, "numero_item": "2", "descricao": "Item pendente", "produzido": False}]
        return [{"id": 9001, "numero_item": "1", "descricao": "Item oficial"}]

    def expedition_items(self, process_id, *, pending_delivery=False):
        self.calls.append(("expedition_items", process_id, pending_delivery))
        if pending_delivery:
            return [{"id": 9003, "numero_item": "3", "descricao": "Item separado", "saldo_separado": "1"}]
        return [{"id": 9003, "numero_item": "3", "descricao": "Item expedicao"}]

    def list_production_proposals(self, **kwargs):
        self.calls.append(("list_production_proposals", kwargs))
        return [
            {"id": 20, "proposta": "CP00020", "cliente": "ACME", "production_status": self.production_status, "api_id": 20},
        ]

    def list_expedition_proposals(self, **kwargs):
        self.calls.append(("list_expedition_proposals", kwargs))
        return [
            {
                "id": 40,
                "api_id": 40,
                "proposta": "CP00040",
                "cliente": "ACME",
                "obra_site": "SITE A",
                "lote": "L1",
                "status_expedicao": self.expedition_status,
                "current_status": self.expedition_status,
            },
            {
                "id": 41,
                "api_id": 41,
                "proposta": "CP00041",
                "cliente": "BETA",
                "obra_site": "SITE B",
                "lote": "L2",
                "status_expedicao": "SEPARADO",
                "current_status": "SEPARADO",
            },
        ]

    def get_production_process(self, process_id):
        self.calls.append(("get_production_process", process_id))
        actions = [
            {"id": "START_PRODUCTION", "enabled": self.production_status in {"NAO_INICIADO", "LIBERADO_PRODUCAO", "ITEM_PENDENTE_FABRICACAO"}},
            {"id": "PAUSE_PRODUCTION", "enabled": self.production_status == "INICIADO"},
            {"id": "RESUME_PRODUCTION", "enabled": self.production_status == "PARADO"},
            {"id": "DEFINE_ITEM_FLOW", "enabled": self.production_status != "FINALIZADO"},
            {"id": "UPDATE_ITEM_WEIGHTS", "enabled": self.production_status != "FINALIZADO"},
            {"id": "COMPLETE_ITEMS", "enabled": self.production_status in {"INICIADO", "FINALIZADO_PARCIAL"}},
        ]
        return {
            "id": process_id,
            "api_id": process_id,
            "api_version": 5,
            "proposta": "CP00020",
            "status_producao": self.production_status,
            "progresso_producao": {"undefined_flow_items": 0, "pending_items": 1},
            "actions": actions,
        }

    def start_production(self, process_id, version, observation=""):
        self.calls.append(("start_production", process_id, version, observation))
        self.production_status = "INICIADO"
        return {"id": process_id, "status_producao": "INICIADO"}

    def pause_production(self, process_id, version, reason):
        self.calls.append(("pause_production", process_id, version, reason))
        self.production_status = "PARADO"
        return {"id": process_id, "status_producao": "PARADO"}

    def resume_production(self, process_id, version, observation=""):
        self.calls.append(("resume_production", process_id, version, observation))
        self.production_status = "INICIADO"
        return {"id": process_id, "status_producao": "INICIADO"}

    def update_production_item_weights(self, process_id, version, weights):
        self.calls.append(("update_production_item_weights", process_id, version, weights))
        return len(weights)

    def production_item_flow_summary(self, process_id):
        self.calls.append(("production_item_flow_summary", process_id))
        return {"total": 1, "undefined_count": 0, "needs_galvanization_count": 1, "no_internal_production_count": 0}

    def update_production_item_flow(self, process_id, version, definitions, origin):
        self.calls.append(("update_production_item_flow", process_id, version, definitions, origin))
        return len(definitions)

    def complete_production_items(self, process_id, version, item_ids=None, observation=""):
        self.calls.append(("complete_production_items", process_id, version, item_ids, observation))
        self.production_status = "FINALIZADO"
        return {"id": process_id, "status_producao": "FINALIZADO"}

    def get_expedition_process(self, process_id):
        self.calls.append(("get_expedition_process", process_id))
        status = self.expedition_status if int(process_id) == 40 else "SEPARADO"
        actions = [
            {"id": "START_SEPARATION", "enabled": status in {"EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL"}},
            {"id": "SEPARATE_ITEMS", "enabled": status in {"EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARACAO_INICIADA", "ENTREGUE_PARCIAL"}},
            {"id": "REGISTER_DELIVERY", "enabled": status in {"SEPARADO", "ENTREGUE_PARCIAL"}},
            {"id": "REMANAGE_MATERIAL", "enabled": status in {"SEPARADO", "ENTREGUE_PARCIAL"}},
        ]
        return {
            "id": process_id,
            "api_id": process_id,
            "api_version": 6,
            "proposta": f"CP{process_id:05d}",
            "status_expedicao": status,
            "current_status": status,
            "actions": actions,
        }

    def start_expedition_separation(self, process_id, version, observation=""):
        self.calls.append(("start_expedition_separation", process_id, version, observation))
        self.expedition_status = "SEPARACAO_INICIADA"
        return {"id": process_id, "status_expedicao": self.expedition_status}

    def separate_expedition_items(self, process_id, version, item_ids=None, observation=""):
        self.calls.append(("separate_expedition_items", process_id, version, item_ids, observation))
        self.expedition_status = "SEPARADO"
        return {"id": process_id, "status_expedicao": self.expedition_status}

    def deliver_expedition_items(self, process_id, version, item_ids=None, observation=""):
        self.calls.append(("deliver_expedition_items", process_id, version, item_ids, observation))
        self.expedition_status = "ENTREGUE" if not item_ids or len(item_ids) > 1 else "ENTREGUE_PARCIAL"
        return {"id": process_id, "status_expedicao": self.expedition_status}

    def deliver_by_material_remanagement(self, destination_id, source_id, observation, item_ids=None):
        self.calls.append(("deliver_by_material_remanagement", destination_id, source_id, observation, item_ids))
        return {"id": destination_id, "status_geral": "ENTREGUE"}

    def fiscal_rows(self, filters=None):
        self.calls.append(("fiscal_rows", filters))
        return [
            {
                "fiscal_processo_id": 60,
                "processo_id": 40,
                "proposta": "CP00060",
                "cliente": "ACME",
                "status_fiscal": "FALTA_EMITIR_NOTA_FISCAL",
                "situacao_fiscal": "DISPONIVEL_PARA_EMISSAO",
            }
        ]

    def fiscal_items(self, fiscal_record_id):
        self.calls.append(("fiscal_items", fiscal_record_id))
        return [{"id": 6001, "fiscal_item_id": 6001, "quantidade_pendente": "1.0000", "peso_pendente": "10.0000"}]

    def fiscal_emissions(self, fiscal_record_id):
        self.calls.append(("fiscal_emissions", fiscal_record_id))
        return [{"id": 6101, "numero_controle": "NF-1", "itens": [{"id": 6201, "active": True}]}]

    def fiscal_movements(self, fiscal_record_id):
        self.calls.append(("fiscal_movements", fiscal_record_id))
        return [{"id": 6301, "tipo_movimento": "FISCAL_INVOICE_REGISTERED"}]

    def fiscal_indicators(self):
        self.calls.append(("fiscal_indicators",))
        return {"falta_emitir": 1, "nf_parcial": 0, "nf_emitida": 0, "pendencia_critica": 0, "entregues_sem_nf": 0, "peso_pendente": "10.0000", "peso_faturado": "0", "mais_7_dias_sem_emissao": 0}

    def fiscal_indicator_rows(self, indicator):
        self.calls.append(("fiscal_indicator_rows", indicator))
        return []

    def fiscal_report_rows(self, report_type, filters=None):
        self.calls.append(("fiscal_report_rows", report_type, filters))
        return []

    def history_rows(self):
        self.calls.append(("history_rows",))
        return [{"id": 1, "proposta": "CP00060", "area": "CONTROLE GERAL", "status_novo": "PROPOSAL_CREATED"}]

    def process_history_rows(self, process_id):
        self.calls.append(("process_history_rows", process_id))
        return [{"id": 2, "proposta": "CP00060", "area": "EXPEDICAO", "status_novo": "ENTREGUE"}]

    def partial_rows(self, filters=None):
        self.calls.append(("partial_rows", filters))
        return [{"id": 70, "proposta": "CP00070", "status_localizacao": "ENTREGUE_PARCIAL"}]

    def process_partials(self, process_id):
        self.calls.append(("process_partials", process_id))
        return [{"id": process_id, "proposta": "CP00070", "situacao_fluxo": "PARCIAL_COM_PENDENCIA"}]

    def warehouse_rows(self, filters=None):
        self.calls.append(("warehouse_rows", filters))
        return [
            {"id": 80, "proposta": "CP00080", "status_almoxarifado": "AGUARDANDO_CONFIRMACAO", "api_version": 4},
            {"id": 81, "proposta": "CP00081", "status_almoxarifado": "AGUARDANDO_CONFIRMACAO", "api_version": 4},
        ]

    def update_warehouse_status(self, process_id, version, status, observation=""):
        self.calls.append(("update_warehouse_status", process_id, version, status, observation))
        return {"id": process_id, "status_almoxarifado": status}

    def register_fiscal_emission(self, fiscal_record_id, emissions, numero_controle="", observacao=""):
        self.calls.append(("register_fiscal_emission", fiscal_record_id, emissions, numero_controle, observacao))
        return 6101

    def register_fiscal_batch(self, draft, operation_id=None):
        self.calls.append(("register_fiscal_batch", draft, operation_id))
        if self.fiscal_batch_error is not None:
            raise self.fiscal_batch_error
        return {"operation_id": operation_id or "op-1", "status": "confirmed", "proposals": [{"fiscal_record_id": row.get("proposal_id"), "emission_id": 9001} for row in draft]}

    def mark_fiscal_invoice_withdrawn(self, fiscal_record_id, observacao=""):
        self.calls.append(("mark_fiscal_invoice_withdrawn", fiscal_record_id, observacao))
        return fiscal_record_id

    def cancel_latest_fiscal_emission(self, fiscal_record_id, reason=""):
        self.calls.append(("cancel_latest_fiscal_emission", fiscal_record_id, reason))
        return 1

    def list_proposals(self, **kwargs):
        self.calls.append(("list_proposals", kwargs))
        return [
            {"id": 10, "proposta": "CP00010", "cliente": "ACME", "obra_site": "SITE A", "lote": "L1"},
            {"id": 11, "proposta": "CP00011", "cliente": "BETA", "obra_site": "SITE B", "lote": "L2"},
        ]

    def get_process(self, process_id):
        self.calls.append(("get_process", process_id))
        return {
            "id": process_id,
            "api_id": process_id,
            "api_version": 3,
            "proposta": "CP00010",
            "status_geral": "AGUARDANDO_LIBERACAO",
            "status_almoxarifado": "AGUARDANDO_CONFIRMACAO",
        }

    def release_to_production(self, process_id, version):
        self.calls.append(("release_to_production", process_id, version))
        return {"id": process_id, "status_geral": "LIBERADO_PRODUCAO"}

    def cancel_process(self, process_id, version, reason):
        self.calls.append(("cancel_process", process_id, version, reason))
        return {"id": process_id, "status_geral": "CANCELADA"}

    def galvanization_load_candidates(self, proposal="", client=""):
        self.calls.append(("galvanization_load_candidates", proposal, client))
        return [
            {"id": 30, "proposta": "CP00030", "cliente": "ACME", "status_galvanizacao": "AGUARDANDO_ENVIO"},
            {"id": 32, "proposta": "CP00032", "cliente": "BETA", "status_galvanizacao": "AGUARDANDO_ENVIO"},
        ]

    def galvanization_loads(self):
        self.calls.append(("galvanization_loads",))
        return [{"id": 7, "status": "LIBERADA_PARA_ENVIO"}]

    def galvanization_load_items(self, load_id):
        self.calls.append(("galvanization_load_items", load_id))
        return [{"processo_id": 30, "proposta": "CP00030", "cliente": "ACME", "peso_enviado": "10"}]

    def galvanization_load_proposal_items(self, load_id, process_id):
        self.calls.append(("galvanization_load_proposal_items", load_id, process_id))
        return [{"id": 70, "numero_item": "1"}]

    def galvanization_return_proposals(self, load_id):
        self.calls.append(("galvanization_return_proposals", load_id))
        return [{"carga_item_id": 80, "processo_id": 30}]

    def galvanization_return_items(self, load_id, process_id):
        self.calls.append(("galvanization_return_items", load_id, process_id))
        return [{"id": 81, "processo_id": process_id}]

    def get_galvanization_load_dict(self, load_id):
        self.calls.append(("get_galvanization_load_dict", load_id))
        return {"id": load_id, "status": "AGUARDANDO_LIBERACAO"}

    def galvanization_available_weight_info(self, process_id, load_id=None):
        self.calls.append(("galvanization_available_weight_info", process_id, load_id))
        return {"processo_id": process_id, "peso_sugerido": 10}

    def save_galvanization_load(self, driver, max_weight, expected_return_date, items, load_id=None):
        self.calls.append(("save_galvanization_load", driver, max_weight, expected_return_date, items, load_id))
        return 7

    def release_galvanization_load(self, load_id):
        self.calls.append(("release_galvanization_load", load_id))

    def register_galvanization_partial_return(self, load_id, returned_items, observation=""):
        self.calls.append(("register_galvanization_partial_return", load_id, returned_items, observation))
        return len(returned_items)


def official_service() -> tuple[BackendService, FakeOfficialProposalStorage]:
    service = BackendService.__new__(BackendService)
    storage = FakeOfficialProposalStorage()
    service.config = {"postgresql_official_proposals_enabled": True}
    service.user = {"id": 1, "login": "admin"}
    service.official_proposal_storage = storage
    service.can_edit = lambda _area: True
    return service, storage


class BackendOfficialProposalTests(unittest.TestCase):
    def test_official_user_management_uses_api_without_legacy_sqlite(self):
        service, storage = official_service()

        self.assertEqual(service.user_rows()[0]["nome"], "Admin")
        self.assertEqual(service.get_user(7)["login"], "operador")
        self.assertEqual(service.user_permissions(7)["users_permissions"], "VIEW")
        service.save_user({"nome": "Novo", "login": "novo", "password": "Senha123456", "perfil": "admin", "ativo": True})
        service.toggle_user(7)

        self.assertIn(("user_rows",), storage.calls)
        self.assertIn(("get_user", 7), storage.calls)
        self.assertIn(("save_user", {"nome": "Novo", "login": "novo", "password": "Senha123456", "perfil": "admin", "ativo": True, "permissions": {}}, None), storage.calls)
        self.assertIn(("toggle_user", 7), storage.calls)

    def test_official_save_uses_api_storage_without_legacy_sqlite_repo(self):
        service, storage = official_service()

        result = service.save_process({"proposta": "CP00010"}, import_metadata={"source": "MANUAL"})

        self.assertEqual(result, 321)
        self.assertEqual(storage.calls, [("save_process", {"proposta": "CP00010"}, None, {"source": "MANUAL"})])

    def test_official_proposal_items_use_api_storage_without_legacy_sqlite_repo(self):
        service, storage = official_service()

        items = service.proposal_items(10)

        self.assertEqual(items[0]["id"], 9001)
        self.assertEqual(storage.calls, [("proposal_items", 10)])

    def test_official_pending_production_items_use_api_without_legacy_sqlite(self):
        service, storage = official_service()

        self.assertEqual(service.proposal_items(10, pending_production=True)[0]["id"], 9002)
        self.assertEqual(service.proposal_items(10, pending_delivery=True)[0]["id"], 9003)
        self.assertEqual(storage.calls, [("production_items", 10, True), ("expedition_items", 10, True)])

    def test_official_process_rows_apply_local_text_filter_on_api_rows(self):
        service, storage = official_service()

        rows = service.process_rows("CONTROLE GERAL", {"text": "site b"})

        self.assertEqual([row["proposta"] for row in rows], ["CP00011"])
        self.assertEqual(storage.calls[0][0], "list_proposals")

    def test_official_control_general_uses_api_status_for_actions_without_legacy_sqlite(self):
        service, storage = official_service()

        self.assertEqual(
            service.list_status("CONTROLE GERAL"),
            [
                "AGUARDANDO_LIBERACAO",
                "LIBERADO_PRODUCAO",
                "EM_PRODUCAO",
                "EM_GALVANIZACAO",
                "EM_EXPEDICAO",
                "ENTREGUE",
                "CANCELADA",
            ],
        )
        self.assertEqual(service.next_status_options("CONTROLE GERAL", 10), ["LIBERADO_PRODUCAO", "CANCELADA"])
        self.assertEqual(service.common_next_statuses("CONTROLE GERAL", [10]), ["LIBERADO_PRODUCAO", "CANCELADA"])

        actions = service.process_actions(10, "CONTROLE GERAL")
        self.assertEqual([action["status"] for action in actions], ["LIBERADO_PRODUCAO", "CANCELADA"])

        service.update_status(10, "CONTROLE GERAL", "LIBERADO_PRODUCAO")
        self.assertIn(("release_to_production", 10, 3), storage.calls)

    def test_official_control_general_actions_respect_edit_permission(self):
        service, _storage = official_service()
        service.can_edit = lambda _area: False

        self.assertEqual(service.next_status_options("CONTROLE GERAL", 10), [])
        self.assertEqual(service.common_next_statuses("CONTROLE GERAL", [10]), [])
        self.assertEqual(service.process_actions(10, "CONTROLE GERAL"), [])

    def test_control_general_can_cancel_after_operational_start_but_not_after_completion(self):
        service, _storage = official_service()
        service._official_control_process = lambda _process_id: {
            "id": 10,
            "status_geral": "EM_GALVANIZACAO",
            "current_status": "ENVIADO_GALVANIZACAO",
            "is_cancelled": False,
            "is_completed": False,
        }
        self.assertEqual(service.next_status_options("CONTROLE GERAL", 10), ["CANCELADA"])
        self.assertEqual([action["status"] for action in service.process_actions(10, "CONTROLE GERAL")], ["CANCELADA"])

        service._official_control_process = lambda _process_id: {"id": 10, "status_geral": "ENTREGUE", "is_completed": True}
        self.assertEqual(service.next_status_options("CONTROLE GERAL", 10), [])
        self.assertEqual(service.process_actions(10, "CONTROLE GERAL"), [])

    def test_cancelled_process_has_no_actions_and_is_visible_only_in_control_general(self):
        service, _storage = official_service()
        cancelled = {"id": 10, "status_geral": "CANCELADA", "is_cancelled": True}
        service._official_control_process = lambda _process_id: cancelled
        self.assertEqual(service.next_status_options("CONTROLE GERAL", 10), [])
        self.assertEqual(service.process_actions(10, "CONTROLE GERAL"), [])
        self.assertTrue(service.process_visible_in_area(cancelled, "CONTROLE GERAL"))
        self.assertFalse(service.process_visible_in_area(cancelled, "PRODUCAO"))

    def test_official_administrative_correction_uses_api_without_legacy_sqlite(self):
        service, storage = official_service()
        service.user["api_superuser"] = True

        options = service.administrative_correction_options(20)
        preview = service.preview_administrative_correction(20, 5, "EXPEDICAO", "EM_SEPARACAO")
        service.administrative_correction(20, 5, "EXPEDICAO", "EM_SEPARACAO", "Ajuste homologacao", "admin-key-0001")

        self.assertEqual(options["version"], 5)
        self.assertTrue(preview["allowed"])
        self.assertIn(("administrative_correction_options", 20), storage.calls)
        self.assertIn(("preview_administrative_correction", 20, 5, "EXPEDICAO", "EM_SEPARACAO"), storage.calls)
        self.assertIn(("administrative_correction", 20, 5, "EXPEDICAO", "EM_SEPARACAO", "Ajuste homologacao", "admin-key-0001"), storage.calls)

    def test_official_administrative_correction_requires_superuser_before_api_call(self):
        service, storage = official_service()

        with self.assertRaisesRegex(Exception, "administradores"):
            service.administrative_correction(20, 5, "EXPEDICAO", "EM_SEPARACAO", "Ajuste homologacao", "admin-key-0001")

        self.assertFalse(any(call[0] == "administrative_correction" for call in storage.calls))

    def test_official_production_rows_and_start_use_api_without_legacy_sqlite(self):
        service, storage = official_service()

        rows = service.process_rows("PRODUCAO", {})
        actions_before = service.process_actions(20, "PRODUCAO")
        service.update_status(20, "PRODUCAO", "INICIADO", "Obs")
        actions_after = service.process_actions(20, "PRODUCAO")

        self.assertEqual(rows[0]["proposta"], "CP00020")
        self.assertEqual(storage.calls[0][0], "list_production_proposals")
        self.assertIn("Iniciar producao", [action["label"] for action in actions_before])
        self.assertIn(("start_production", 20, 5, "Obs"), storage.calls)
        self.assertEqual(service.next_status_options("PRODUCAO", 20), ["PARADO", "FINALIZADO_PARCIAL", "FINALIZADO"])
        self.assertEqual(service.common_next_statuses("PRODUCAO", [20]), ["PARADO", "FINALIZADO_PARCIAL", "FINALIZADO"])
        self.assertIn("Registrar producao", [action["label"] for action in actions_after])

        service.update_status(20, "PRODUCAO", "FINALIZADO", "Fim", [9002])
        self.assertIn(("complete_production_items", 20, 5, [9002], "Fim"), storage.calls)

    def test_official_pause_and_resume_use_distinct_api_commands(self):
        service, storage = official_service()
        storage.production_status = "INICIADO"

        started_actions = service.process_actions(20, "PRODUCAO")
        self.assertIn("Pausar producao", [action["label"] for action in started_actions])
        self.assertNotIn("Iniciar producao", [action["label"] for action in started_actions])
        service.update_status(20, "PRODUCAO", "PARADO", "Manutencao preventiva")
        self.assertIn(("pause_production", 20, 5, "Manutencao preventiva"), storage.calls)

        paused_actions = service.process_actions(20, "PRODUCAO")
        self.assertIn("Retomar producao", [action["label"] for action in paused_actions])
        self.assertNotIn("Pausar producao", [action["label"] for action in paused_actions])
        self.assertNotIn("Registrar producao", [action["label"] for action in paused_actions])
        self.assertEqual(service.next_status_options("PRODUCAO", 20), ["INICIADO"])

        service.update_status(20, "PRODUCAO", "INICIADO", "Material liberado")
        self.assertIn(("resume_production", 20, 5, "Material liberado"), storage.calls)

    def test_official_pause_requires_reason_before_calling_api(self):
        service, storage = official_service()
        storage.production_status = "INICIADO"

        with self.assertRaisesRegex(Exception, "motivo da pausa"):
            service.update_status(20, "PRODUCAO", "PARADO", "   ")
        self.assertFalse(any(call[0] == "pause_production" for call in storage.calls))

    def test_official_production_item_flow_and_weights_use_api_without_backup(self):
        service, storage = official_service()

        self.assertEqual(service.item_flow_summary(20)["total"], 1)
        self.assertEqual(service.update_item_flow(20, [{"id": 1}], "Producao"), 1)
        self.assertEqual(service.update_item_weights(20, {1: 2.5}), 1)

        self.assertIn(("production_item_flow_summary", 20), storage.calls)
        self.assertIn(("update_production_item_flow", 20, 5, [{"id": 1}], "Producao"), storage.calls)
        self.assertIn(("update_production_item_weights", 20, 5, {1: 2.5}), storage.calls)

    def test_official_production_actions_respect_edit_permission(self):
        service, _storage = official_service()
        service.can_edit = lambda _area: False

        self.assertEqual(service.next_status_options("PRODUCAO", 20), [])
        self.assertEqual(service.common_next_statuses("PRODUCAO", [20]), [])
        self.assertEqual(service.process_actions(20, "PRODUCAO"), [])

    def test_official_expedition_rows_actions_and_status_updates_use_api_without_legacy_sqlite(self):
        service, storage = official_service()

        rows = service.process_rows("EXPEDICAO", {"status": "EM_SEPARACAO"})
        self.assertEqual([row["proposta"] for row in rows], ["CP00040"])
        self.assertEqual(storage.calls[0][0], "list_expedition_proposals")

        actions_before = service.process_actions(40, "EXPEDICAO")
        self.assertEqual([action["status"] for action in actions_before], ["SEPARACAO_INICIADA", "SEPARADO"])
        self.assertEqual(service.next_status_options("EXPEDICAO", 40), ["SEPARACAO_INICIADA", "SEPARADO"])
        self.assertEqual(service.common_next_statuses("EXPEDICAO", [40]), ["SEPARACAO_INICIADA", "SEPARADO"])

        service.update_status(40, "EXPEDICAO", "SEPARACAO_INICIADA", "inicio")
        service.update_status(40, "EXPEDICAO", "SEPARADO", "separado", [9003])
        self.assertIn(("start_expedition_separation", 40, 6, "inicio"), storage.calls)
        self.assertIn(("separate_expedition_items", 40, 6, [9003], "separado"), storage.calls)

        storage.expedition_status = "SEPARADO"
        self.assertEqual(service.next_status_options("EXPEDICAO", 40), ["ENTREGUE_PARCIAL", "ENTREGUE"])
        self.assertEqual([action["id"] for action in service.process_actions(40, "EXPEDICAO")], ["REGISTER_DELIVERY"])
        service.update_status(40, "EXPEDICAO", "ENTREGUE_PARCIAL", "retirada parcial", [9003])
        self.assertIn(("deliver_expedition_items", 40, 6, [9003], "retirada parcial"), storage.calls)

    def test_official_expedition_batch_and_remanagement_respect_permissions(self):
        service, storage = official_service()

        storage.expedition_status = "SEPARADO"
        sources = service.remanagement_source_candidates(exclude_process_id=41, search="")
        self.assertEqual([row["id"] for row in sources], [40])
        service.deliver_by_material_remanagement(50, 40, "obs", [9003])
        self.assertIn(("deliver_by_material_remanagement", 50, 40, "obs", [9003]), storage.calls)

        service.can_edit = lambda _area: False
        self.assertEqual(service.next_status_options("EXPEDICAO", 40), [])
        self.assertEqual(service.common_next_statuses("EXPEDICAO", [40]), [])
        self.assertEqual(service.process_actions(40, "EXPEDICAO"), [])
        with self.assertRaisesRegex(Exception, "Expedicao|remanejamentos"):
            service.update_status(40, "EXPEDICAO", "ENTREGUE", "sem permissao")
        with self.assertRaisesRegex(Exception, "remanejamentos"):
            service.deliver_by_material_remanagement(50, 40, "obs", [9003])

    def test_official_fiscal_uses_api_storage_without_legacy_sqlite(self):
        service, storage = official_service()

        self.assertEqual(service.fiscal_rows({"text": "CP"})[0]["fiscal_processo_id"], 60)
        self.assertEqual(service.fiscal_items(60)[0]["id"], 6001)
        self.assertEqual(service.fiscal_emissions(60)[0]["id"], 6101)
        self.assertEqual(service.fiscal_movements(60)[0]["id"], 6301)
        self.assertEqual(service.fiscal_indicators()["falta_emitir"], 1)
        self.assertEqual(service.fiscal_indicator_rows("pendencia_critica"), [])
        self.assertEqual(service.fiscal_report_rows("PENDENTES"), [])

        self.assertTrue(service.can_register_fiscal_emission())
        self.assertTrue(service.can_cancel_fiscal_emission())
        self.assertEqual(service.register_fiscal_emission(60, [{"fiscal_item_id": 6001}], "NF-1", "obs"), 6101)
        self.assertEqual(service.mark_fiscal_invoice_withdrawn(60, "retirada"), 60)
        self.assertEqual(service.cancel_latest_fiscal_emission(60, "correcao"), 1)

        self.assertIn(("fiscal_rows", {"text": "CP"}), storage.calls)
        self.assertIn(("register_fiscal_emission", 60, [{"fiscal_item_id": 6001}], "NF-1", "obs"), storage.calls)
        self.assertIn(("mark_fiscal_invoice_withdrawn", 60, "retirada"), storage.calls)
        self.assertIn(("cancel_latest_fiscal_emission", 60, "correcao"), storage.calls)

    def test_fiscal_partial_group_never_hides_mother_row(self):
        service = BackendService.__new__(BackendService)
        rows = service._merge_partial_operational_rows(
            [
                {"id": 100, "fiscal_processo_id": 500, "proposta": "CP05378", "status_fiscal": "NOTA_FISCAL_PARCIAL"},
                {"id": 101, "fiscal_processo_id": 501, "proposta": "CP05378-1", "parent_proposal_id": 100, "partial_number": 1, "status_fiscal": "NOTA_FISCAL_PARCIAL"},
                {"id": 102, "fiscal_processo_id": 502, "proposta": "CP05378-2", "parent_proposal_id": 100, "partial_number": 2, "status_fiscal": "NOTA_FISCAL_PARCIAL"},
            ],
            "FISCAL",
        )

        assert len(rows) == 2
        mother = next(row for row in rows if row["proposta"] == "CP05378")
        grouped_children = next(row for row in rows if row.get("grouped_partial"))
        assert mother["fiscal_processo_id"] == 500
        assert grouped_children["fiscal_processo_ids"] == [501, 502]

    def test_expedition_children_with_same_status_are_grouped(self):
        service = BackendService.__new__(BackendService)
        storage = FakeOfficialProposalStorage()
        storage.list_expedition_proposals = lambda **_kwargs: [
            {"id": 30, "proposta": "CP05390-1", "parent_proposal_id": 26, "partial_number": 1,
             "status_expedicao": "EM_SEPARACAO", "quantidade_itens": 2},
            {"id": 31, "proposta": "CP05390-2", "parent_proposal_id": 26, "partial_number": 2,
             "status_expedicao": "EM_SEPARACAO", "quantidade_itens": 1},
        ]
        service.official_proposal_storage = storage

        rows = service.process_rows("EXPEDICAO", {})

        assert len(rows) == 1
        assert rows[0]["proposta"] == "CP05390-1,2"
        assert rows[0]["proposal_ids"] == [30, 31]
        assert rows[0]["quantidade_itens"] == 3

    def test_official_fiscal_write_actions_respect_permission(self):
        service, _storage = official_service()
        service.can_edit = lambda _area: False

        self.assertFalse(service.can_register_fiscal_emission())
        self.assertFalse(service.can_cancel_fiscal_emission())
        with self.assertRaisesRegex(Exception, "emissao fiscal"):
            service.register_fiscal_emission(60, [{"fiscal_item_id": 6001}], "NF-1", "obs")
        with self.assertRaisesRegex(Exception, "retirada fiscal"):
            service.mark_fiscal_invoice_withdrawn(60, "retirada")
        with self.assertRaisesRegex(Exception, "cancelar emissao fiscal"):
            service.cancel_latest_fiscal_emission(60, "correcao")

    def test_official_history_uses_api_storage_without_legacy_sqlite(self):
        service, storage = official_service()

        self.assertEqual(service.history_rows()[0]["status_novo"], "PROPOSAL_CREATED")
        self.assertEqual(service.process_history_rows(60)[0]["status_novo"], "ENTREGUE")
        self.assertIn(("history_rows",), storage.calls)
        self.assertIn(("process_history_rows", 60), storage.calls)

    def test_official_partials_use_api_storage_without_legacy_sqlite(self):
        service, storage = official_service()

        rows = service.process_rows("PARCIAIS", {"text": "CP00070"})
        partials = service.process_partials(70)

        self.assertEqual(rows[0]["status_localizacao"], "ENTREGUE_PARCIAL")
        self.assertEqual(partials[0]["situacao_fluxo"], "PARCIAL_COM_PENDENCIA")
        self.assertIn(("partial_rows", {"text": "CP00070"}), storage.calls)
        self.assertIn(("process_partials", 70), storage.calls)

    def test_official_warehouse_rows_actions_and_updates_use_api_without_legacy_sqlite(self):
        service, storage = official_service()

        rows = service.process_rows("ALMOXARIFADO", {"text": "CP00080"})
        actions = service.process_actions(80, "ALMOXARIFADO")
        options = service.next_status_options("ALMOXARIFADO", 80)
        common = service.common_next_statuses("ALMOXARIFADO", [80, 81])
        service.update_status(80, "ALMOXARIFADO", "EM_SEPARACAO", "tem parafusos")

        self.assertEqual(rows[0]["status_almoxarifado"], "AGUARDANDO_CONFIRMACAO")
        self.assertEqual(options, ["EM_SEPARACAO", "SEM_PARAFUSOS"])
        self.assertEqual(common, ["EM_SEPARACAO", "SEM_PARAFUSOS"])
        self.assertTrue(any(action["status"] == "EM_SEPARACAO" for action in actions))
        self.assertIn(("warehouse_rows", {"text": "CP00080"}), storage.calls)
        self.assertIn(("update_warehouse_status", 80, 3, "EM_SEPARACAO", "tem parafusos"), storage.calls)

    def test_official_warehouse_blocks_update_without_edit_permission(self):
        service, storage = official_service()
        service.can_edit = lambda area: area != "ALMOXARIFADO"

        self.assertEqual(service.process_actions(80, "ALMOXARIFADO"), [])
        with self.assertRaisesRegex(Exception, "Almoxarifado"):
            service.update_status(80, "ALMOXARIFADO", "EM_SEPARACAO", "bloqueado")
        self.assertNotIn(("update_warehouse_status", 80, 3, "EM_SEPARACAO", "bloqueado"), storage.calls)

    def test_official_galvanization_uses_api_without_legacy_sqlite(self):
        service, storage = official_service()

        self.assertEqual(service.galvanization_load_candidates("CP", "ACME")[0]["id"], 30)
        self.assertEqual(service.galvanization_loads()[0]["id"], 7)
        self.assertEqual(service.galvanization_load_items(7)[0]["processo_id"], 30)
        self.assertEqual(service.galvanization_load_proposal_items(7, 30)[0]["id"], 70)
        self.assertEqual(service.galvanization_return_proposals(7)[0]["carga_item_id"], 80)
        self.assertEqual(service.galvanization_return_items(7, 30)[0]["id"], 81)
        self.assertEqual(service.get_galvanization_load_dict(7)["status"], "AGUARDANDO_LIBERACAO")
        self.assertEqual(service.galvanization_available_weight_info(30)["peso_sugerido"], 10)
        self.assertEqual(service.save_galvanization_load("Motorista", "", "", [{"process_id": 30}]), 7)
        service.release_galvanization_load(7)
        self.assertEqual(service.register_galvanization_partial_return(7, [{"detail_id": 81}], "obs"), 1)
        service.mark_galvanization_load_returned(7)

        self.assertIn(("galvanization_load_candidates", "CP", "ACME"), storage.calls)
        self.assertIn(("save_galvanization_load", "Motorista", "", "", [{"process_id": 30}], None), storage.calls)
        self.assertIn(("release_galvanization_load", 7), storage.calls)
        self.assertIn(("register_galvanization_partial_return", 7, [{"detail_id": 81}], "obs"), storage.calls)
        self.assertIn(("register_galvanization_partial_return", 7, [{"processo_id": 30, "proposal_level": True}], "Retorno total pelo desktop"), storage.calls)

    def test_official_galvanization_rows_actions_and_loads_use_api_without_legacy_sqlite(self):
        service, storage = official_service()

        rows = service.process_rows("GALVANIZACAO", {})
        by_id = {row["id"]: row for row in rows}

        self.assertEqual(by_id[32]["status_galvanizacao"], "AGUARDANDO_ENVIO")
        self.assertEqual(by_id[30]["status_galvanizacao"], "ENVIADO_GALVANIZACAO")
        self.assertEqual(by_id[30]["carga_galvanizacao"], 7)
        self.assertEqual(service.process_loads(30)[0]["id"], 7)

        candidate_actions = service.process_actions(32, "GALVANIZACAO")
        sent_actions = service.process_actions(30, "GALVANIZACAO")

        self.assertEqual([action["id"] for action in candidate_actions], ["MANAGE_LOAD"])
        self.assertEqual([action["id"] for action in sent_actions], ["REGISTER_GALVANIZATION_RETURN"])
        self.assertIn(("galvanization_load_items", 7), storage.calls)

    def test_galvanization_partial_load_return_reflects_each_proposal_own_state(self):
        # Regressao: uma carga em RETORNO_PARCIAL nao deve marcar TODAS as
        # propostas dela como "Retornou parcialmente" - cada proposta reflete
        # seu proprio retorno (item['status_retorno'], ja calculado pela API
        # por proposta), nunca o status agregado da carga inteira.
        class FakePartialReturnStorage:
            def galvanization_load_candidates(self, proposal='', client=''):
                return []

            def galvanization_loads(self):
                return [{'id': 5, 'status': 'RETORNO_PARCIAL'}]

            def galvanization_load_items(self, load_id):
                return [
                    {'processo_id': 10, 'proposta': 'CP00010', 'cliente': 'A', 'peso_enviado': '10', 'status_retorno': 'RETORNADO'},
                    {'processo_id': 20, 'proposta': 'CP00020', 'cliente': 'B', 'peso_enviado': '10', 'status_retorno': 'RETORNO_PARCIAL'},
                    {'processo_id': 30, 'proposta': 'CP00030', 'cliente': 'C', 'peso_enviado': '10', 'status_retorno': 'AGUARDANDO_RETORNO'},
                ]

        service = BackendService.__new__(BackendService)
        service.official_proposal_storage = FakePartialReturnStorage()

        rows = service._official_galvanization_rows({})
        by_id = {row['id']: row for row in rows}

        # Proposta totalmente retornada nao permanece na fila operacional da
        # Galvanizacao; somente as propostas ainda pendentes sao projetadas.
        self.assertNotIn(10, by_id)
        self.assertEqual(by_id[20]['status_galvanizacao'], 'RETORNOU_PARCIAL')
        self.assertEqual(by_id[30]['status_galvanizacao'], 'ENVIADO_GALVANIZACAO')
        # A carga em si (carga_galvanizacao) e a mesma para as 3 - so a
        # projecao de status por proposta muda, o status da carga nao.
        self.assertTrue(all(row['carga_galvanizacao'] == 5 for row in by_id.values()))

    def test_galvanization_loaded_child_is_not_duplicated_by_zero_balance_candidate(self):
        class FakeLoadedChildStorage:
            def galvanization_load_candidates(self, proposal='', client=''):
                return [{
                    'id': 30,
                    'processo_id': 30,
                    'proposta': 'CP05390-1',
                    'cliente': 'MNS ENGENHARIA',
                    'available_quantity': '0.0000',
                    'status_galvanizacao': 'AGUARDANDO_ENVIO',
                }]

            def galvanization_loads(self):
                return [{'id': 30, 'status': 'AGUARDANDO_LIBERACAO'}]

            def galvanization_load_items(self, load_id):
                return [{'processo_id': 30, 'proposta': 'CP05390-1', 'status_retorno': 'AGUARDANDO_RETORNO'}]

        service = BackendService.__new__(BackendService)
        service.official_proposal_storage = FakeLoadedChildStorage()

        rows = service._official_galvanization_rows({})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['id'], 30)
        self.assertEqual(rows[0]['carga_galvanizacao'], 30)

    def test_official_galvanization_actions_respect_edit_permission(self):
        service, _storage = official_service()
        service.can_edit = lambda _area: False

        self.assertFalse(service.can_mount_galvanization_load())
        self.assertEqual(service.process_actions(32, "GALVANIZACAO"), [])
        with self.assertRaisesRegex(AppError, "galvanizacao"):
            service.save_galvanization_load("Motorista", "", "", [{"process_id": 32}])

    def test_official_api_failure_is_converted_to_app_error(self):
        service, _storage = official_service()
        service.official_proposal_storage.should_fail = True

        with self.assertRaises(AppError) as ctx:
            service.save_process({"proposta": "CP00010"})

        self.assertIn("servidor esta indisponivel", str(ctx.exception))

    def test_register_fiscal_batch_delegates_to_official_storage(self):
        service, storage = official_service()
        draft = [{"proposal_id": 60, "invoice_number": "NF-1", "selection_type": "TOTAL", "items": [{"item_id": 6001}]}]

        result = service.register_fiscal_batch(draft, operation_id="op-123")

        self.assertEqual(result["status"], "confirmed")
        self.assertIn(("register_fiscal_batch", draft, "op-123"), storage.calls)

    def test_register_fiscal_batch_preserves_backend_error_code(self):
        """Regression: a real API error_code must survive the AppError wrapping.

        Before the fix, BackendService.register_fiscal_batch (and the shared
        `_api_app_error` helper it uses) discarded `error_code`/`technical_message`
        from the underlying ApiClientError, so the fiscal batch confirmation
        dialog could never map the failure to a useful message and always fell
        back to the generic "Nao foi possivel concluir a emissao fiscal.",
        regardless of what actually failed on the server.
        """
        service, storage = official_service()
        storage.fiscal_batch_error = ApiBusinessError(
            "FISCAL_ITEM_INVALID", "Um item fiscal ficou indisponivel para esta proposta.", status_code=409, request_id="req-1"
        )

        with self.assertRaises(AppError) as ctx:
            service.register_fiscal_batch([{"proposal_id": 60, "invoice_number": "NF-1", "items": []}])

        self.assertEqual(ctx.exception.error_code, "FISCAL_ITEM_INVALID")
        self.assertIn("indisponivel", str(ctx.exception))

    def test_register_fiscal_batch_requires_permission(self):
        service, _storage = official_service()
        service.can_edit = lambda _area: False

        with self.assertRaisesRegex(Exception, "emissao fiscal"):
            service.register_fiscal_batch([{"proposal_id": 60, "invoice_number": "NF-1", "items": []}])


class DesktopApiErrorContractTests(unittest.TestCase):
    def test_api_business_errors_cover_not_found_and_conflict(self):
        for status_code, error_code in ((404, "PROPOSAL_NOT_FOUND"), (409, "PROPOSAL_NUMBER_ALREADY_EXISTS")):
            with self.subTest(status_code=status_code):
                error = ApiBusinessError(error_code, "erro", status_code=status_code, request_id="REQ")
                self.assertEqual(error.error_code, error_code)
                self.assertEqual(error.status_code, status_code)


if __name__ == "__main__":
    unittest.main()
