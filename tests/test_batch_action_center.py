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
    ):
        self.area = area
        self.palette = OFFICIAL_COLOR_PALETTES[palette_name]
        self._common_statuses = common_statuses if common_statuses is not None else ["LIBERADO_PRODUCAO", "CANCELADA"]
        self.calls: list[tuple] = []
        self.validation_result: dict | None = None
        self._pending_delivery_items = pending_delivery_items or {}
        self._open_loads = open_loads if open_loads is not None else [{"id": 14, "status": "AGUARDANDO_LIBERACAO"}]
        self._process_loads = process_loads or {}
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

    def action_label(self, area, status):
        return {"LIBERADO_PRODUCAO": "Liberar para producao", "CANCELADA": "Cancelar proposta"}.get(
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
        # Producao sempre ganha o card de definir fluxo, independente do status comum
        self.assertIn("DEFINE_ITEM_FLOW", ids)

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
        fake.exec.return_value = 1  # QDialog.Accepted
        with patch(
            "app.ui.action_center.batch_action_center.ProductionRegistrationDialog", return_value=fake
        ) as ctor:
            dialog.run_action(action)
        ctor.assert_called_once_with(service, [10, 20], dialog, observation="")
        self.assertTrue(dialog.changed)
        self.assertTrue(dialog.result())

    def test_register_production_cancel_does_not_close_or_write(self):
        service = FakeBatchService("PRODUCAO", common_statuses=["FINALIZADO"])
        dialog = BatchProposalActionCenter(service, [10, 20], "PRODUCAO")
        action = next(a for a in dialog.actions if a.id == "REGISTER_PRODUCTION")
        fake = MagicMock()
        fake.exec.return_value = 0  # usuario cancela a mesa de registro
        with patch("app.ui.action_center.batch_action_center.ProductionRegistrationDialog", return_value=fake):
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

    def test_register_delivery_loops_item_selection_per_proposal(self):
        service = FakeBatchService(
            "EXPEDICAO", common_statuses=["ENTREGUE"],
            pending_delivery_items={10: [{"id": 1}, {"id": 2}], 20: []},
        )
        dialog = BatchProposalActionCenter(service, [10, 20], "EXPEDICAO")
        action = next(a for a in dialog.actions if a.id == "REGISTER_DELIVERY")
        fake_selector = MagicMock()
        fake_selector.exec.return_value = 1
        fake_selector.selected_ids = [1, 2]
        with patch(
            "app.ui.action_center.batch_action_center.ItemSelectionDialog", return_value=fake_selector
        ) as ctor, patch(
            "app.ui.action_center.batch_action_center.QMessageBox.question", return_value=QMessageBox.Yes
        ), patch("app.ui.action_center.batch_action_center.start_worker", side_effect=_run_synchronously):
            dialog.run_action(action)
        ctor.assert_called_once()  # so a proposta 10 tem itens pendentes
        update_calls = {call[1]: call[3] for call in service.calls if call[0] == "update_status"}
        self.assertEqual(update_calls, {10: "ENTREGUE", 20: "ENTREGUE"})

    def test_register_delivery_cancel_mid_loop_aborts_without_writing(self):
        service = FakeBatchService(
            "EXPEDICAO", common_statuses=["ENTREGUE"],
            pending_delivery_items={10: [{"id": 1}]},
        )
        dialog = BatchProposalActionCenter(service, [10], "EXPEDICAO")
        action = next(a for a in dialog.actions if a.id == "REGISTER_DELIVERY")
        fake_selector = MagicMock()
        fake_selector.exec.return_value = 0  # usuario cancela a selecao de itens
        with patch("app.ui.action_center.batch_action_center.ItemSelectionDialog", return_value=fake_selector):
            dialog.run_action(action)
        self.assertFalse(any(call[0] == "update_status" for call in service.calls))
        self.assertFalse(dialog.changed)


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


if __name__ == "__main__":
    unittest.main()
