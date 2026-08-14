from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.action_center.context import ProposalActionContext
from app.ui.action_center.descriptor import ActionCategory
from app.ui.action_center.provider import GalvanizationActionProvider
from app.ui.status_dialog import StatusDialog


def _galvanization_actions(status: str, active_loads: list[dict]) -> list[dict]:
    """Mirrors BackendAdapter.process_actions()'s GALVANIZACAO branch
    (app/services/backend_adapter.py:1352-1369) exactly."""
    actions: list[dict] = []

    def add(action_id, label, icon, status_value=""):
        actions.append({"id": action_id, "label": label, "icon": icon, "status": status_value, "area": "GALVANIZACAO"})

    if status in ("AGUARDANDO_ENVIO", "DISPONIVEL_PARCIAL"):
        add("MANAGE_LOAD", "Adicionar a uma carga", "load", "EM_CARGA")
    if status in ("ENVIADO_GALVANIZACAO", "RETORNOU_PARCIAL"):
        eligible = [row for row in active_loads if (row.get("status") or "") in ("LIBERADA_PARA_ENVIO", "RETORNO_PARCIAL")]
        if eligible:
            add("REGISTER_GALVANIZATION_RETURN", "Registrar retorno da galvanizacao", "load", "RETORNOU_GALVANIZACAO")
    return actions


class FakeGalvanizationService:
    """Mirrors the GALVANIZACAO surface of BackendAdapter (process_actions +
    process_loads) closely enough to exercise the Fase 6 handlers/provider
    without a real API/DB."""

    def __init__(
        self, status: str = "AGUARDANDO_ENVIO", loads: list[dict] | None = None,
        palette_name: str = "claro", admin: bool = False, can_edit: bool = True,
    ):
        self.status = status
        self.loads = loads if loads is not None else []
        self.palette = OFFICIAL_COLOR_PALETTES[palette_name]
        self._admin = admin
        self._can_edit = can_edit
        self.calls: list[tuple] = []

    def get_process_dict(self, process_id):
        return {"id": process_id, "proposta": "CP05266", "cliente": "MNS ENGENHARIA"}

    def get_process_area_dict(self, process_id, area):
        return self.get_process_dict(process_id)

    def current_location(self, process):
        return ("GALVANIZACAO", "Galvanizacao", self.status)

    def status_for_area(self, process, area):
        return self.status

    def area_status_label(self, area, status):
        return status.replace("_", " ").title()

    def can_admin(self):
        return self._admin

    def process_actions(self, process_id, area):
        if area != "GALVANIZACAO" or not self._can_edit:
            return []
        return _galvanization_actions(self.status, self.loads)

    def process_loads(self, process_id):
        self.calls.append(("process_loads", process_id))
        return list(self.loads)

    def galvanization_loads(self):
        self.calls.append(("galvanization_loads",))
        return list(self.loads)

    def update_status(self, process_id, area, status, observation="", item_ids=None, produced_weight=None):
        self.calls.append(("update_status", process_id, area, status, observation))
        return {}


