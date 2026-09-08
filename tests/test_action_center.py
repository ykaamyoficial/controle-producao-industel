from __future__ import annotations

import dataclasses
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from PySide6.QtWidgets import QMessageBox

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.action_center.context import ProposalActionContext
from app.ui.action_center.descriptor import ActionCategory, ActionDescriptor
from app.ui.action_center.provider import BackendActionProvider
from app.ui.status_dialog import StatusDialog
from tests.test_status_dialog import FakeService, _production_actions


def _control_general_actions(status: str, completed: bool = False) -> list[dict]:
    """Mirrors BackendAdapter.process_actions()'s CONTROLE GERAL branch
    (app/services/backend_adapter.py:1290-1304)."""
    actions: list[dict] = []
    if status == "AGUARDANDO_LIBERACAO":
        actions.append({
            "id": "STATUS", "label": "Liberar para producao", "icon": "production",
            "status": "LIBERADO_PRODUCAO", "area": "CONTROLE GERAL",
        })
    if not completed:
        actions.append({
            "id": "STATUS", "label": "Cancelar proposta", "icon": "delete",
            "status": "CANCELADA", "area": "CONTROLE GERAL",
        })
    return actions


class FakeControlGeneralService:
    """Fake service exercising only the CONTROLE GERAL surface StatusDialog/
    ProposalActionCenter actually calls - mirrors FakeService's shape from
    test_status_dialog.py but tracks update_status calls so tests can assert
    exactly which service method ran with which arguments."""

    def __init__(self, status: str = "AGUARDANDO_LIBERACAO", palette_name: str = "claro", admin: bool = False, completed: bool = False):
        self.status = status
        self.completed = completed
        self.palette = OFFICIAL_COLOR_PALETTES[palette_name]
        self._admin = admin
        self.calls: list[tuple] = []
        self.cancelled = False

    def get_process_dict(self, process_id):
        return {"id": process_id, "proposta": "CP05266", "cliente": "MNS ENGENHARIA"}

    def get_process_area_dict(self, process_id, area):
        return self.get_process_dict(process_id)

    def current_location(self, process):
        return ("CONTROLE GERAL", "Controle geral", self.status)

    def status_for_area(self, process, area):
        return self.status

    def area_status_label(self, area, status):
        return status.replace("_", " ").title()

    def process_actions(self, process_id, area):
        if area != "CONTROLE GERAL" or self.status == "CANCELADA":
            return []
        return _control_general_actions(self.status, self.completed)

    def can_admin(self):
        return self._admin

    def update_status(self, process_id, area, status, observation="", item_ids=None, produced_weight=None):
        self.calls.append(("update_status", process_id, area, status, observation))
        if status == "LIBERADO_PRODUCAO":
            self.status = "LIBERADO_PRODUCAO"
        elif status == "CANCELADA":
            self.status = "CANCELADA"
            self.cancelled = True
        return {}


_WAREHOUSE_OPTIONS = {
    "": ["EM_SEPARACAO", "SEM_PARAFUSOS"],
    "NAO_DEFINIDO": ["EM_SEPARACAO", "SEM_PARAFUSOS"],
    "AGUARDANDO_CONFIRMACAO": ["EM_SEPARACAO", "SEM_PARAFUSOS"],
    "EM_SEPARACAO": ["SEPARADO"],
    "SEPARADO": ["ALMOXARIFADO_ENTREGUE", "ALMOXARIFADO_ENTREGUE_PARCIAL"],
    "ALMOXARIFADO_ENTREGUE_PARCIAL": ["ALMOXARIFADO_ENTREGUE"],
    "ALMOXARIFADO_ENTREGUE": [],
    "SEM_PARAFUSOS": [],
}
# Mirrors BackendAdapter.process_actions()'s ALMOXARIFADO branch label choice
# (app/services/backend_adapter.py:1370-1384): AGUARDANDO_CONFIRMACAO uses the
# follow-up labels even though it shares the same options as NAO_DEFINIDO/''.
_WAREHOUSE_LABELS_INITIAL = {"EM_SEPARACAO": "Precisa de Almoxarifado", "SEM_PARAFUSOS": "Nao precisa de Almoxarifado"}
_WAREHOUSE_LABELS_FOLLOWUP = {
    "EM_SEPARACAO": "Confirmar que possui almoxarifado",
    "SEM_PARAFUSOS": "Confirmar sem almoxarifado",
    "SEPARADO": "Confirmar separacao concluida",
    "ALMOXARIFADO_ENTREGUE": "Confirmar entrega do almoxarifado",
    "ALMOXARIFADO_ENTREGUE_PARCIAL": "Registrar entrega parcial",
}
_WAREHOUSE_ICONS = {"EM_SEPARACAO": "stock", "SEM_PARAFUSOS": "clear"}


class FakeWarehouseService:
    """Mirrors the real ALMOXARIFADO state machine
    (next_status_options()/process_actions() in backend_adapter.py) closely
    enough to exercise WarehouseStatusHandler without a real API/DB."""

    def __init__(self, status: str = "", palette_name: str = "claro", admin: bool = False, can_edit: bool = True):
        self.status = status
        self.palette = OFFICIAL_COLOR_PALETTES[palette_name]
        self._admin = admin
        self._can_edit = can_edit
        self.calls: list[tuple] = []

    def get_process_dict(self, process_id):
        return {"id": process_id, "proposta": "CP05266", "cliente": "MNS ENGENHARIA"}

    def get_process_area_dict(self, process_id, area):
        return self.get_process_dict(process_id)

    def current_location(self, process):
        return ("ALMOXARIFADO", "Almoxarifado", self.status)

    def status_for_area(self, process, area):
        return self.status

    def area_status_label(self, area, status):
        return status.replace("_", " ").title()

    def can_admin(self):
        return self._admin

    def process_actions(self, process_id, area):
        if area != "ALMOXARIFADO" or not self._can_edit:
            return []
        options = _WAREHOUSE_OPTIONS.get(self.status, [])
        labels = _WAREHOUSE_LABELS_INITIAL if self.status in ("", "NAO_DEFINIDO") else _WAREHOUSE_LABELS_FOLLOWUP
        actions = []
        for target in options:
            label = labels.get(target, target.replace("_", " ").title())
            icon = _WAREHOUSE_ICONS.get(target, "status")
            actions.append({"id": "STATUS", "label": label, "icon": icon, "status": target, "area": "ALMOXARIFADO"})
        return actions

    def update_status(self, process_id, area, status, observation="", item_ids=None, produced_weight=None):
        self.calls.append(("update_status", process_id, area, status, observation))
        self.status = status
        return {}


