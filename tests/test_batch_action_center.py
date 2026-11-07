from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication, QMessageBox

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.action_center.batch_action_center import BatchProposalActionCenter
from app.ui.action_center.descriptor import ActionCategory


def _run_synchronously(_owner, operation, on_success, on_error):
    try:
        result = operation()
    except Exception as exc:
        on_error(exc)
    else:
        on_success(result)
    return None


class FakeBatchService:
    """Mirrors just the surface `BatchProposalActionCenter` calls -
    common_next_statuses/action_label/update_status (STATUS areas),
    proposal_items (Expedicao retirada) and validate_batch_selection
    (revalidation on click)."""

    def __init__(
        self,
        area: str = "CONTROLE GERAL",
        common_statuses: list[str] | None = None,
        palette_name: str = "claro",
        pending_delivery_items: dict[int, list[dict]] | None = None,
        open_loads: list[dict] | None = None,
        process_loads: dict[int, list[dict]] | None = None,
        load_candidates: list[dict] | None = None,
        flow_summaries: dict[int, dict] | None = None,
    ):
        self.area = area
        self.palette = OFFICIAL_COLOR_PALETTES[palette_name]
        self._common_statuses = common_statuses if common_statuses is not None else ["LIBERADO_PRODUCAO", "CANCELADA"]
        self.calls: list[tuple] = []
        self.validation_result: dict | None = None
        self._pending_delivery_items = pending_delivery_items or {}
        self._open_loads = open_loads if open_loads is not None else [{"id": 14, "status": "AGUARDANDO_LIBERACAO"}]
        self._process_loads = process_loads or {}
        self._flow_summaries = flow_summaries
        # Por padrao, 10 e 20 (os ids usados na maioria dos testes de
        # GALVANIZACAO) tem saldo elegivel para montar carga - assim os
        # testes que nao mexem com elegibilidade continuam vendo os cards
        # MANAGE_LOAD_*. Passe load_candidates=[] para simular uma selecao
        # ja totalmente enviada (sem saldo livre).
        self._load_candidates = (
            load_candidates
            if load_candidates is not None
            else [
                {"id": 10, "_galvanization_items": [{"item_id": 1, "available_quantity": 2}]},
                {"id": 20, "_galvanization_items": [{"item_id": 2, "available_quantity": 3}]},
            ]
        )

    def galvanization_loads(self):
        self.calls.append(("galvanization_loads",))
        return list(self._open_loads)

    def galvanization_load_candidates(self, proposal="", client_name=""):
        self.calls.append(("galvanization_load_candidates",))
        return list(self._load_candidates)

    def process_loads(self, process_id):
        self.calls.append(("process_loads", process_id))
        return list(self._process_loads.get(process_id, []))

    def add_items_to_galvanization_load(self, load_id, *, item_ids=None, proposal_ids=None):
        self.calls.append(("add_items_to_galvanization_load", load_id, item_ids, proposal_ids))
        return {"id": load_id, "added_item_ids": [1, 2]}

    def common_next_statuses(self, area, process_ids):
        self.calls.append(("common_next_statuses", area, tuple(process_ids)))
        return list(self._common_statuses)

    def item_flow_summary(self, process_id):
        self.calls.append(("item_flow_summary", process_id))
        if self._flow_summaries is None:
            return {"total": 1, "undefined_count": 0}
        return dict(self._flow_summaries[process_id])

    def action_label(self, area, status):
        return {
            "LIBERADO_PRODUCAO": "Liberar para producao",
            "CANCELADA": "Cancelar proposta",
            "INICIADO": "Iniciar ou retomar producao",
        }.get(
            status, status.replace("_", " ").title()
        )

    def update_status(self, process_id, area, status, observation="", item_ids=None, produced_weight=None):
        self.calls.append(("update_status", process_id, area, status, observation, item_ids))
        return {}

    def validate_batch_selection(self, area, process_ids, action_id):
        self.calls.append(("validate_batch_selection", area, tuple(process_ids), action_id))
        if self.validation_result is not None:
            return self.validation_result
        return {"valid_ids": list(process_ids), "incompatible": [], "common_statuses": [], "global_reason": ""}

    def proposal_items(self, process_id, pending_production=False, pending_delivery=False):
        if pending_delivery:
            return self._pending_delivery_items.get(process_id, [])
        return []

    def get_process_dict(self, process_id):
        return {"id": process_id, "proposta": f"CP{process_id}"}