class GalvanizationActionCenterOpeningTests(unittest.TestCase):
    """Secao 63: a Central abre em Galvanizacao com o proposal_id/area/status
    corretos e nenhuma acao de carga (edicao/liberacao/historico) vaza para
    dentro dela."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_opens_for_correct_proposal_id_area_and_status(self):
        service = FakeGalvanizationService("AGUARDANDO_ENVIO")
        dialog = StatusDialog(service, 77, "GALVANIZACAO")
        self.assertEqual(dialog.context.proposal_id, 77)
        self.assertEqual(dialog.context.area, "GALVANIZACAO")
        self.assertEqual(dialog.context.current_status, "AGUARDANDO_ENVIO")
        self.assertIn("CP05266", dialog._title_label.text())

    def test_load_only_actions_never_appear_in_the_proposal_action_center(self):
        service = FakeGalvanizationService("ENVIADO_GALVANIZACAO", loads=[{"id": 14, "status": "LIBERADA_PARA_ENVIO"}])
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        ids = {action.id for action in dialog.context.available_actions}
        for forbidden in ("EDIT_LOAD", "RELEASE_LOAD", "LOAD_HISTORY", "VIEW_RETURNS"):
            self.assertNotIn(forbidden, ids)

    def test_empty_state_message_when_no_action_available(self):
        service = FakeGalvanizationService("RETORNOU_GALVANIZACAO", loads=[])
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        self.assertEqual(dialog.context.available_actions, ())

    def test_opening_and_closing_does_not_write_to_the_service(self):
        # process_loads (read, used to resolve carga navigation - secao 43) is
        # expected; only a write (update_status) would violate secoes 42/69.
        service = FakeGalvanizationService("AGUARDANDO_ENVIO")
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        dialog.observation.setPlainText("rascunho")
        dialog.reject()
        self.assertFalse(any(call[0] == "update_status" for call in service.calls))


class ManageLoadHandlerTests(unittest.TestCase):
    """Secoes 8-13 (Fase 6) + divisao em dois cards (Fase 8): MANAGE_LOAD
    chega do backend como uma unica acao, mas GalvanizationActionProvider ja
    a divide em MANAGE_LOAD_EXISTING/MANAGE_LOAD_NEW, cada uma com handler
    dedicado (nao LegacyActionHandler); cancelar nao altera dados e sucesso
    pede refresh."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_manage_load_is_split_into_two_cards_with_dedicated_handlers(self):
        from app.ui.action_center.handlers.galvanization import (
            ManageGalvanizationLoadExistingHandler, ManageGalvanizationLoadNewHandler,
        )
        from app.ui.action_center.handlers.legacy import LegacyActionHandler

        service = FakeGalvanizationService("AGUARDANDO_ENVIO")
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        ids = [a.id for a in dialog.context.available_actions]
        self.assertIn("MANAGE_LOAD_EXISTING", ids)
        self.assertIn("MANAGE_LOAD_NEW", ids)
        self.assertNotIn("MANAGE_LOAD", ids)

        registry = StatusDialog._build_registry()
        existing_handler = registry.resolve("MANAGE_LOAD_EXISTING", "GALVANIZACAO")
        new_handler = registry.resolve("MANAGE_LOAD_NEW", "GALVANIZACAO")
        self.assertIsInstance(existing_handler, ManageGalvanizationLoadExistingHandler)
        self.assertIsInstance(new_handler, ManageGalvanizationLoadNewHandler)
        self.assertNotIsInstance(existing_handler, LegacyActionHandler)
        self.assertNotIsInstance(new_handler, LegacyActionHandler)

    def test_manage_load_new_opens_galvanization_load_dialog_with_correct_proposal_id(self):
        service = FakeGalvanizationService("AGUARDANDO_ENVIO")
        dialog = StatusDialog(service, 55, "GALVANIZACAO")
        action = next(a for a in dialog.context.available_actions if a.id == "MANAGE_LOAD_NEW")
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = 0
        with patch(
            "app.ui.action_center.handlers.galvanization.GalvanizationLoadDialog", return_value=fake_dialog
        ) as ctor:
            dialog.run_action(action)
        ctor.assert_called_once_with(service, [55], parent=dialog)

    def test_manage_load_new_cancel_does_not_close_action_center_or_write(self):
        service = FakeGalvanizationService("AGUARDANDO_ENVIO")
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        action = next(a for a in dialog.context.available_actions if a.id == "MANAGE_LOAD_NEW")
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = 0
        with patch(
            "app.ui.action_center.handlers.galvanization.GalvanizationLoadDialog", return_value=fake_dialog
        ):
            dialog.run_action(action)
        self.assertFalse(dialog.result())
        self.assertFalse(any(call[0] == "update_status" for call in service.calls))

    def test_manage_load_new_success_accepts_action_center_for_refresh(self):
        service = FakeGalvanizationService("AGUARDANDO_ENVIO")
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        action = next(a for a in dialog.context.available_actions if a.id == "MANAGE_LOAD_NEW")
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = 1
        with patch(
            "app.ui.action_center.handlers.galvanization.GalvanizationLoadDialog", return_value=fake_dialog
        ):
            dialog.run_action(action)
        self.assertTrue(dialog.result())

    def test_manage_load_existing_shows_chooser_then_opens_with_load_id(self):
        service = FakeGalvanizationService(
            "AGUARDANDO_ENVIO", loads=[{"id": 14, "status": "AGUARDANDO_LIBERACAO"}]
        )
        dialog = StatusDialog(service, 55, "GALVANIZACAO")
        action = next(a for a in dialog.context.available_actions if a.id == "MANAGE_LOAD_EXISTING")
        fake_chooser = MagicMock()
        fake_chooser.exec.return_value = 1
        fake_chooser.selected_load_id = 14
        fake_load_dialog = MagicMock()
        fake_load_dialog.exec.return_value = 1
        with patch(
            "app.ui.action_center.handlers.galvanization._SelectGalvanizationLoadDialog", return_value=fake_chooser
        ) as chooser_ctor, patch(
            "app.ui.action_center.handlers.galvanization.GalvanizationLoadDialog", return_value=fake_load_dialog
        ) as load_ctor:
            dialog.run_action(action)
        chooser_ctor.assert_called_once()
        load_ctor.assert_called_once_with(service, [55], load_id=14, parent=dialog)
        self.assertTrue(dialog.result())

    def test_manage_load_existing_with_no_open_loads_shows_message(self):
        service = FakeGalvanizationService("AGUARDANDO_ENVIO", loads=[])
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        action = next(a for a in dialog.context.available_actions if a.id == "MANAGE_LOAD_EXISTING")
        with patch("app.ui.action_center.handlers.galvanization.QMessageBox.information") as info, patch(
            "app.ui.action_center.handlers.galvanization.GalvanizationLoadDialog"
        ) as ctor:
            dialog.run_action(action)
        info.assert_called_once()
        ctor.assert_not_called()
        self.assertFalse(dialog.result())

    def test_manage_load_not_offered_outside_eligible_status(self):
        service = FakeGalvanizationService("ENVIADO_GALVANIZACAO", loads=[{"id": 1, "status": "LIBERADA_PARA_ENVIO"}])
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        ids = [a.id for a in dialog.context.available_actions]
        self.assertNotIn("MANAGE_LOAD_EXISTING", ids)
        self.assertNotIn("MANAGE_LOAD_NEW", ids)