class FakeExpeditionService:
    """Mirrors BackendAdapter.process_actions()'s EXPEDICAO branch
    (app/services/backend_adapter.py:1305-1324) and update_status()'s
    EXPEDICAO branch (:1436-1455) closely enough to exercise
    ExpeditionStatusHandler/RegisterDeliveryHandler without a real API/DB."""

    def __init__(
        self, status: str = "EM_SEPARACAO", palette_name: str = "claro", admin: bool = False,
        can_edit: bool = True, pending_delivery_items: list[dict] | None = None,
    ):
        self.status = status
        self.palette = OFFICIAL_COLOR_PALETTES[palette_name]
        self._admin = admin
        self._can_edit = can_edit
        self.calls: list[tuple] = []
        self._pending_delivery_items = (
            pending_delivery_items if pending_delivery_items is not None else [{"id": 101}, {"id": 102}]
        )

    def get_process_dict(self, process_id):
        return {"id": process_id, "proposta": "CP05266", "cliente": "MNS ENGENHARIA"}

    def get_process_area_dict(self, process_id, area):
        return self.get_process_dict(process_id)

    def current_location(self, process):
        return ("EXPEDICAO", "Expedicao", self.status)

    def status_for_area(self, process, area):
        return self.status

    def area_status_label(self, area, status):
        return status.replace("_", " ").title()

    def can_admin(self):
        return self._admin

    def process_actions(self, process_id, area):
        if area != "EXPEDICAO" or not self._can_edit:
            return []
        actions: list[dict] = []

        def add(action_id, label, status_value=""):
            actions.append({"id": action_id, "label": label, "icon": "status", "status": status_value, "area": "EXPEDICAO"})

        if self.status in ("EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL"):
            add("STATUS", "Iniciar separacao", "SEPARACAO_INICIADA")
        if self.status in ("EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARACAO_INICIADA", "ENTREGUE_PARCIAL"):
            add("STATUS", "Registrar separacao", "SEPARADO")
        if self.status in ("SEPARADO", "ENTREGUE_PARCIAL"):
            add("REGISTER_DELIVERY", "Registrar retirada do cliente")
        return actions

    def proposal_items(self, process_id, pending_production=False, pending_delivery=False):
        if pending_delivery:
            return list(self._pending_delivery_items)
        return []

    def update_status(self, process_id, area, status, observation="", item_ids=None, produced_weight=None):
        self.calls.append(("update_status", process_id, area, status, observation, item_ids))
        self.status = status
        return {}


def _synchronous_start_worker(owner, operation, on_success, on_error):
    """Runs the "background" operation inline so tests can assert on its
    outcome without spinning a real QThread + Qt event loop."""
    try:
        result = operation()
    except Exception as exc:
        on_error(exc)
    else:
        on_success(result)
    return None