class ActionListPerAreaTests(unittest.TestCase):
    """Cada area computa cards diferentes - nenhuma regra de disponibilidade
    e inventada aqui, so a leitura de common_next_statuses()/area especifica
    (mesma logica que BatchStatusDialog.refresh_selected() ja tinha)."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_control_general_shows_one_card_per_common_status(self):
        service = FakeBatchService("CONTROLE GERAL", common_statuses=["LIBERADO_PRODUCAO", "CANCELADA"])
        dialog = BatchProposalActionCenter(service, [10, 20], "CONTROLE GERAL")
        ids_status = {(a.id, a.status) for a in dialog.actions}
        self.assertEqual(ids_status, {("STATUS", "LIBERADO_PRODUCAO"), ("STATUS", "CANCELADA")})

    def test_production_collapses_finalizado_into_register_production_card(self):
        service = FakeBatchService("PRODUCAO", common_statuses=["INICIADO", "FINALIZADO", "FINALIZADO_PARCIAL"])
        dialog = BatchProposalActionCenter(service, [10, 20], "PRODUCAO")
        ids = [a.id for a in dialog.actions]
        self.assertIn("REGISTER_PRODUCTION", ids)
        self.assertNotIn(("STATUS", "FINALIZADO"), [(a.id, a.status) for a in dialog.actions])
        self.assertIn(("STATUS", "INICIADO"), [(a.id, a.status) for a in dialog.actions])
        self.assertEqual(dialog.actions[0].id, "DEFINE_ITEM_FLOW")
        self.assertEqual(dialog.actions[0].label, "Redefinir fluxo dos itens")

    def test_production_without_defined_flow_only_offers_definition(self):
        service = FakeBatchService(
            "PRODUCAO",
            common_statuses=["INICIADO", "FINALIZADO"],
            flow_summaries={
                10: {"total": 2, "undefined_count": 2},
                20: {"total": 1, "undefined_count": 1},
            },
        )
        dialog = BatchProposalActionCenter(service, [10, 20], "PRODUCAO")

        self.assertEqual([(action.id, action.label) for action in dialog.actions], [("DEFINE_ITEM_FLOW", "Definir fluxo dos itens")])
        self.assertFalse(any(call[0] == "common_next_statuses" for call in service.calls))

    def test_production_with_defined_flow_orders_redefinition_before_start(self):
        service = FakeBatchService("PRODUCAO", common_statuses=["INICIADO"])
        dialog = BatchProposalActionCenter(service, [10, 20], "PRODUCAO")

        self.assertEqual(
            [(action.id, action.status, action.label) for action in dialog.actions],
            [
                ("DEFINE_ITEM_FLOW", "", "Redefinir fluxo dos itens"),
                ("STATUS", "INICIADO", "Iniciar ou retomar producao"),
            ],
        )

    def test_mixed_flow_selection_prioritizes_definition_and_hides_start(self):
        service = FakeBatchService(
            "PRODUCAO",
            common_statuses=["INICIADO"],
            flow_summaries={
                10: {"total": 2, "undefined_count": 0},
                20: {"total": 2, "undefined_count": 1},
            },
        )
        dialog = BatchProposalActionCenter(service, [10, 20], "PRODUCAO")

        self.assertEqual([(action.id, action.label) for action in dialog.actions], [("DEFINE_ITEM_FLOW", "Definir fluxo dos itens")])
        self.assertFalse(any(action.status == "INICIADO" for action in dialog.actions))

    def test_expedicao_collapses_entregue_into_register_delivery_card(self):
        service = FakeBatchService("EXPEDICAO", common_statuses=["SEPARADO", "ENTREGUE", "ENTREGUE_PARCIAL"])
        dialog = BatchProposalActionCenter(service, [10, 20], "EXPEDICAO")
        ids = [a.id for a in dialog.actions]
        self.assertIn("REGISTER_DELIVERY", ids)
        self.assertNotIn("DEFINE_ITEM_FLOW", ids)

    def test_almoxarifado_shows_plain_status_cards_without_extras(self):
        service = FakeBatchService("ALMOXARIFADO", common_statuses=["SEPARADO"])
        dialog = BatchProposalActionCenter(service, [10, 20], "ALMOXARIFADO")
        self.assertEqual([(a.id, a.status) for a in dialog.actions], [("STATUS", "SEPARADO")])

    def test_galvanizacao_shows_the_manage_load_and_return_cards_when_both_apply(self):
        service = FakeBatchService(
            "GALVANIZACAO",
            process_loads={10: [{"id": 30, "status": "LIBERADA_PARA_ENVIO"}], 20: []},
        )
        dialog = BatchProposalActionCenter(service, [10, 20], "GALVANIZACAO")
        self.assertEqual(
            [a.id for a in dialog.actions],
            ["MANAGE_LOAD_EXISTING", "MANAGE_LOAD_NEW", "REGISTER_RETURN"],
        )
        # Galvanizacao nao suporta common_next_statuses - nunca deve ser chamado
        self.assertFalse(any(call[0] == "common_next_statuses" for call in service.calls))

    def test_galvanizacao_shows_only_return_when_selection_has_no_free_balance(self):
        # As propostas selecionadas ja foram totalmente enviadas para uma
        # carga ativa - "Adicionar a uma carga"/"Criar nova carga" nao se
        # aplicam mais, so "Registrar retorno".
        service = FakeBatchService(
            "GALVANIZACAO",
            load_candidates=[],
            process_loads={10: [{"id": 30, "status": "LIBERADA_PARA_ENVIO"}], 20: [{"id": 30, "status": "LIBERADA_PARA_ENVIO"}]},
        )
        dialog = BatchProposalActionCenter(service, [10, 20], "GALVANIZACAO")
        self.assertEqual([a.id for a in dialog.actions], ["REGISTER_RETURN"])

    def test_galvanizacao_ignores_candidates_with_zero_available_quantity(self):
        # Bug real: a API pode listar o item em _galvanization_items mesmo
        # com saldo zerado (GalvanizationLoadDialog._add_item_entry ja se
        # protege disso) - lista nao-vazia sozinha nao pode significar
        # "tem o que adicionar".
        service = FakeBatchService(
            "GALVANIZACAO",
            load_candidates=[
                {"id": 10, "_galvanization_items": [{"item_id": 1, "available_quantity": 0}]},
                {"id": 20, "_galvanization_items": [{"item_id": 2, "available_quantity": "0"}]},
            ],
            process_loads={10: [{"id": 30, "status": "LIBERADA_PARA_ENVIO"}], 20: [{"id": 30, "status": "LIBERADA_PARA_ENVIO"}]},
        )
        dialog = BatchProposalActionCenter(service, [10, 20], "GALVANIZACAO")
        self.assertEqual([a.id for a in dialog.actions], ["REGISTER_RETURN"])

    def test_galvanizacao_shows_only_manage_load_when_nothing_is_returnable_yet(self):
        service = FakeBatchService("GALVANIZACAO", process_loads={})
        dialog = BatchProposalActionCenter(service, [10, 20], "GALVANIZACAO")
        self.assertEqual([a.id for a in dialog.actions], ["MANAGE_LOAD_EXISTING", "MANAGE_LOAD_NEW"])

    def test_galvanizacao_shows_empty_state_when_neither_applies(self):
        service = FakeBatchService("GALVANIZACAO", load_candidates=[], process_loads={})
        dialog = BatchProposalActionCenter(service, [10, 20], "GALVANIZACAO")
        self.assertEqual(dialog.actions, [])

    def test_no_common_status_shows_empty_state(self):
        service = FakeBatchService("ALMOXARIFADO", common_statuses=[])
        dialog = BatchProposalActionCenter(service, [10, 20], "ALMOXARIFADO")
        self.assertEqual(dialog.actions, [])

    def test_at_most_one_primary_card(self):
        service = FakeBatchService("PRODUCAO", common_statuses=["INICIADO"])
        dialog = BatchProposalActionCenter(service, [10, 20], "PRODUCAO")
        primaries = [a for a in dialog.actions if a.category == ActionCategory.PRIMARY]
        self.assertLessEqual(len(primaries), 1)


class HeaderAndEmptyStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_header_shows_proposal_count(self):
        service = FakeBatchService("CONTROLE GERAL")
        dialog = BatchProposalActionCenter(service, [10, 20, 30], "CONTROLE GERAL")
        self.assertIn("3 propostas selecionadas", dialog._title_label.text())

    def test_header_singular_for_one_proposal(self):
        service = FakeBatchService("CONTROLE GERAL")
        dialog = BatchProposalActionCenter(service, [10], "CONTROLE GERAL")
        self.assertIn("1 proposta selecionada", dialog._title_label.text())

    def test_opening_and_cancelling_does_not_write(self):
        service = FakeBatchService("CONTROLE GERAL")
        dialog = BatchProposalActionCenter(service, [10, 20], "CONTROLE GERAL")
        dialog.observation.setPlainText("rascunho que ninguem deve gravar")
        dialog.reject()
        self.assertFalse(any(call[0] == "update_status" for call in service.calls))
        self.assertFalse(dialog.changed)


class StatusCardRoutingTests(unittest.TestCase):
    """Card de STATUS: confirma, revalida, aplica a cada process_id em
    segundo plano e fecha reportando falhas quando existirem."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_confirmed_status_card_applies_to_every_selected_id(self):
        service = FakeBatchService("CONTROLE GERAL", common_statuses=["LIBERADO_PRODUCAO"])
        dialog = BatchProposalActionCenter(service, [10, 20], "CONTROLE GERAL")
        action = next(a for a in dialog.actions if a.id == "STATUS")
        with patch("app.ui.action_center.batch_action_center.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch("app.ui.action_center.batch_action_center.start_worker", side_effect=_run_synchronously):
            dialog.run_action(action)
        update_calls = [call for call in service.calls if call[0] == "update_status"]
        self.assertEqual({call[1] for call in update_calls}, {10, 20})
        self.assertTrue(dialog.changed)
        self.assertTrue(dialog.result())

    def test_declining_confirmation_does_not_write(self):
        service = FakeBatchService("CONTROLE GERAL", common_statuses=["CANCELADA"])
        dialog = BatchProposalActionCenter(service, [10, 20], "CONTROLE GERAL")
        action = next(a for a in dialog.actions if a.id == "STATUS")
        with patch("app.ui.action_center.batch_action_center.QMessageBox.question", return_value=QMessageBox.No):
            dialog.run_action(action)
        self.assertFalse(any(call[0] == "update_status" for call in service.calls))
        self.assertFalse(dialog.changed)

    def test_pausing_production_without_observation_is_blocked(self):
        service = FakeBatchService("PRODUCAO", common_statuses=["PARADO"])
        dialog = BatchProposalActionCenter(service, [10, 20], "PRODUCAO")
        action = next(a for a in dialog.actions if a.id == "STATUS" and a.status == "PARADO")
        with patch("app.ui.action_center.batch_action_center.QMessageBox.warning") as warning, patch(
            "app.ui.action_center.batch_action_center.QMessageBox.question"
        ) as question:
            dialog.run_action(action)
        warning.assert_called_once()
        question.assert_not_called()
        self.assertFalse(any(call[0] == "update_status" for call in service.calls))

    def test_revalidation_blocks_stale_selection_before_confirming(self):
        service = FakeBatchService("CONTROLE GERAL", common_statuses=["CANCELADA"])
        service.validation_result = {
            "valid_ids": [10],
            "incompatible": [{"id": 20, "proposta": "CP20", "reason": "estado alterado"}],
            "common_statuses": [],
            "global_reason": "",
        }
        dialog = BatchProposalActionCenter(service, [10, 20], "CONTROLE GERAL")
        action = next(a for a in dialog.actions if a.id == "STATUS")
        with patch("app.ui.action_center.batch_action_center.QMessageBox.warning") as warning, patch(
            "app.ui.action_center.batch_action_center.QMessageBox.question"
        ) as question:
            dialog.run_action(action)
        warning.assert_called_once()
        question.assert_not_called()
        self.assertFalse(any(call[0] == "update_status" for call in service.calls))

    def test_partial_failure_is_reported_but_dialog_still_completes(self):
        service = FakeBatchService("CONTROLE GERAL", common_statuses=["CANCELADA"])

        def flaky_update(process_id, *_args, **_kwargs):
            if process_id == 20:
                raise RuntimeError("versao desatualizada")
            return {}

        service.update_status = flaky_update
        dialog = BatchProposalActionCenter(
            service, [10, 20], "CONTROLE GERAL", proposal_labels={10: "CP10", 20: "CP20"}
        )
        action = next(a for a in dialog.actions if a.id == "STATUS")
        with patch("app.ui.action_center.batch_action_center.QMessageBox.question", return_value=QMessageBox.Yes), \
             patch("app.ui.action_center.batch_action_center.start_worker", side_effect=_run_synchronously), \
             patch("app.ui.action_center.batch_action_center.QMessageBox.warning") as warning:
            dialog.run_action(action)
        warning.assert_called_once()
        self.assertIn("CP20", warning.call_args.args[2])
        self.assertTrue(dialog.changed)
        self.assertTrue(dialog.result())


class SpecializedDialogRoutingTests(unittest.TestCase):
    """REGISTER_PRODUCTION, REGISTER_DELIVERY, DEFINE_ITEM_FLOW e MANAGE_LOAD
    encaminham para exatamente o mesmo dialogo especializado que a acao
    individual correspondente ja usa."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_register_production_opens_production_registration_dialog_with_exact_ids(self):
        service = FakeBatchService("PRODUCAO", common_statuses=["FINALIZADO"])
        dialog = BatchProposalActionCenter(service, [10, 20], "PRODUCAO")
        action = next(a for a in dialog.actions if a.id == "REGISTER_PRODUCTION")
        fake = MagicMock()
        fake.registered = True
        with patch(
            "app.ui.action_center.batch_action_center.ProductionWizardDialog", return_value=fake
        ) as ctor:
            dialog.run_action(action)
        ctor.assert_called_once_with(service, [10, 20], dialog, observation="")
        self.assertTrue(dialog.changed)
        self.assertTrue(dialog.result())

    def test_register_production_cancel_closes_the_center_without_changes(self):
        service = FakeBatchService("PRODUCAO", common_statuses=["FINALIZADO"])
        dialog = BatchProposalActionCenter(service, [10, 20], "PRODUCAO")
        action = next(a for a in dialog.actions if a.id == "REGISTER_PRODUCTION")
        fake = MagicMock()
        fake.registered = False  # usuario cancela o assistente
        with patch("app.ui.action_center.batch_action_center.ProductionWizardDialog", return_value=fake):
            dialog.run_action(action)
        self.assertFalse(dialog.changed)
        self.assertFalse(dialog.result())

    def test_define_item_flow_opens_flow_review_dialog_with_exact_ids(self):
        service = FakeBatchService("PRODUCAO", common_statuses=["INICIADO"])
        dialog = BatchProposalActionCenter(service, [10, 20], "PRODUCAO")
        action = next(a for a in dialog.actions if a.id == "DEFINE_ITEM_FLOW")
        fake = MagicMock()
        fake.exec.return_value = 1
        fake.changed = False
        with patch("app.ui.action_center.batch_action_center.FlowReviewDialog", return_value=fake) as ctor:
            dialog.run_action(action)
        ctor.assert_called_once_with(service, [10, 20], dialog, origin="ProducaoLote")
        self.assertTrue(dialog.changed)

    def test_manage_load_new_opens_galvanization_load_dialog_without_load_id(self):
        service = FakeBatchService("GALVANIZACAO")
        dialog = BatchProposalActionCenter(service, [10, 20], "GALVANIZACAO")
        action = next(a for a in dialog.actions if a.id == "MANAGE_LOAD_NEW")
        fake = MagicMock()
        fake.exec.return_value = 1
        with patch(
            "app.ui.action_center.batch_action_center.GalvanizationLoadDialog", return_value=fake
        ) as ctor:
            dialog.run_action(action)
        ctor.assert_called_once_with(service, [10, 20], parent=dialog)
        self.assertTrue(dialog.changed)
        self.assertTrue(dialog.result())

    def test_manage_load_existing_with_no_open_loads_shows_message_and_stays_open(self):
        service = FakeBatchService("GALVANIZACAO", open_loads=[])
        dialog = BatchProposalActionCenter(service, [10, 20], "GALVANIZACAO")
        action = next(a for a in dialog.actions if a.id == "MANAGE_LOAD_EXISTING")
        with patch("app.ui.action_center.handlers.galvanization.QMessageBox.information") as info, patch(
            "app.ui.action_center.batch_action_center.GalvanizationLoadDialog"
        ) as ctor:
            dialog.run_action(action)
        info.assert_called_once()
        ctor.assert_not_called()
        self.assertFalse(dialog.changed)
        self.assertFalse(dialog.result())

    def test_manage_load_existing_with_one_open_load_still_shows_chooser(self):
        # O usuario pediu explicitamente para "mostrar a lista das cargas
        # disponiveis" - mesmo com um unico resultado, a escolha e explicita.
        service = FakeBatchService("GALVANIZACAO", open_loads=[{"id": 14, "status": "AGUARDANDO_LIBERACAO"}])
        dialog = BatchProposalActionCenter(service, [10, 20], "GALVANIZACAO")
        action = next(a for a in dialog.actions if a.id == "MANAGE_LOAD_EXISTING")
        fake_chooser = MagicMock()
        fake_chooser.exec.return_value = 1
        fake_chooser.selected_load_id = 14
        with patch(
            "app.ui.action_center.handlers.galvanization._SelectGalvanizationLoadDialog", return_value=fake_chooser
        ) as chooser_ctor, patch(
            "app.ui.action_center.batch_action_center.GalvanizationLoadDialog"
        ) as load_ctor, patch(
            "app.ui.action_center.batch_action_center.QMessageBox.information"
        ) as info:
            dialog.run_action(action)
        chooser_ctor.assert_called_once()
        self.assertIn(("add_items_to_galvanization_load", 14, None, [10, 20]), service.calls)
        load_ctor.assert_not_called()
        info.assert_called_once()
        self.assertTrue(dialog.changed)
        self.assertTrue(dialog.result())

    def test_manage_load_existing_cancelling_the_chooser_does_not_open_anything(self):
        service = FakeBatchService("GALVANIZACAO")
        dialog = BatchProposalActionCenter(service, [10, 20], "GALVANIZACAO")
        action = next(a for a in dialog.actions if a.id == "MANAGE_LOAD_EXISTING")
        fake_chooser = MagicMock()
        fake_chooser.exec.return_value = 0
        with patch(
            "app.ui.action_center.handlers.galvanization._SelectGalvanizationLoadDialog", return_value=fake_chooser
        ), patch("app.ui.action_center.batch_action_center.GalvanizationLoadDialog") as load_ctor:
            dialog.run_action(action)
        load_ctor.assert_not_called()
        self.assertFalse(dialog.changed)

    def test_register_return_with_single_shared_load_opens_return_dialog_scoped_to_proposals(self):
        service = FakeBatchService(
            "GALVANIZACAO",
            process_loads={
                10: [{"id": 30, "status": "LIBERADA_PARA_ENVIO"}],
                20: [{"id": 30, "status": "LIBERADA_PARA_ENVIO"}],
            },
        )
        dialog = BatchProposalActionCenter(service, [10, 20], "GALVANIZACAO")
        action = next(a for a in dialog.actions if a.id == "REGISTER_RETURN")
        fake = MagicMock()
        fake.exec.return_value = 1
        with patch(
            "app.ui.action_center.batch_action_center.GalvanizationReturnDialog", return_value=fake
        ) as ctor:
            dialog.run_action(action)
        ctor.assert_called_once_with(service, 30, dialog, proposal_ids=[10, 20], extra_load_ids=[])
        self.assertTrue(dialog.changed)
        self.assertTrue(dialog.result())

    # O caso "nenhuma carga ativa" nao aparece mais aqui: o card
    # REGISTER_RETURN so existe quando ha carga retornavel elegivel
    # (ActionListPerAreaTests acima) - a mensagem defensiva de
    # resolve_return_load_ids() continua coberta diretamente em
    # tests/test_galvanization_action_center.py::ResolveReturnLoadIdsTests,
    # que e o unico ponto onde o card pode ficar visivel sem carga (aba
    # Itens da Galvanizacao, onde a elegibilidade nao e pre-filtrada).

    def test_register_return_with_proposals_on_different_loads_opens_a_single_combined_dialog(self):
        # CP10 e CP20 estao em cargas diferentes de proposito - uma unica
        # tela cobre as duas (extra_load_ids), em vez de uma tela por carga.
        service = FakeBatchService(
            "GALVANIZACAO",
            process_loads={
                10: [{"id": 30, "status": "LIBERADA_PARA_ENVIO"}],
                20: [{"id": 31, "status": "RETORNO_PARCIAL"}],
            },
        )
        dialog = BatchProposalActionCenter(service, [10, 20], "GALVANIZACAO")
        action = next(a for a in dialog.actions if a.id == "REGISTER_RETURN")
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = 1
        with patch(
            "app.ui.action_center.batch_action_center.GalvanizationReturnDialog", return_value=fake_dialog
        ) as ctor:
            dialog.run_action(action)
        ctor.assert_called_once_with(service, 30, dialog, proposal_ids=[10, 20], extra_load_ids=[31])
        self.assertTrue(dialog.changed)
        self.assertTrue(dialog.result())

    def test_register_return_cancelling_does_not_close_the_center(self):
        service = FakeBatchService(
            "GALVANIZACAO",
            process_loads={
                10: [{"id": 30, "status": "LIBERADA_PARA_ENVIO"}],
                20: [{"id": 31, "status": "RETORNO_PARCIAL"}],
            },
        )
        dialog = BatchProposalActionCenter(service, [10, 20], "GALVANIZACAO")
        action = next(a for a in dialog.actions if a.id == "REGISTER_RETURN")
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = 0
        with patch("app.ui.action_center.batch_action_center.GalvanizationReturnDialog", return_value=fake_dialog):
            dialog.run_action(action)
        self.assertFalse(dialog.changed)
        self.assertFalse(dialog.result())

    def test_manage_load_existing_only_offers_loads_awaiting_release(self):
        service = FakeBatchService(
            "GALVANIZACAO",
            open_loads=[
                {"id": 14, "status": "AGUARDANDO_LIBERACAO"},
                {"id": 15, "status": "LIBERADA_PARA_ENVIO"},
            ],
        )
        dialog = BatchProposalActionCenter(service, [10], "GALVANIZACAO")
        action = next(a for a in dialog.actions if a.id == "MANAGE_LOAD_EXISTING")
        with patch(
            "app.ui.action_center.handlers.galvanization._SelectGalvanizationLoadDialog"
        ) as chooser_ctor:
            chooser_ctor.return_value.exec.return_value = 0
            dialog.run_action(action)
        passed_loads = chooser_ctor.call_args.args[0]
        self.assertEqual([row["id"] for row in passed_loads], [14])

    def test_register_delivery_opens_the_wizard_with_exact_ids_and_closes_changed(self):
        service = FakeBatchService("EXPEDICAO", common_statuses=["ENTREGUE"], pending_delivery_items={10: [{"id": 1}], 20: []})
        dialog = BatchProposalActionCenter(service, [10, 20], "EXPEDICAO")
        action = next(a for a in dialog.actions if a.id == "REGISTER_DELIVERY")
        fake = MagicMock()
        fake.registered = True
        with patch("app.ui.action_center.batch_action_center.DeliveryWizardDialog", return_value=fake) as ctor:
            dialog.run_action(action)
        ctor.assert_called_once_with(service, [10, 20], dialog, observation="")
        self.assertTrue(dialog.changed)
        self.assertTrue(dialog.result())

    def test_register_delivery_cancel_closes_the_center_without_writing(self):
        service = FakeBatchService("EXPEDICAO", common_statuses=["ENTREGUE"], pending_delivery_items={10: [{"id": 1}]})
        dialog = BatchProposalActionCenter(service, [10], "EXPEDICAO")
        action = next(a for a in dialog.actions if a.id == "REGISTER_DELIVERY")
        fake = MagicMock()
        fake.registered = False
        with patch("app.ui.action_center.batch_action_center.DeliveryWizardDialog", return_value=fake):
            dialog.run_action(action)
        self.assertFalse(any(call[0] == "update_status" for call in service.calls))
        self.assertFalse(dialog.changed)
        self.assertFalse(dialog.result())


class RoutingErrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_unknown_action_id_shows_friendly_message_and_does_not_crash(self):
        from app.ui.action_center.descriptor import ActionDescriptor

        service = FakeBatchService("CONTROLE GERAL")
        dialog = BatchProposalActionCenter(service, [10], "CONTROLE GERAL")
        unknown = ActionDescriptor(
            id="NOT_REGISTERED", label="X", description="", icon=None,
            category=ActionCategory.NORMAL, area="CONTROLE GERAL",
        )
        with patch("app.ui.action_center.batch_action_center.QMessageBox.warning") as warning:
            dialog.run_action(unknown)
        warning.assert_called_once()


def _row(process_id, status, deducted=False):
    return {"id": process_id, "proposta": f"CP{process_id}", "status_almoxarifado": status, "baixa_estoque": deducted}


class WarehouseStockDeductionBatchTests(unittest.TestCase):
    """Baixa no estoque em lote (Fase 15): cards pelo estado de cada linha selecionada; uma chamada por proposta;
    a falha de uma nao derruba as outras."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _service():
        service = FakeBatchService("ALMOXARIFADO", common_statuses=[])
        service.deduction_calls = []

        def set_deduction(process_id, version, deducted):
            service.deduction_calls.append((process_id, version, deducted))
            if process_id in service.failing:
                raise RuntimeError("Esta proposta foi alterada por outro usuario.")
            return {}

        service.failing = set()
        service.warehouse_set_stock_deduction = set_deduction
        return service

    @staticmethod
    def _dialog(service, ids, rows):
        labels = {process_id: f"CP{process_id}" for process_id in ids}
        return BatchProposalActionCenter(service, ids, "ALMOXARIFADO", proposal_labels=labels, proposal_rows=rows)

    @staticmethod
    def _cards(dialog):
        return [(a.label, a.status, a.category) for a in dialog.actions if a.id == "STOCK_DEDUCTION"]

    def test_confirm_card_is_primary_and_revert_is_normal(self):
        rows = {10: _row(10, "SEPARADO"), 20: _row(20, "ALMOXARIFADO_ENTREGUE", deducted=True)}
        dialog = self._dialog(self._service(), [10, 20], rows)
        self.assertEqual(
            self._cards(dialog),
            [
                ("Confirmar baixa no estoque", "CONFIRM", ActionCategory.PRIMARY),
                ("Desfazer baixa", "REVERT", ActionCategory.NORMAL),
            ],
        )
        self.assertEqual(len([a for a in dialog.actions if a.category == ActionCategory.PRIMARY]), 1)

    def test_coverage_is_in_the_description_when_only_part_of_the_selection_qualifies(self):
        rows = {10: _row(10, "SEPARADO"), 20: _row(20, "EM_SEPARACAO"), 30: _row(30, "SEM_PARAFUSOS")}
        dialog = self._dialog(self._service(), [10, 20, 30], rows)
        card = next(a for a in dialog.actions if a.id == "STOCK_DEDUCTION")
        self.assertIn("1 de 3", card.description)
        self.assertEqual(card.raw["eligible_ids"], [10])

    def test_no_card_for_em_separacao_sem_parafusos_or_unknown_rows(self):
        rows = {10: _row(10, "EM_SEPARACAO"), 20: _row(20, "SEM_PARAFUSOS", deducted=False)}
        dialog = self._dialog(self._service(), [10, 20, 30], rows)  # 30 sem linha conhecida
        self.assertEqual(self._cards(dialog), [])
        self.assertEqual(dialog.actions, [])

    def test_other_areas_never_get_the_card(self):
        service = FakeBatchService("EXPEDICAO", common_statuses=["SEPARADO"])
        dialog = BatchProposalActionCenter(service, [10], "EXPEDICAO", proposal_rows={10: _row(10, "SEPARADO")})
        self.assertEqual(self._cards(dialog), [])

    def test_confirm_makes_one_call_per_eligible_proposal_only(self):
        service = self._service()
        rows = {10: _row(10, "SEPARADO"), 20: _row(20, "ALMOXARIFADO_ENTREGUE_PARCIAL"), 30: _row(30, "EM_SEPARACAO")}
        dialog = self._dialog(service, [10, 20, 30], rows)
        action = next(a for a in dialog.actions if a.status == "CONFIRM")
        with patch("app.ui.action_center.batch_action_center.QMessageBox.question", return_value=QMessageBox.Yes) as question, patch(
            "app.ui.action_center.batch_action_center.start_worker", side_effect=_run_synchronously
        ), patch("app.ui.action_center.batch_action_center.QMessageBox.warning") as warning, patch(
            "app.ui.action_center.batch_action_center.QMessageBox.information"
        ) as info:
            dialog.run_action(action)
        self.assertEqual(service.deduction_calls, [(10, None, True), (20, None, True)])
        warning.assert_not_called()
        info.assert_called_once()
        self.assertIn("2 proposta(s) alterada(s): CP10, CP20", info.call_args.args[2])
        self.assertIn("CP10", question.call_args.args[2])
        self.assertNotIn("CP30", question.call_args.args[2])
        self.assertTrue(dialog.changed)
        self.assertTrue(dialog.result())

    def test_revert_sends_deducted_false(self):
        service = self._service()
        dialog = self._dialog(service, [10], {10: _row(10, "SEPARADO", deducted=True)})
        action = next(a for a in dialog.actions if a.status == "REVERT")
        with patch("app.ui.action_center.batch_action_center.QMessageBox.question", return_value=QMessageBox.Yes), patch(
            "app.ui.action_center.batch_action_center.start_worker", side_effect=_run_synchronously
        ), patch("app.ui.action_center.batch_action_center.QMessageBox.information"):
            dialog.run_action(action)
        self.assertEqual(service.deduction_calls, [(10, None, False)])

    def test_failure_in_the_middle_does_not_stop_the_others_and_is_reported_by_number(self):
        service = self._service()
        service.failing = {20}
        rows = {n: _row(n, "SEPARADO") for n in (10, 20, 30)}
        dialog = self._dialog(service, [10, 20, 30], rows)
        action = next(a for a in dialog.actions if a.status == "CONFIRM")
        with patch("app.ui.action_center.batch_action_center.QMessageBox.question", return_value=QMessageBox.Yes), patch(
            "app.ui.action_center.batch_action_center.start_worker", side_effect=_run_synchronously
        ), patch("app.ui.action_center.batch_action_center.QMessageBox.warning") as warning:
            dialog.run_action(action)
        self.assertEqual([call[0] for call in service.deduction_calls], [10, 20, 30])  # a 30 foi tentada apos a falha da 20
        warning.assert_called_once()
        text = warning.call_args.args[2]
        self.assertIn("2 proposta(s) alterada(s): CP10, CP30", text)
        self.assertIn("CP20: Esta proposta foi alterada por outro usuario.", text)
        self.assertTrue(dialog.changed)

    def _run(self, service, ids):
        dialog = self._dialog(service, ids, {n: _row(n, "SEPARADO") for n in ids})
        action = next(a for a in dialog.actions if a.status == "CONFIRM")
        with patch("app.ui.action_center.batch_action_center.QMessageBox.question", return_value=QMessageBox.Yes), patch(
            "app.ui.action_center.batch_action_center.start_worker", side_effect=_run_synchronously
        ), patch("app.ui.action_center.batch_action_center.QMessageBox.warning") as warning, patch(
            "app.ui.action_center.batch_action_center.QMessageBox.information"
        ) as info:
            dialog.run_action(action)
        return dialog, warning, info

    def test_when_every_proposal_fails_nothing_changed_and_the_dialog_stays_open_with_the_failures(self):
        service = self._service()
        service.failing = {10, 20}
        dialog, warning, info = self._run(service, [10, 20])
        warning.assert_called_once()
        info.assert_not_called()
        text = warning.call_args.args[2]
        self.assertIn("0 proposta(s) alterada(s)", text)
        self.assertIn("CP10: Esta proposta foi alterada por outro usuario.", text)
        self.assertIn("CP20: Esta proposta foi alterada por outro usuario.", text)
        self.assertFalse(dialog.changed)
        self.assertEqual(dialog.result(), 0)  # nao fechou como sucesso

    def test_lists_cut_at_12_end_with_e_mais_n(self):
        ids = list(range(100, 115))  # 15
        # sucesso: so a lista dos numeros que deram certo
        dialog, warning, info = self._run(self._service(), ids)
        text = info.call_args.args[2]
        self.assertIn("15 proposta(s) alterada(s): CP100,", text)
        self.assertIn("CP111, ... e mais 3", text)
        self.assertNotIn("CP112", text)
        self.assertTrue(dialog.changed)
        # falhas e sucessos cortados no mesmo relatorio
        service = self._service()
        service.failing = set(range(100, 113))  # 13 falhas, 2 sucessos
        _, warning, _ = self._run(service, ids)
        text = warning.call_args.args[2]
        self.assertIn("2 proposta(s) alterada(s): CP113, CP114.", text)
        self.assertIn("... e mais 1", text)
        self.assertNotIn("CP112:", text)

    def test_declining_the_confirmation_does_not_call_the_service(self):
        service = self._service()
        dialog = self._dialog(service, [10], {10: _row(10, "SEPARADO")})
        action = next(a for a in dialog.actions if a.status == "CONFIRM")
        with patch("app.ui.action_center.batch_action_center.QMessageBox.question", return_value=QMessageBox.No):
            dialog.run_action(action)
        self.assertEqual(service.deduction_calls, [])
        self.assertFalse(dialog.changed)


if __name__ == "__main__":
    unittest.main()