class GalvanizationReturnLegacyCompatibilityTests(unittest.TestCase):
    """Secoes 21-25: REGISTER_GALVANIZATION_RETURN continua funcionando pelo
    caminho direto (LegacyActionHandler) enquanto a navegacao oficial nao
    estiver comprovada - nenhuma regra foi alterada."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_register_return_still_uses_legacy_handler(self):
        from app.ui.action_center.handlers.legacy import LegacyActionHandler

        handler = StatusDialog._build_registry().resolve("REGISTER_GALVANIZATION_RETURN", "GALVANIZACAO")
        self.assertIsInstance(handler, LegacyActionHandler)

    def test_single_active_load_opens_return_dialog(self):
        service = FakeGalvanizationService("ENVIADO_GALVANIZACAO", loads=[{"id": 14, "status": "LIBERADA_PARA_ENVIO"}])
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        action = next(a for a in dialog.context.available_actions if a.id == "REGISTER_GALVANIZATION_RETURN")
        fake_dialog = MagicMock()
        fake_dialog.exec.return_value = 1
        with patch(
            "app.ui.action_center.handlers.galvanization.GalvanizationReturnDialog", return_value=fake_dialog
        ) as ctor:
            dialog.run_action(action)
        ctor.assert_called_once_with(service, 14, dialog, proposal_ids=[1], extra_load_ids=[])
        self.assertTrue(dialog.result())

    def test_no_active_load_shows_controlled_message(self):
        service = FakeGalvanizationService("RETORNOU_PARCIAL", loads=[])
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        from app.ui.action_center.descriptor import ActionDescriptor

        action = ActionDescriptor(
            id="REGISTER_GALVANIZATION_RETURN", label="Registrar retorno", description="", icon=None,
            category=ActionCategory.NORMAL, area="GALVANIZACAO",
        )
        with patch("app.ui.action_center.handlers.galvanization.QMessageBox.information") as info:
            dialog.run_action(action)
        info.assert_called_once()
        self.assertFalse(any(call[0] == "update_status" for call in service.calls))


class OpenRelatedLoadNavigationTests(unittest.TestCase):
    """Secoes 14-19, 41-43: acao de navegacao proposta -> carga - nunca
    persistida como status, nunca escolhe uma carga arbitraria quando ha
    ambiguidade, e trata a carga desaparecida sem crashar."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_no_related_load_does_not_offer_navigation(self):
        service = FakeGalvanizationService("AGUARDANDO_ENVIO", loads=[])
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        self.assertNotIn("OPEN_RELATED_GALVANIZATION_LOAD", [a.id for a in dialog.context.available_actions])

    def test_closed_load_alone_does_not_offer_navigation(self):
        service = FakeGalvanizationService("AGUARDANDO_ENVIO", loads=[{"id": 9, "status": "RETORNADA_GALVANIZACAO"}])
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        self.assertNotIn("OPEN_RELATED_GALVANIZATION_LOAD", [a.id for a in dialog.context.available_actions])

    def test_single_relevant_load_offers_navigation_with_its_number(self):
        service = FakeGalvanizationService("ENVIADO_GALVANIZACAO", loads=[{"id": 14, "status": "LIBERADA_PARA_ENVIO"}])
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        nav = next(a for a in dialog.context.available_actions if a.id == "OPEN_RELATED_GALVANIZATION_LOAD")
        self.assertIn("14", nav.label)
        self.assertEqual(nav.category, ActionCategory.NORMAL)

    def test_navigation_action_is_never_primary(self):
        service = FakeGalvanizationService("ENVIADO_GALVANIZACAO", loads=[{"id": 14, "status": "LIBERADA_PARA_ENVIO"}])
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        primaries = [a for a in dialog.context.available_actions if a.category == ActionCategory.PRIMARY]
        self.assertNotIn("OPEN_RELATED_GALVANIZATION_LOAD", [a.id for a in primaries])

    def test_single_relevant_load_opens_details_dialog_directly(self):
        service = FakeGalvanizationService("ENVIADO_GALVANIZACAO", loads=[{"id": 14, "status": "LIBERADA_PARA_ENVIO"}])
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        action = next(a for a in dialog.context.available_actions if a.id == "OPEN_RELATED_GALVANIZATION_LOAD")
        fake_details = MagicMock()
        fake_details.exec.return_value = 1
        fake_details.changed = False
        with patch(
            "app.ui.action_center.handlers.galvanization.GalvanizationLoadDetailsDialog", return_value=fake_details
        ) as ctor:
            dialog.run_action(action)
        ctor.assert_called_once_with(service, 14, dialog)
        self.assertFalse(dialog.result())  # so navegacao, sem mudanca: Central continua aberta

    def test_details_dialog_change_triggers_reload_not_close(self):
        service = FakeGalvanizationService("ENVIADO_GALVANIZACAO", loads=[{"id": 14, "status": "LIBERADA_PARA_ENVIO"}])
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        action = next(a for a in dialog.context.available_actions if a.id == "OPEN_RELATED_GALVANIZATION_LOAD")
        fake_details = MagicMock()
        fake_details.exec.return_value = 1
        fake_details.changed = True
        with patch(
            "app.ui.action_center.handlers.galvanization.GalvanizationLoadDetailsDialog", return_value=fake_details
        ):
            dialog.run_action(action)
        self.assertFalse(dialog.result())  # ainda aberta - reload_context, nao accept()
        self.assertTrue(dialog._changed_since_open)

    def test_multiple_relevant_loads_offer_a_chooser_label(self):
        service = FakeGalvanizationService(
            "ENVIADO_GALVANIZACAO",
            loads=[{"id": 12, "status": "LIBERADA_PARA_ENVIO"}, {"id": 14, "status": "RETORNO_PARCIAL"}],
        )
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        nav = next(a for a in dialog.context.available_actions if a.id == "OPEN_RELATED_GALVANIZATION_LOAD")
        self.assertEqual(nav.label, "Ver cargas da proposta")

    def test_multiple_relevant_loads_never_open_the_first_one_arbitrarily(self):
        service = FakeGalvanizationService(
            "ENVIADO_GALVANIZACAO",
            loads=[{"id": 12, "status": "LIBERADA_PARA_ENVIO"}, {"id": 14, "status": "RETORNO_PARCIAL"}],
        )
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        action = next(a for a in dialog.context.available_actions if a.id == "OPEN_RELATED_GALVANIZATION_LOAD")
        fake_chooser = MagicMock()
        fake_chooser.exec.return_value = 0  # usuario fecha sem escolher
        with patch(
            "app.ui.action_center.handlers.galvanization._SelectGalvanizationLoadDialog", return_value=fake_chooser
        ) as chooser_ctor, patch(
            "app.ui.action_center.handlers.galvanization.GalvanizationLoadDetailsDialog"
        ) as details_ctor:
            dialog.run_action(action)
        chooser_ctor.assert_called_once()
        details_ctor.assert_not_called()

    def test_multiple_relevant_loads_opens_the_chosen_one(self):
        service = FakeGalvanizationService(
            "ENVIADO_GALVANIZACAO",
            loads=[{"id": 12, "status": "LIBERADA_PARA_ENVIO"}, {"id": 14, "status": "RETORNO_PARCIAL"}],
        )
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        action = next(a for a in dialog.context.available_actions if a.id == "OPEN_RELATED_GALVANIZATION_LOAD")
        fake_chooser = MagicMock()
        fake_chooser.exec.return_value = 1
        fake_chooser.selected_load_id = 14
        fake_details = MagicMock()
        fake_details.exec.return_value = 1
        fake_details.changed = False
        with patch(
            "app.ui.action_center.handlers.galvanization._SelectGalvanizationLoadDialog", return_value=fake_chooser
        ), patch(
            "app.ui.action_center.handlers.galvanization.GalvanizationLoadDetailsDialog", return_value=fake_details
        ) as details_ctor:
            dialog.run_action(action)
        details_ctor.assert_called_once_with(service, 14, dialog)

    def test_load_disappearing_between_open_and_click_shows_controlled_message(self):
        """Concorrencia (secao 43): a Central foi montada com uma carga
        ativa, mas outro usuario a liberou/fechou antes do clique - o
        handler resolve de novo e nao deve confiar no snapshot."""
        service = FakeGalvanizationService("ENVIADO_GALVANIZACAO", loads=[{"id": 14, "status": "LIBERADA_PARA_ENVIO"}])
        dialog = StatusDialog(service, 1, "GALVANIZACAO")
        action = next(a for a in dialog.context.available_actions if a.id == "OPEN_RELATED_GALVANIZATION_LOAD")
        service.loads = [{"id": 14, "status": "RETORNADA_GALVANIZACAO"}]  # fechada entre a abertura e o clique
        with patch("app.ui.action_center.handlers.galvanization.QMessageBox.information") as info, patch(
            "app.ui.action_center.handlers.galvanization.GalvanizationLoadDetailsDialog"
        ) as details_ctor:
            dialog.run_action(action)
        info.assert_called_once()
        details_ctor.assert_not_called()

    def test_process_loads_called_once_per_action_center_open_not_per_card(self):
        """Secao 20: abrir a Central nao deve provocar N+1 - uma unica
        chamada de leitura para resolver a navegacao, nao uma por card."""
        service = FakeGalvanizationService("AGUARDANDO_ENVIO", loads=[{"id": 14, "status": "AGUARDANDO_LIBERACAO"}])
        StatusDialog(service, 1, "GALVANIZACAO")
        self.assertEqual(service.calls.count(("process_loads", 1)), 1)