class ProviderContractTests(unittest.TestCase):
    """Todo ActionDescriptor devolvido pelo provider de Producao precisa ser
    identificavel, apresentavel e roteavel - e nenhuma acao pode ficar sem
    handler registrado."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_every_descriptor_has_required_fields_and_a_registered_handler(self):
        registry = StatusDialog._build_registry()
        for status in ("NAO_INICIADO", "LIBERADO_PRODUCAO", "INICIADO", "PARADO", "FINALIZADO_PARCIAL", "FINALIZADO"):
            service = FakeService(status)
            provider = BackendActionProvider(service)
            context = ProposalActionContext(
                proposal_id=1, area="PRODUCAO", current_status=status, proposal_number="CP05385", client_name="MNS",
            )
            descriptors = provider.get_actions(context)
            self.assertEqual(
                [descriptor.raw for descriptor in descriptors],
                _production_actions(status),
            )
            for descriptor in descriptors:
                with self.subTest(status=status, action_id=descriptor.id):
                    self.assertTrue(descriptor.id)
                    self.assertTrue(descriptor.label)
                    self.assertIsInstance(descriptor.category, ActionCategory)
                    self.assertIsNotNone(
                        registry.resolve(descriptor.id, descriptor.area), f"sem handler para {descriptor.id!r}"
                    )

    def test_at_most_one_primary_action_per_context(self):
        for status in ("NAO_INICIADO", "INICIADO", "PARADO", "FINALIZADO"):
            with self.subTest(status=status):
                service = FakeService(status)
                provider = BackendActionProvider(service)
                context = ProposalActionContext(
                    proposal_id=1, area="PRODUCAO", current_status=status, proposal_number="CP1", client_name="X",
                )
                primaries = [d for d in provider.get_actions(context) if d.category == ActionCategory.PRIMARY]
                self.assertLessEqual(len(primaries), 1)


class ContextIdentityTests(unittest.TestCase):
    def test_context_carries_the_real_proposal_id_not_a_row_index(self):
        context = ProposalActionContext(
            proposal_id=42, area="PRODUCAO", current_status="INICIADO", proposal_number="CP05385", client_name="MNS",
        )
        self.assertEqual(context.proposal_id, 42)

    def test_context_is_immutable(self):
        context = ProposalActionContext(
            proposal_id=42, area="PRODUCAO", current_status="INICIADO", proposal_number="CP05385", client_name="MNS",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            context.proposal_id = 99


class ReloadContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_reload_context_reflects_new_status_without_duplicating_widgets(self):
        service = FakeService("NAO_INICIADO")
        dialog = StatusDialog(service, 1, "PRODUCAO")
        first_action_count = len(dialog._action_buttons)
        self.assertGreater(first_action_count, 0)
        badges_before = dialog._badges_layout.count()

        service.status = "INICIADO"
        dialog.reload_context()

        self.assertEqual(dialog.context.current_status, "INICIADO")
        self.assertEqual(len(dialog._action_buttons), len(dialog.context.available_actions))
        # a acao Registrar producao so existe quando INICIADO - prova que a grade foi recalculada
        self.assertIn("REGISTER_PRODUCTION", [a.id for a in dialog.context.available_actions])
        # nenhum widget orfao ficou no container (senao o count cresceria a cada reload)
        self.assertEqual(dialog._actions_layout.count(), 1)
        self.assertEqual(dialog._badges_layout.count(), badges_before)


class RoutingErrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_unknown_action_id_shows_friendly_message_and_does_not_crash(self):
        service = FakeService("INICIADO")
        dialog = StatusDialog(service, 1, "PRODUCAO")
        unknown = ActionDescriptor(
            id="NOT_REGISTERED", label="X", description="", icon=None,
            category=ActionCategory.NORMAL, area="PRODUCAO",
        )
        with patch("app.ui.action_center.proposal_action_center.QMessageBox.warning") as warning:
            dialog.run_action(unknown)
        warning.assert_called_once()

    def test_handler_exception_is_caught_and_shown_not_raised(self):
        service = FakeService("INICIADO")
        dialog = StatusDialog(service, 1, "PRODUCAO")

        class BoomHandler:
            def execute(self, context, action, dlg):
                raise RuntimeError("boom")

        dialog.registry.register("REGISTER_PRODUCTION", BoomHandler())
        action = next(a for a in dialog.context.available_actions if a.id == "REGISTER_PRODUCTION")
        with patch("app.ui.action_center.proposal_action_center.QMessageBox.warning") as warning:
            dialog.run_action(action)  # nao deve lancar
        warning.assert_called_once()


class ProductionHandlerRoutingTests(unittest.TestCase):
    """Cada handler de producao deve abrir o dialog especializado certo -
    exatamente como o StatusDialog monolitico fazia."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_register_production_opens_registration_dialog_when_flow_is_defined(self):
        service = FakeService("INICIADO")
        service.item_flow_summary = lambda process_id: {"undefined_count": 0}
        dialog = StatusDialog(service, 1, "PRODUCAO")
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = 0
        action = next(a for a in dialog.context.available_actions if a.id == "REGISTER_PRODUCTION")
        with patch(
            "app.ui.action_center.handlers.production.ProductionRegistrationDialog", return_value=fake_dialog
        ) as ctor:
            dialog.run_action(action)
        ctor.assert_called_once()

    def test_define_item_flow_opens_flow_review_dialog(self):
        service = FakeService("NAO_INICIADO")
        dialog = StatusDialog(service, 1, "PRODUCAO")
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = 0
        action = next(a for a in dialog.context.available_actions if a.id == "DEFINE_ITEM_FLOW")
        with patch("app.ui.action_center.handlers.production.FlowReviewDialog", return_value=fake_dialog) as ctor:
            dialog.run_action(action)
        ctor.assert_called_once()

    def test_edit_item_weights_opens_item_weight_dialog(self):
        service = FakeService("NAO_INICIADO")
        dialog = StatusDialog(service, 1, "PRODUCAO")
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = 0
        action = next(a for a in dialog.context.available_actions if a.id == "EDIT_ITEM_WEIGHTS")
        with patch("app.ui.action_center.handlers.production.ItemWeightDialog", return_value=fake_dialog) as ctor:
            dialog.run_action(action)
        ctor.assert_called_once()

    def test_pause_opens_production_pause_dialog(self):
        service = FakeService("INICIADO")
        dialog = StatusDialog(service, 1, "PRODUCAO")
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = 0  # usuario cancela a pausa
        action = next(a for a in dialog.context.available_actions if a.id == "STATUS" and a.status == "PARADO")
        with patch(
            "app.ui.action_center.handlers.production.ProductionPauseDialog", return_value=fake_dialog
        ) as ctor:
            dialog.run_action(action)
        ctor.assert_called_once()

    def test_cancelling_a_specialized_dialog_does_not_close_the_action_center(self):
        service = FakeService("NAO_INICIADO")
        dialog = StatusDialog(service, 1, "PRODUCAO")
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = 0
        action = next(a for a in dialog.context.available_actions if a.id == "DEFINE_ITEM_FLOW")
        with patch("app.ui.action_center.handlers.production.FlowReviewDialog", return_value=fake_dialog):
            dialog.run_action(action)
        self.assertFalse(dialog.result())  # QDialog.Rejected/0 (nao aceito) - ainda aberto