class GalvanizationProviderContractTests(unittest.TestCase):
    """Secao 63.5: nenhum descriptor devolvido pelo provider de Galvanizacao
    fica sem handler registrado, incluindo a acao de navegacao adicionada
    pelo GalvanizationActionProvider."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_every_descriptor_has_a_registered_handler(self):
        registry = StatusDialog._build_registry()
        scenarios = [
            ("AGUARDANDO_ENVIO", []),
            ("DISPONIVEL_PARCIAL", [{"id": 14, "status": "AGUARDANDO_LIBERACAO"}]),
            ("ENVIADO_GALVANIZACAO", [{"id": 14, "status": "LIBERADA_PARA_ENVIO"}]),
            ("RETORNOU_PARCIAL", [{"id": 14, "status": "RETORNO_PARCIAL"}]),
            ("RETORNOU_GALVANIZACAO", [{"id": 14, "status": "RETORNADA_GALVANIZACAO"}]),
        ]
        for status, loads in scenarios:
            with self.subTest(status=status):
                service = FakeGalvanizationService(status, loads=loads)
                provider = GalvanizationActionProvider(service)
                context = ProposalActionContext(
                    proposal_id=1, area="GALVANIZACAO", current_status=status, proposal_number="CP1", client_name="X",
                )
                for descriptor in provider.get_actions(context):
                    self.assertIsNotNone(
                        registry.resolve(descriptor.id, descriptor.area), f"sem handler para {descriptor.id!r}"
                    )

    def test_non_galvanization_area_is_untouched_by_the_wrapper(self):
        from app.ui.action_center.provider import BackendActionProvider

        class FakeProductionService:
            palette = OFFICIAL_COLOR_PALETTES["claro"]

            def process_actions(self, process_id, area):
                return [{"id": "STATUS", "label": "Iniciar producao", "icon": "production", "status": "INICIADO", "area": "PRODUCAO"}]

        service = FakeProductionService()
        context = ProposalActionContext(
            proposal_id=1, area="PRODUCAO", current_status="NAO_INICIADO", proposal_number="CP1", client_name="X",
        )
        wrapped = GalvanizationActionProvider(service).get_actions(context)
        plain = BackendActionProvider(service).get_actions(context)
        self.assertEqual([d.id for d in wrapped], [d.id for d in plain])


class ChooseExistingLoadForAdditionTests(unittest.TestCase):
    """`choose_existing_load_for_addition` (Fase 8: divisao de "Adicionar a
    uma carga" em "carga existente" vs "criar nova") - so oferece cargas
    ainda abertas (AGUARDANDO_LIBERACAO) e nunca escolhe uma arbitraria."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_no_open_loads_shows_message_and_returns_none(self):
        from app.ui.action_center.handlers.galvanization import choose_existing_load_for_addition

        service = MagicMock()
        service.galvanization_loads.return_value = [{"id": 9, "status": "RETORNADA_GALVANIZACAO"}]
        with patch("app.ui.action_center.handlers.galvanization.QMessageBox.information") as info:
            result = choose_existing_load_for_addition(service, None)
        info.assert_called_once()
        self.assertIsNone(result)

    def test_only_awaiting_release_loads_are_offered(self):
        from app.ui.action_center.handlers.galvanization import choose_existing_load_for_addition

        service = MagicMock()
        service.galvanization_loads.return_value = [
            {"id": 14, "status": "AGUARDANDO_LIBERACAO"},
            {"id": 15, "status": "LIBERADA_PARA_ENVIO"},
            {"id": 16, "status": "RETORNADA_GALVANIZACAO"},
        ]
        with patch(
            "app.ui.action_center.handlers.galvanization._SelectGalvanizationLoadDialog"
        ) as chooser_ctor:
            chooser_ctor.return_value.exec.return_value = 1
            chooser_ctor.return_value.selected_load_id = 14
            result = choose_existing_load_for_addition(service, None)
        passed_loads = chooser_ctor.call_args.args[0]
        self.assertEqual([row["id"] for row in passed_loads], [14])
        self.assertEqual(result, 14)

    def test_cancelling_the_chooser_returns_none(self):
        from app.ui.action_center.handlers.galvanization import choose_existing_load_for_addition

        service = MagicMock()
        service.galvanization_loads.return_value = [{"id": 14, "status": "AGUARDANDO_LIBERACAO"}]
        with patch(
            "app.ui.action_center.handlers.galvanization._SelectGalvanizationLoadDialog"
        ) as chooser_ctor:
            chooser_ctor.return_value.exec.return_value = 0
            result = choose_existing_load_for_addition(service, None)
        self.assertIsNone(result)

    def test_service_error_is_treated_as_no_loads_available(self):
        from app.ui.action_center.handlers.galvanization import choose_existing_load_for_addition

        service = MagicMock()
        service.galvanization_loads.side_effect = RuntimeError("offline")
        with patch("app.ui.action_center.handlers.galvanization.QMessageBox.information") as info:
            result = choose_existing_load_for_addition(service, None)
        info.assert_called_once()
        self.assertIsNone(result)


class ResolveReturnLoadIdsTests(unittest.TestCase):
    """`resolve_return_load_ids` - agrega TODAS as cargas retornaveis
    (LIBERADA_PARA_ENVIO/RETORNO_PARCIAL) relacionadas as propostas
    selecionadas, sem forcar uma escolha unica: a selecao pode abranger
    cargas diferentes de proposito, e quem chama processa cada carga
    devolvida em sequencia."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_no_returnable_load_shows_message_and_returns_empty(self):
        from app.ui.action_center.handlers.galvanization import resolve_return_load_ids

        service = MagicMock()
        service.process_loads.side_effect = lambda proposal_id: {
            10: [{"id": 9, "status": "RETORNADA_GALVANIZACAO"}],
            20: [],
        }[proposal_id]
        with patch("app.ui.action_center.handlers.galvanization.QMessageBox.information") as info:
            result = resolve_return_load_ids(service, [10, 20], None)
        info.assert_called_once()
        self.assertEqual(result, [])

    def test_single_shared_load_is_returned_without_any_message(self):
        from app.ui.action_center.handlers.galvanization import resolve_return_load_ids

        service = MagicMock()
        service.process_loads.side_effect = lambda proposal_id: {
            10: [{"id": 30, "status": "LIBERADA_PARA_ENVIO"}],
            20: [{"id": 30, "status": "RETORNO_PARCIAL"}],
        }[proposal_id]
        with patch("app.ui.action_center.handlers.galvanization.QMessageBox.information") as info:
            result = resolve_return_load_ids(service, [10, 20], None)
        info.assert_not_called()
        self.assertEqual(result, [30])

    def test_different_loads_are_all_returned_without_any_message(self):
        # A selecao abrange propostas de cargas diferentes de proposito -
        # ambas sao devolvidas para uma unica tela combinada (coluna "Carga"
        # as diferencia), sem interromper o usuario com um aviso previo.
        from app.ui.action_center.handlers.galvanization import resolve_return_load_ids

        service = MagicMock()
        service.process_loads.side_effect = lambda proposal_id: {
            10: [{"id": 30, "status": "LIBERADA_PARA_ENVIO"}],
            20: [{"id": 31, "status": "RETORNO_PARCIAL"}],
        }[proposal_id]
        with patch("app.ui.action_center.handlers.galvanization.QMessageBox.information") as info:
            result = resolve_return_load_ids(service, [10, 20], None)
        info.assert_not_called()
        self.assertEqual(result, [30, 31])

    def test_service_error_is_treated_as_no_loads_available(self):
        from app.ui.action_center.handlers.galvanization import resolve_return_load_ids

        service = MagicMock()
        service.process_loads.side_effect = RuntimeError("offline")
        with patch("app.ui.action_center.handlers.galvanization.QMessageBox.information") as info:
            result = resolve_return_load_ids(service, [10, 20], None)
        info.assert_called_once()
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