class ControlGeneralActionCenterTests(unittest.TestCase):
    """Fase 3: Controle Geral (Liberar para Producao / Cancelar proposta)
    passa a usar a mesma Central de Acoes da Producao. Cobre a lista de
    testes obrigatorios da secao 22 do prompt tecnico da Fase 3."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    # 1-2: abre para o proposal_id correto, cabecalho mostra proposta/cliente/area/status
    def test_opens_for_correct_proposal_id_with_full_header(self):
        service = FakeControlGeneralService("AGUARDANDO_LIBERACAO")
        dialog = StatusDialog(service, 42, "CONTROLE GERAL")
        self.assertEqual(dialog.context.proposal_id, 42)
        self.assertEqual(dialog.context.area, "CONTROLE GERAL")
        self.assertIn("CP05266", dialog._title_label.text())
        self.assertIn("MNS ENGENHARIA", dialog._title_label.text())

    # 3-4: AGUARDANDO_LIBERACAO mostra as duas acoes
    def test_awaiting_release_shows_both_actions(self):
        service = FakeControlGeneralService("AGUARDANDO_LIBERACAO")
        dialog = StatusDialog(service, 1, "CONTROLE GERAL")
        ids_and_status = {(a.id, a.status) for a in dialog.context.available_actions}
        self.assertIn(("STATUS", "LIBERADO_PRODUCAO"), ids_and_status)
        self.assertIn(("STATUS", "CANCELADA"), ids_and_status)

    # 5-6: Liberar e PRIMARY, Cancelar e DESTRUCTIVE
    def test_release_is_primary_and_cancel_is_destructive(self):
        service = FakeControlGeneralService("AGUARDANDO_LIBERACAO")
        dialog = StatusDialog(service, 1, "CONTROLE GERAL")
        by_status = {a.status: a.category for a in dialog.context.available_actions}
        self.assertEqual(by_status["LIBERADO_PRODUCAO"], ActionCategory.PRIMARY)
        self.assertEqual(by_status["CANCELADA"], ActionCategory.DESTRUCTIVE)

    # 7: proposta sem avancos nao mostra Liberar (so aparece em AGUARDANDO_LIBERACAO)
    def test_non_awaiting_status_does_not_show_release_action(self):
        service = FakeControlGeneralService("LIBERADO_PRODUCAO")
        dialog = StatusDialog(service, 1, "CONTROLE GERAL")
        self.assertNotIn("LIBERADO_PRODUCAO", [a.status for a in dialog.context.available_actions])
        self.assertIn("CANCELADA", [a.status for a in dialog.context.available_actions])

    # 12-13: abrir/fechar e digitar observacao nao grava nada
    def test_opening_closing_and_typing_observation_does_not_touch_the_service(self):
        service = FakeControlGeneralService("AGUARDANDO_LIBERACAO")
        dialog = StatusDialog(service, 1, "CONTROLE GERAL")
        dialog.observation.setPlainText("rascunho que ninguem deve salvar")
        dialog.reject()
        self.assertEqual(service.calls, [])

    # 14: Liberar chama somente o service oficial (update_status), com a observacao atual
    def test_release_calls_only_the_official_service(self):
        service = FakeControlGeneralService("AGUARDANDO_LIBERACAO")
        dialog = StatusDialog(service, 1, "CONTROLE GERAL")
        dialog.observation.setPlainText("liberando conforme combinado")
        action = next(a for a in dialog.context.available_actions if a.status == "LIBERADO_PRODUCAO")
        with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
            dialog.run_action(action)
        self.assertEqual(service.calls, [("update_status", 1, "CONTROLE GERAL", "LIBERADO_PRODUCAO", "liberando conforme combinado")])

    # 15: Cancelar exige confirmacao antes de chamar o service
    def test_cancel_requires_confirmation_before_calling_the_service(self):
        service = FakeControlGeneralService("AGUARDANDO_LIBERACAO")
        dialog = StatusDialog(service, 1, "CONTROLE GERAL")
        dialog.observation.setPlainText("motivo valido")
        action = next(a for a in dialog.context.available_actions if a.status == "CANCELADA")
        with patch("app.ui.action_center.handlers.control_general.QMessageBox.question", return_value=QMessageBox.No) as question:
            with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
                dialog.run_action(action)
        question.assert_called_once()
        self.assertEqual(service.calls, [])

    # 16: Cancelar preserva motivo/observacao obrigatorios
    def test_cancel_without_observation_is_blocked_before_any_confirmation(self):
        service = FakeControlGeneralService("AGUARDANDO_LIBERACAO")
        dialog = StatusDialog(service, 1, "CONTROLE GERAL")
        action = next(a for a in dialog.context.available_actions if a.status == "CANCELADA")
        with patch("app.ui.action_center.handlers.control_general.QMessageBox.warning") as warning:
            with patch("app.ui.action_center.handlers.control_general.QMessageBox.question") as question:
                dialog.run_action(action)
        warning.assert_called_once()
        question.assert_not_called()
        self.assertEqual(service.calls, [])

    def test_cancel_confirmed_with_observation_calls_the_official_service(self):
        service = FakeControlGeneralService("AGUARDANDO_LIBERACAO")
        dialog = StatusDialog(service, 1, "CONTROLE GERAL")
        dialog.observation.setPlainText("cliente desistiu do pedido")
        action = next(a for a in dialog.context.available_actions if a.status == "CANCELADA")
        with patch("app.ui.action_center.handlers.control_general.QMessageBox.question", return_value=QMessageBox.Yes):
            with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
                dialog.run_action(action)
        self.assertEqual(service.calls, [("update_status", 1, "CONTROLE GERAL", "CANCELADA", "cliente desistiu do pedido")])
        self.assertEqual(dialog.result(), 1)  # accept() - fecha como antes

    # 17-18: sucesso em liberar executa reload_context() sem duplicar cards e sem fechar
    def test_release_success_reloads_context_in_place_without_duplicating_cards(self):
        service = FakeControlGeneralService("AGUARDANDO_LIBERACAO")
        dialog = StatusDialog(service, 1, "CONTROLE GERAL")
        action = next(a for a in dialog.context.available_actions if a.status == "LIBERADO_PRODUCAO")
        with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
            dialog.run_action(action)
        # o fake service ja aplicou a transicao - o contexto recarregado reflete o novo status
        self.assertEqual(dialog.context.current_status, "LIBERADO_PRODUCAO")
        self.assertNotIn("LIBERADO_PRODUCAO", [a.status for a in dialog.context.available_actions])
        self.assertEqual(len(dialog._action_buttons), len(dialog.context.available_actions))
        self.assertEqual(dialog._actions_layout.count(), 1)
        self.assertNotEqual(dialog.result(), 1)  # ainda nao foi fechado

    # o resultado do exec() so vira "aceito" quando o usuario finalmente fecha, apos uma mudanca real
    def test_closing_after_a_reload_only_action_still_reports_changed_to_the_caller(self):
        service = FakeControlGeneralService("AGUARDANDO_LIBERACAO")
        dialog = StatusDialog(service, 1, "CONTROLE GERAL")
        action = next(a for a in dialog.context.available_actions if a.status == "LIBERADO_PRODUCAO")
        with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
            dialog.run_action(action)
        dialog.reject()  # clique no botao "Fechar"
        self.assertEqual(dialog.result(), 1)  # QDialog.Accepted - ProcessPage.exec() enxerga a mudanca

    # 19: conflito de status e tratado sem sobrescrita - erro mostra aviso e recarrega o contexto
    def test_service_error_shows_warning_and_reloads_context_without_crashing(self):
        service = FakeControlGeneralService("AGUARDANDO_LIBERACAO")

        def _boom(*args, **kwargs):
            raise RuntimeError("versao desatualizada - outra pessoa alterou a proposta")

        service.update_status = _boom
        dialog = StatusDialog(service, 1, "CONTROLE GERAL")
        dialog.observation.setPlainText("liberando")
        action = next(a for a in dialog.context.available_actions if a.status == "LIBERADO_PRODUCAO")
        with patch("app.ui.action_center.proposal_action_center.QMessageBox.warning") as warning:
            with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
                dialog.run_action(action)
        warning.assert_called_once()
        # a Central continua utilizavel (contexto recarregado, sem crash) e ainda aberta
        self.assertEqual(dialog.context.proposal_id, 1)
        self.assertNotEqual(dialog.result(), 1)

    # 20: usuario sem permissao nao consegue executar (o dominio ja nao devolve a acao)
    def test_user_without_permission_sees_no_actionable_cards(self):
        service = FakeControlGeneralService("AGUARDANDO_LIBERACAO")
        service.process_actions = lambda process_id, area: []
        dialog = StatusDialog(service, 1, "CONTROLE GERAL")
        self.assertEqual(dialog.context.available_actions, ())
        self.assertEqual(dialog._action_buttons, [])

    # 21: correcao administrativa continua restrita a admin
    def test_manual_correction_button_respects_can_admin(self):
        from PySide6.QtWidgets import QPushButton

        hidden = StatusDialog(FakeControlGeneralService("AGUARDANDO_LIBERACAO", admin=False), 1, "CONTROLE GERAL")
        visible = StatusDialog(FakeControlGeneralService("AGUARDANDO_LIBERACAO", admin=True), 1, "CONTROLE GERAL")
        self.assertNotIn("Correcao administrativa", [b.text() for b in hidden.findChildren(QPushButton)])
        self.assertIn("Correcao administrativa", [b.text() for b in visible.findChildren(QPushButton)])

    # 22-23: temas claro e escuro
    def test_light_and_dark_theme_render_without_crash(self):
        light = StatusDialog(FakeControlGeneralService("AGUARDANDO_LIBERACAO", palette_name="claro"), 1, "CONTROLE GERAL")
        dark = StatusDialog(FakeControlGeneralService("AGUARDANDO_LIBERACAO", palette_name="escuro"), 1, "CONTROLE GERAL")
        self.assertNotEqual(light.service.palette["accent"], dark.service.palette["accent"])
        self.assertTrue(light._action_buttons)
        self.assertTrue(dark._action_buttons)

    # 24: Action ID/area desconhecidos nao causam crash
    def test_unregistered_area_for_a_known_action_id_does_not_crash(self):
        service = FakeControlGeneralService("AGUARDANDO_LIBERACAO")
        dialog = StatusDialog(service, 1, "CONTROLE GERAL")
        bogus = ActionDescriptor(
            id="STATUS", label="X", description="", icon=None,
            category=ActionCategory.NORMAL, area="GALVANIZACAO",  # STATUS nunca foi registrado para essa area
        )
        with patch("app.ui.action_center.proposal_action_center.QMessageBox.warning") as warning:
            dialog.run_action(bogus)
        warning.assert_called_once()
        self.assertEqual(service.calls, [])


class WarehouseActionCenterTests(unittest.TestCase):
    """Fase 4: Almoxarifado (definir necessidade / confirmar separacao /
    confirmar entrega / entrega parcial) passa a usar a mesma Central de
    Acoes. Cobre a lista de testes obrigatorios da secao 29 do prompt
    tecnico da Fase 4."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    # 1-2: abre para o proposal_id correto, cabecalho mostra proposta/cliente/area/status
    def test_opens_for_correct_proposal_id_with_full_header(self):
        service = FakeWarehouseService("")
        dialog = StatusDialog(service, 7, "ALMOXARIFADO")
        self.assertEqual(dialog.context.proposal_id, 7)
        self.assertEqual(dialog.context.area, "ALMOXARIFADO")
        self.assertIn("CP05266", dialog._title_label.text())
        self.assertIn("MNS ENGENHARIA", dialog._title_label.text())

    # 3: acoes exibidas correspondem ao retorno oficial do dominio
    def test_actions_match_the_official_domain_output(self):
        service = FakeWarehouseService("SEPARADO")
        dialog = StatusDialog(service, 1, "ALMOXARIFADO")
        self.assertEqual(
            sorted(a.status for a in dialog.context.available_actions),
            sorted(_WAREHOUSE_OPTIONS["SEPARADO"]),
        )

    # 4: acoes indisponiveis nao aparecem (ex.: EM_SEPARACAO ja concluido nao reaparece)
    def test_unavailable_actions_do_not_appear(self):
        service = FakeWarehouseService("SEPARADO")
        dialog = StatusDialog(service, 1, "ALMOXARIFADO")
        statuses = [a.status for a in dialog.context.available_actions]
        self.assertNotIn("EM_SEPARACAO", statuses)
        self.assertNotIn("SEM_PARAFUSOS", statuses)

    # 5: definir necessidade de Almoxarifado continua usando o service oficial
    def test_define_requirement_calls_only_the_official_service(self):
        service = FakeWarehouseService("")
        dialog = StatusDialog(service, 1, "ALMOXARIFADO")
        action = next(a for a in dialog.context.available_actions if a.status == "EM_SEPARACAO")
        with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
            dialog.run_action(action)
        self.assertEqual(service.calls, [("update_status", 1, "ALMOXARIFADO", "EM_SEPARACAO", "")])

    # 6: confirmacao de separacao continua funcionando
    def test_confirm_separation_calls_the_official_service(self):
        service = FakeWarehouseService("EM_SEPARACAO")
        dialog = StatusDialog(service, 1, "ALMOXARIFADO")
        action = next(a for a in dialog.context.available_actions if a.status == "SEPARADO")
        with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
            dialog.run_action(action)
        self.assertEqual(service.calls, [("update_status", 1, "ALMOXARIFADO", "SEPARADO", "")])

    # 7: confirmacao de entrega continua funcionando
    def test_confirm_delivery_calls_the_official_service(self):
        service = FakeWarehouseService("SEPARADO")
        dialog = StatusDialog(service, 1, "ALMOXARIFADO")
        action = next(a for a in dialog.context.available_actions if a.status == "ALMOXARIFADO_ENTREGUE")
        with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
            dialog.run_action(action)
        self.assertEqual(service.calls, [("update_status", 1, "ALMOXARIFADO", "ALMOXARIFADO_ENTREGUE", "")])

    # 8: entrega parcial continua respeitando a regra atual (status de destino correto)
    def test_partial_delivery_calls_the_official_service_with_the_partial_status(self):
        service = FakeWarehouseService("SEPARADO")
        dialog = StatusDialog(service, 1, "ALMOXARIFADO")
        action = next(a for a in dialog.context.available_actions if a.status == "ALMOXARIFADO_ENTREGUE_PARCIAL")
        with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
            dialog.run_action(action)
        self.assertEqual(service.calls, [("update_status", 1, "ALMOXARIFADO", "ALMOXARIFADO_ENTREGUE_PARCIAL", "")])
        # a regra de que "entrega parcial" continua exigindo o passo intermediario e do backend:
        # apos ela, next_status_options so libera ALMOXARIFADO_ENTREGUE (nunca volta a SEPARADO)
        self.assertEqual(_WAREHOUSE_OPTIONS["ALMOXARIFADO_ENTREGUE_PARCIAL"], ["ALMOXARIFADO_ENTREGUE"])

    # 9: acao concluida chama reload_context() e atualiza cards/status sem fechar
    def test_successful_action_reloads_context_in_place_without_duplicating_cards(self):
        service = FakeWarehouseService("EM_SEPARACAO")
        dialog = StatusDialog(service, 1, "ALMOXARIFADO")
        action = next(a for a in dialog.context.available_actions if a.status == "SEPARADO")
        with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
            dialog.run_action(action)
        self.assertEqual(dialog.context.current_status, "SEPARADO")
        self.assertEqual(
            sorted(a.status for a in dialog.context.available_actions),
            sorted(_WAREHOUSE_OPTIONS["SEPARADO"]),
        )
        self.assertEqual(len(dialog._action_buttons), len(dialog.context.available_actions))
        self.assertEqual(dialog._actions_layout.count(), 1)
        self.assertNotEqual(dialog.result(), 1)  # ainda aberta - o usuario nao precisa reabrir

    # closing after such a reload-only session still reports "changed" to the caller (ProcessPage)
    def test_closing_after_a_reload_only_action_still_reports_changed_to_the_caller(self):
        service = FakeWarehouseService("EM_SEPARACAO")
        dialog = StatusDialog(service, 1, "ALMOXARIFADO")
        action = next(a for a in dialog.context.available_actions if a.status == "SEPARADO")
        with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
            dialog.run_action(action)
        dialog.reject()  # clique no botao "Fechar"
        self.assertEqual(dialog.result(), 1)  # QDialog.Accepted

    # 10: uma acao bloqueada/cancelada (ex.: clique duplo enquanto outra acao roda) nao altera dados
    def test_action_blocked_while_another_is_running_does_not_touch_the_service(self):
        service = FakeWarehouseService("")
        dialog = StatusDialog(service, 1, "ALMOXARIFADO")
        dialog._running_action = True
        action = next(a for a in dialog.context.available_actions if a.status == "EM_SEPARACAO")
        dialog.run_action(action)
        self.assertEqual(service.calls, [])

    # 11: abrir/fechar a Central nao executa INSERT/UPDATE/DELETE
    def test_opening_and_closing_does_not_touch_the_service(self):
        service = FakeWarehouseService("")
        dialog = StatusDialog(service, 1, "ALMOXARIFADO")
        dialog.reject()
        self.assertEqual(service.calls, [])

    # 12: digitar observacao nao grava nada automaticamente
    def test_typing_observation_does_not_touch_the_service(self):
        service = FakeWarehouseService("")
        dialog = StatusDialog(service, 1, "ALMOXARIFADO")
        dialog.observation.setPlainText("rascunho")
        dialog.reject()
        self.assertEqual(service.calls, [])

    # 13: usuario sem permissao nao executa acao proibida (o dominio ja nao devolve a acao)
    def test_user_without_permission_sees_no_actionable_cards(self):
        service = FakeWarehouseService("", can_edit=False)
        dialog = StatusDialog(service, 1, "ALMOXARIFADO")
        self.assertEqual(dialog.context.available_actions, ())
        self.assertEqual(dialog._action_buttons, [])

    # 14: correcao administrativa continua restrita a administrador
    def test_manual_correction_button_respects_can_admin(self):
        from PySide6.QtWidgets import QPushButton

        hidden = StatusDialog(FakeWarehouseService("", admin=False), 1, "ALMOXARIFADO")
        visible = StatusDialog(FakeWarehouseService("", admin=True), 1, "ALMOXARIFADO")
        self.assertNotIn("Correcao administrativa", [b.text() for b in hidden.findChildren(QPushButton)])
        self.assertIn("Correcao administrativa", [b.text() for b in visible.findChildren(QPushButton)])

    # 15: handler inexistente gera erro controlado (nao crasha)
    def test_unregistered_area_for_a_known_action_id_does_not_crash(self):
        service = FakeWarehouseService("")
        dialog = StatusDialog(service, 1, "ALMOXARIFADO")
        bogus = ActionDescriptor(
            id="STATUS", label="X", description="", icon=None,
            category=ActionCategory.NORMAL, area="GALVANIZACAO",  # STATUS nunca foi registrado para essa area
        )
        with patch("app.ui.action_center.proposal_action_center.QMessageBox.warning") as warning:
            dialog.run_action(bogus)
        warning.assert_called_once()
        self.assertEqual(service.calls, [])

    # 16-17: temas claro e escuro renderizam sem erro
    def test_light_and_dark_theme_render_without_crash(self):
        light = StatusDialog(FakeWarehouseService("SEPARADO", palette_name="claro"), 1, "ALMOXARIFADO")
        dark = StatusDialog(FakeWarehouseService("SEPARADO", palette_name="escuro"), 1, "ALMOXARIFADO")
        self.assertNotEqual(light.service.palette["accent"], dark.service.palette["accent"])
        self.assertTrue(light._action_buttons)
        self.assertTrue(dark._action_buttons)


class ExpeditionActionCenterTests(unittest.TestCase):
    """Fase 5: Expedicao (iniciar separacao / registrar separacao / registrar
    retirada) passa a usar a mesma Central de Acoes. Cobre a lista de testes
    obrigatorios da secao 26 do prompt tecnico da Fase 5."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    # 1-2: abre para o proposal_id correto, cabecalho mostra proposta/cliente/area/status
    def test_opens_for_correct_proposal_id_with_full_header(self):
        service = FakeExpeditionService("EM_SEPARACAO")
        dialog = StatusDialog(service, 9, "EXPEDICAO")
        self.assertEqual(dialog.context.proposal_id, 9)
        self.assertEqual(dialog.context.area, "EXPEDICAO")
        self.assertIn("CP05266", dialog._title_label.text())
        self.assertIn("MNS ENGENHARIA", dialog._title_label.text())

    # 3: somente acoes oficiais validas aparecem
    def test_actions_match_the_official_domain_output(self):
        service = FakeExpeditionService("SEPARADO")
        dialog = StatusDialog(service, 1, "EXPEDICAO")
        ids_and_status = {(a.id, a.status) for a in dialog.context.available_actions}
        self.assertEqual(ids_and_status, {("REGISTER_DELIVERY", "")})

    def test_unavailable_actions_do_not_appear_at_separacao_iniciada(self):
        service = FakeExpeditionService("SEPARACAO_INICIADA")
        dialog = StatusDialog(service, 1, "EXPEDICAO")
        ids_and_status = {(a.id, a.status) for a in dialog.context.available_actions}
        self.assertEqual(ids_and_status, {("STATUS", "SEPARADO")})  # sem "Iniciar separacao" de novo

    # 4: ordem/categoria dos cards e estavel - Iniciar separacao e a acao PRIMARY quando presente
    def test_start_separation_is_primary_when_available(self):
        service = FakeExpeditionService("EM_SEPARACAO")
        dialog = StatusDialog(service, 1, "EXPEDICAO")
        by_status = {a.status: a.category for a in dialog.context.available_actions}
        self.assertEqual(by_status["SEPARACAO_INICIADA"], ActionCategory.PRIMARY)
        self.assertEqual(by_status["SEPARADO"], ActionCategory.NORMAL)

    def test_register_separation_becomes_primary_once_started(self):
        service = FakeExpeditionService("SEPARACAO_INICIADA")
        dialog = StatusDialog(service, 1, "EXPEDICAO")
        by_status = {a.status: a.category for a in dialog.context.available_actions}
        self.assertEqual(by_status["SEPARADO"], ActionCategory.PRIMARY)

    def test_register_delivery_outranks_register_separation_when_both_available(self):
        # ENTREGUE_PARCIAL mostra STATUS/SEPARADO e REGISTER_DELIVERY juntos - retirada e a primaria.
        service = FakeExpeditionService("ENTREGUE_PARCIAL")
        dialog = StatusDialog(service, 1, "EXPEDICAO")
        by_id = {(a.id, a.status): a.category for a in dialog.context.available_actions}
        self.assertEqual(by_id[("REGISTER_DELIVERY", "")], ActionCategory.PRIMARY)
        self.assertEqual(by_id[("STATUS", "SEPARADO")], ActionCategory.NORMAL)

    # a mesma (id, status) "STATUS"/"SEPARADO" do Almoxarifado nao pode virar PRIMARY por engano
    def test_status_separado_primary_scoping_does_not_leak_into_warehouse(self):
        service = FakeWarehouseService("EM_SEPARACAO")
        dialog = StatusDialog(service, 1, "ALMOXARIFADO")
        action = next(a for a in dialog.context.available_actions if a.status == "SEPARADO")
        self.assertEqual(action.category, ActionCategory.NORMAL)

    # 5: iniciar separacao usa handler/service oficial, sem dialogo de itens (nao existe hoje)
    def test_start_separation_calls_only_the_official_service_without_item_dialog(self):
        service = FakeExpeditionService("EM_SEPARACAO")
        dialog = StatusDialog(service, 1, "EXPEDICAO")
        action = next(a for a in dialog.context.available_actions if a.status == "SEPARACAO_INICIADA")
        with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
            dialog.run_action(action)
        self.assertEqual(service.calls, [("update_status", 1, "EXPEDICAO", "SEPARACAO_INICIADA", "", None)])

    # 6: nenhuma acao e executada so por abrir/fechar a Central (nao ha confirmacao para iniciar/registrar separacao hoje)
    def test_opening_and_closing_does_not_touch_the_service(self):
        service = FakeExpeditionService("EM_SEPARACAO")
        dialog = StatusDialog(service, 1, "EXPEDICAO")
        dialog.reject()
        self.assertEqual(service.calls, [])

    # 7-9: registrar separacao chama o mesmo fluxo simples (sem selecao de itens) e preserva o item_ids=None atual
    def test_register_separation_calls_the_official_service_without_assuming_all_items(self):
        service = FakeExpeditionService("SEPARACAO_INICIADA")
        dialog = StatusDialog(service, 1, "EXPEDICAO")
        action = next(a for a in dialog.context.available_actions if a.status == "SEPARADO")
        with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
            dialog.run_action(action)
        call = service.calls[0]
        self.assertEqual(call[:4], ("update_status", 1, "EXPEDICAO", "SEPARADO"))
        self.assertIsNone(call[5])  # item_ids: preserva o comportamento atual (nunca inventa selecao de itens)

    # 10: registrar retirada abre o dialogo especializado correto
    def test_register_delivery_opens_the_item_selection_dialog(self):
        service = FakeExpeditionService("SEPARADO")
        dialog = StatusDialog(service, 1, "EXPEDICAO")
        fake_selector = MagicMock()
        fake_selector.exec.return_value = 0  # usuario cancela
        action = next(a for a in dialog.context.available_actions if a.id == "REGISTER_DELIVERY")
        with patch(
            "app.ui.action_center.handlers.expedition.ItemSelectionDialog", return_value=fake_selector
        ) as ctor:
            dialog.run_action(action)
        ctor.assert_called_once()
        self.assertEqual(service.calls, [])

    # 11-13: retirada trabalha apenas com os itens elegiveis retornados pelo dominio; parcial/total conforme selecao real
    def test_partial_delivery_selection_results_in_partial_status(self):
        service = FakeExpeditionService("SEPARADO", pending_delivery_items=[{"id": 101}, {"id": 102}])
        dialog = StatusDialog(service, 1, "EXPEDICAO")
        fake_selector = MagicMock()
        fake_selector.exec.return_value = 1
        fake_selector.selected_ids = [101]  # so um dos dois itens elegiveis
        action = next(a for a in dialog.context.available_actions if a.id == "REGISTER_DELIVERY")
        with patch("app.ui.action_center.handlers.expedition.ItemSelectionDialog", return_value=fake_selector):
            with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
                dialog.run_action(action)
        self.assertEqual(service.calls, [("update_status", 1, "EXPEDICAO", "ENTREGUE_PARCIAL", "", [101])])

    def test_full_delivery_selection_results_in_total_status(self):
        service = FakeExpeditionService("SEPARADO", pending_delivery_items=[{"id": 101}, {"id": 102}])
        dialog = StatusDialog(service, 1, "EXPEDICAO")
        fake_selector = MagicMock()
        fake_selector.exec.return_value = 1
        fake_selector.selected_ids = [101, 102]  # todos os itens elegiveis
        action = next(a for a in dialog.context.available_actions if a.id == "REGISTER_DELIVERY")
        with patch("app.ui.action_center.handlers.expedition.ItemSelectionDialog", return_value=fake_selector):
            with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
                dialog.run_action(action)
        self.assertEqual(service.calls, [("update_status", 1, "EXPEDICAO", "ENTREGUE", "", [101, 102])])

    def test_no_pending_items_delivers_directly_without_opening_the_dialog(self):
        # itens ja entregues nao aparecem mais como pendentes - dominio decide, nao a UI
        service = FakeExpeditionService("SEPARADO", pending_delivery_items=[])
        dialog = StatusDialog(service, 1, "EXPEDICAO")
        action = next(a for a in dialog.context.available_actions if a.id == "REGISTER_DELIVERY")
        with patch("app.ui.action_center.handlers.expedition.ItemSelectionDialog") as ctor:
            with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
                dialog.run_action(action)
        ctor.assert_not_called()
        self.assertEqual(service.calls, [("update_status", 1, "EXPEDICAO", "ENTREGUE", "", None)])

    # registrar retirada continua fechando a Central em sucesso (mesmo comportamento do RegisterProductionHandler)
    def test_register_delivery_success_closes_the_action_center(self):
        service = FakeExpeditionService("SEPARADO", pending_delivery_items=[{"id": 101}])
        dialog = StatusDialog(service, 1, "EXPEDICAO")
        fake_selector = MagicMock()
        fake_selector.exec.return_value = 1
        fake_selector.selected_ids = [101]
        action = next(a for a in dialog.context.available_actions if a.id == "REGISTER_DELIVERY")
        with patch("app.ui.action_center.handlers.expedition.ItemSelectionDialog", return_value=fake_selector):
            with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
                dialog.run_action(action)
        self.assertEqual(dialog.result(), 1)  # QDialog.Accepted

    # 18-19: sucesso em iniciar/registrar separacao chama reload_context() e nao duplica widgets
    def test_start_separation_success_reloads_context_in_place_without_duplicating_cards(self):
        service = FakeExpeditionService("EM_SEPARACAO")
        dialog = StatusDialog(service, 1, "EXPEDICAO")
        action = next(a for a in dialog.context.available_actions if a.status == "SEPARACAO_INICIADA")
        with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
            dialog.run_action(action)
        self.assertEqual(dialog.context.current_status, "SEPARACAO_INICIADA")
        self.assertEqual({(a.id, a.status) for a in dialog.context.available_actions}, {("STATUS", "SEPARADO")})
        self.assertEqual(len(dialog._action_buttons), len(dialog.context.available_actions))
        self.assertEqual(dialog._actions_layout.count(), 1)
        self.assertNotEqual(dialog.result(), 1)  # ainda aberta

    def test_closing_after_a_reload_only_action_still_reports_changed_to_the_caller(self):
        service = FakeExpeditionService("EM_SEPARACAO")
        dialog = StatusDialog(service, 1, "EXPEDICAO")
        action = next(a for a in dialog.context.available_actions if a.status == "SEPARACAO_INICIADA")
        with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
            dialog.run_action(action)
        dialog.reject()  # clique no botao "Fechar"
        self.assertEqual(dialog.result(), 1)

    # 20: usuario sem permissao nao executa acao proibida (o dominio ja nao devolve a acao)
    def test_user_without_permission_sees_no_actionable_cards(self):
        service = FakeExpeditionService("EM_SEPARACAO", can_edit=False)
        dialog = StatusDialog(service, 1, "EXPEDICAO")
        self.assertEqual(dialog.context.available_actions, ())
        self.assertEqual(dialog._action_buttons, [])

    # 21: correcao administrativa continua restrita a administrador
    def test_manual_correction_button_respects_can_admin(self):
        from PySide6.QtWidgets import QPushButton

        hidden = StatusDialog(FakeExpeditionService("EM_SEPARACAO", admin=False), 1, "EXPEDICAO")
        visible = StatusDialog(FakeExpeditionService("EM_SEPARACAO", admin=True), 1, "EXPEDICAO")
        self.assertNotIn("Correcao administrativa", [b.text() for b in hidden.findChildren(QPushButton)])
        self.assertIn("Correcao administrativa", [b.text() for b in visible.findChildren(QPushButton)])

    # 22-23: digitar observacao/abrir/fechar nao grava nada
    def test_typing_observation_and_closing_does_not_touch_the_service(self):
        service = FakeExpeditionService("EM_SEPARACAO")
        dialog = StatusDialog(service, 1, "EXPEDICAO")
        dialog.observation.setPlainText("rascunho")
        dialog.reject()
        self.assertEqual(service.calls, [])

    # 27: acao sem handler gera erro controlado
    def test_unregistered_area_for_a_known_action_id_does_not_crash(self):
        service = FakeExpeditionService("EM_SEPARACAO")
        dialog = StatusDialog(service, 1, "EXPEDICAO")
        bogus = ActionDescriptor(
            id="STATUS", label="X", description="", icon=None,
            category=ActionCategory.NORMAL, area="FISCAL",  # STATUS nunca foi registrado para essa area
        )
        with patch("app.ui.action_center.proposal_action_center.QMessageBox.warning") as warning:
            dialog.run_action(bogus)
        warning.assert_called_once()
        self.assertEqual(service.calls, [])

    # 28-29: falha de API/concorrencia nao deixa a UI inconsistente - mostra aviso e recarrega o contexto
    def test_service_error_shows_warning_and_reloads_context_without_crashing(self):
        service = FakeExpeditionService("EM_SEPARACAO")

        def _boom(*args, **kwargs):
            raise RuntimeError("versao desatualizada - outra pessoa alterou a proposta")

        service.update_status = _boom
        dialog = StatusDialog(service, 1, "EXPEDICAO")
        action = next(a for a in dialog.context.available_actions if a.status == "SEPARACAO_INICIADA")
        with patch("app.ui.action_center.proposal_action_center.QMessageBox.warning") as warning:
            with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
                dialog.run_action(action)
        warning.assert_called_once()
        self.assertEqual(dialog.context.proposal_id, 1)
        self.assertNotEqual(dialog.result(), 1)

    # 25-26: temas claro e escuro
    def test_light_and_dark_theme_render_without_crash(self):
        light = StatusDialog(FakeExpeditionService("SEPARADO", palette_name="claro"), 1, "EXPEDICAO")
        dark = StatusDialog(FakeExpeditionService("SEPARADO", palette_name="escuro"), 1, "EXPEDICAO")
        self.assertNotEqual(light.service.palette["accent"], dark.service.palette["accent"])
        self.assertTrue(light._action_buttons)
        self.assertTrue(dark._action_buttons)


if __name__ == "__main__":
    unittest.main()
