"""Desktop: dialogo "Desfazer ultima acao", card da Central de Acoes, botao dos Detalhes e historico."""

from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES, AppError
from app.ui.action_center import undo_dialog as undo_dialog_module
from app.ui.action_center.context import ProposalActionContext
from app.ui.action_center.descriptor import ActionCategory
from app.ui.action_center.handlers.undo import UndoLastActionHandler
from app.ui.action_center.provider import (
    CATEGORY_TO_CARD_TYPE, PRIMARY_ACTION_KEYS, UNDO_ACTION_ID, BackendActionProvider, UndoActionProvider,
)
from app.ui.action_center.undo_dialog import UNDO_ERROR_MESSAGES, UndoActionDialog
from app.ui.process_detail.historico_tab import HistoricoTab
from app.ui.process_detail_dialog import ProcessDetailDialog
from app.ui.status_dialog import StatusDialog
from tests.test_process_detail_dialog import FakeDetailService
from tests.test_status_dialog import FakeService as ProductionFakeService
from tests.undo_fakes import NoUndoActionMixin


def sync_worker(_owner, operation, on_success, on_error, *, operation_name=None):
    try:
        result = operation()
    except Exception as exc:  # noqa: BLE001 - espelha o Worker real
        on_error(exc)
    else:
        on_success(result)


def candidate(**over) -> dict:
    base = {
        "proposal_id": 10, "proposal_version": 7, "handler": "RELEASE_PROPOSAL", "undo_class": "C",
        "undoable": True, "can_undo": True, "cannot_undo_reason": None, "blockers": [],
        "action": {
            "request_id": "req-1", "event_type": "PROPOSAL_RELEASED", "label": "Liberar proposta",
            "title": "Proposta liberada para produção", "actor_user_id": 3, "actor_name": "Maria",
            "created_at": "2026-11-05T14:30:00Z", "event_count": 1,
        },
        "changes": [
            {"field": "current_area", "label": "Área atual", "current_value": "PRODUCAO", "restored_value": "CONTROLE_GERAL"},
            {"field": "items[1].status", "label": "Item 1: status", "current_value": "LIBERADO", "restored_value": None},
        ],
        "side_effects": [{"code": "ALMOX_NOT_NOTIFIED", "message": "O Almox+ não é avisado; a conciliação horária acerta."}],
    }
    base.update(over)
    return base


class FakeUndoService(NoUndoActionMixin):
    palette = OFFICIAL_COLOR_PALETTES["claro"]

    def __init__(self, candidates=None, outcomes=None):
        self.candidates = list(candidates or [candidate()])
        self.outcomes = list(outcomes or [{"id": 10, "version": 8}])
        self.get_calls = 0
        self.post_calls: list[tuple] = []

    def undo_candidate(self, process_id):
        item = self.candidates[min(self.get_calls, len(self.candidates) - 1)]
        self.get_calls += 1
        if isinstance(item, Exception):
            raise item
        return item

    def undo_last_action(self, process_id, expected_version, target_request_id, reason, idempotency_key):
        self.post_calls.append((process_id, expected_version, target_request_id, reason, idempotency_key))
        outcome = self.outcomes.pop(0) if self.outcomes else {"id": process_id}
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        patcher = patch.object(undo_dialog_module, "start_worker", sync_worker)
        patcher.start()
        self.addCleanup(patcher.stop)


class UndoDialogTests(QtCase):
    def _dialog(self, service=None, **kwargs):
        service = service or FakeUndoService()
        return UndoActionDialog(service, 10, None, **kwargs), service

    def test_dialog_module_has_no_message_box(self):
        self.assertFalse(hasattr(undo_dialog_module, "QMessageBox"))

    def test_renders_action_changes_and_side_effect_banner(self):
        dialog, service = self._dialog(candidate=candidate())
        self.assertEqual(service.get_calls, 0)  # candidato vindo da Central: sem nova consulta
        self.assertEqual(dialog.action_title.text(), "Proposta liberada para produção")
        self.assertIn("Maria", dialog.action_meta.text())
        self.assertIn("05/11/2026", dialog.action_meta.text())
        table = dialog.changes_table
        self.assertEqual(table.rowCount(), 2)
        self.assertEqual([table.item(0, col).text() for col in range(3)], ["Área atual", "PRODUCAO", "CONTROLE_GERAL"])
        self.assertEqual(table.item(1, 2).text(), "—")  # restored_value None
        self.assertEqual(dialog.side_effects_box.count(), 1)
        self.assertIn("Almox+", dialog.side_effects_box.itemAt(0).widget().text())
        self.assertTrue(dialog.reason_notice.isHidden())

    def test_without_candidate_it_loads_on_open(self):
        service = FakeUndoService([candidate(proposal_version=9)])
        dialog, _ = self._dialog(service)
        self.assertEqual(service.get_calls, 1)
        self.assertEqual(dialog.candidate["proposal_version"], 9)

    def test_load_failure_is_inline_and_blocks_confirm(self):
        dialog, _ = self._dialog(FakeUndoService([AppError("sem rede")]))
        self.assertFalse(dialog.error_label.isHidden())
        self.assertIn("sem rede", dialog.error_label.text())
        dialog.reason.setPlainText("motivo")
        self.assertFalse(dialog.undo_button.isEnabled())

    def test_confirm_needs_can_undo_undoable_and_a_reason(self):
        dialog, _ = self._dialog(candidate=candidate())
        self.assertFalse(dialog.undo_button.isEnabled())
        dialog.reason.setPlainText("   ")
        self.assertFalse(dialog.undo_button.isEnabled())
        dialog.reason.setPlainText("liberei a proposta errada")
        self.assertTrue(dialog.undo_button.isEnabled())
        dialog.reason.setPlainText("x" * 1001)
        self.assertFalse(dialog.undo_button.isEnabled())
        for broken in (candidate(can_undo=False), candidate(undoable=False)):
            other, _ = self._dialog(candidate=broken)
            other.reason.setPlainText("motivo")
            self.assertFalse(other.undo_button.isEnabled())

    def test_not_undoable_shows_the_api_reason_and_alternative(self):
        reason = "Esta ação não pode ser desfeita. Use Remanejar para corrigir."
        dialog, _ = self._dialog(candidate=candidate(
            undoable=False, can_undo=False, handler=None, undo_class=None, changes=[], side_effects=[], cannot_undo_reason=reason,
        ))
        self.assertFalse(dialog.reason_notice.isHidden())
        self.assertEqual(dialog.reason_notice.text(), reason)
        self.assertTrue(dialog.changes_table.isHidden())

    def test_no_action_message(self):
        dialog, _ = self._dialog(candidate=candidate(
            action=None, handler=None, undo_class=None, undoable=False, can_undo=False, changes=[], side_effects=[],
            cannot_undo_reason="Nao ha nenhuma acao para desfazer nesta proposta.",
        ))
        self.assertIn("Nao ha nenhuma acao", dialog.reason_notice.text())
        self.assertFalse(dialog.undo_button.isEnabled())

    def test_success_posts_contract_args_and_accepts(self):
        dialog, service = self._dialog(candidate=candidate())
        dialog.reason.setPlainText("  liberada por engano  ")
        dialog.submit()
        self.assertEqual(len(service.post_calls), 1)
        process_id, version, target, reason, key = service.post_calls[0]
        self.assertEqual((process_id, version, target, reason), (10, 7, "req-1", "liberada por engano"))
        self.assertGreaterEqual(len(key), 8)
        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertEqual(dialog.updated_process, {"id": 10, "version": 8})

    def test_key_is_kept_on_timeout_and_changes_when_reason_changes(self):
        timeout = AppError("O servidor demorou mais que o esperado para responder.")
        service = FakeUndoService(outcomes=[timeout, timeout, {"id": 10}])
        dialog, _ = self._dialog(service, candidate=candidate())
        dialog.reason.setPlainText("motivo um")
        dialog.submit()
        dialog.submit()
        self.assertEqual(service.post_calls[0][4], service.post_calls[1][4])
        self.assertIn("demorou", dialog.error_label.text())
        self.assertNotEqual(dialog.result(), dialog.DialogCode.Accepted)
        dialog.reason.setPlainText("motivo dois")
        dialog.submit()
        self.assertNotEqual(service.post_calls[1][4], service.post_calls[2][4])

    def test_idempotency_conflict_gets_a_new_key(self):
        conflict = AppError("x", error_code="UNDO_IDEMPOTENCY_CONFLICT")
        service = FakeUndoService(outcomes=[conflict, {"id": 10}])
        dialog, _ = self._dialog(service, candidate=candidate())
        dialog.reason.setPlainText("motivo")
        dialog.submit()
        self.assertEqual(dialog.error_label.text(), UNDO_ERROR_MESSAGES["UNDO_IDEMPOTENCY_CONFLICT"])
        dialog.submit()
        self.assertNotEqual(service.post_calls[0][4], service.post_calls[1][4])

    def test_version_conflict_reloads_keeping_the_reason(self):
        fresh = candidate(proposal_version=9)
        service = FakeUndoService([candidate(), fresh], [AppError("x", error_code="PROPOSAL_VERSION_CONFLICT")])
        dialog, _ = self._dialog(service)
        dialog.reason.setPlainText("meu motivo")
        dialog.submit()
        self.assertEqual(service.get_calls, 2)
        self.assertEqual(dialog.candidate["proposal_version"], 9)
        self.assertEqual(dialog.reason.toPlainText(), "meu motivo")
        self.assertEqual(dialog.error_label.text(), UNDO_ERROR_MESSAGES["PROPOSAL_VERSION_CONFLICT"])
        dialog.submit()
        self.assertEqual(service.post_calls[1][1], 9)
        self.assertNotEqual(service.post_calls[0][4], service.post_calls[1][4])  # versao mudou: chave nova

    def test_target_changed_codes_reload_and_clear_the_reason(self):
        for code in ("UNDO_NOT_LATEST", "UNDO_ALREADY_UNDONE", "UNDO_ACTION_NOT_FOUND"):
            with self.subTest(code=code):
                other = candidate()
                other["action"] = {**other["action"], "request_id": "req-2", "title": "Outra ação"}
                service = FakeUndoService([candidate(), other], [AppError("x", error_code=code, details={"latest_request_id": "req-2"})])
                dialog, _ = self._dialog(service)
                dialog.reason.setPlainText("motivo")
                dialog.submit()
                self.assertEqual(service.get_calls, 2)
                self.assertEqual(dialog.action_title.text(), "Outra ação")
                self.assertEqual(dialog.reason.toPlainText(), "")
                self.assertEqual(dialog.error_label.text(), UNDO_ERROR_MESSAGES[code])

    def test_blocked_lists_blockers_and_disables_confirm(self):
        details = {"blockers": [{"code": "PRODUCTION_ALREADY_STARTED", "message": "A produção já começou."}]}
        service = FakeUndoService(outcomes=[AppError("x", error_code="UNDO_BLOCKED", details=details)])
        dialog, _ = self._dialog(service, candidate=candidate())
        dialog.reason.setPlainText("motivo")
        dialog.submit()
        self.assertEqual(dialog.error_label.text(), UNDO_ERROR_MESSAGES["UNDO_BLOCKED"])
        self.assertEqual(dialog.error_blockers_box.count(), 1)
        self.assertIn("A produção já começou.", dialog.error_blockers_box.itemAt(0).widget().text())
        self.assertFalse(dialog.undo_button.isEnabled())

    def test_not_supported_shows_api_alternative_and_disables_confirm(self):
        message = "Cancelar não pode ser desfeito. Crie uma nova proposta."
        service = FakeUndoService(outcomes=[AppError(message, error_code="UNDO_NOT_SUPPORTED")])
        dialog, _ = self._dialog(service, candidate=candidate())
        dialog.reason.setPlainText("motivo")
        dialog.submit()
        self.assertEqual(dialog.error_label.text(), message)
        self.assertFalse(dialog.undo_button.isEnabled())
        self.assertEqual(len(service.post_calls), 1)

    def test_permission_error_is_inline(self):
        service = FakeUndoService(outcomes=[AppError("Seu usuario nao possui permissao na API para esta operacao.")])
        dialog, _ = self._dialog(service, candidate=candidate())
        dialog.reason.setPlainText("motivo")
        dialog.submit()
        self.assertIn("permissao", dialog.error_label.text())
        self.assertTrue(dialog.undo_button.isEnabled())  # pode tentar de novo

    def test_candidate_without_version_cannot_be_confirmed(self):
        broken = candidate()
        del broken["proposal_version"]
        dialog, _ = self._dialog(candidate=broken)
        dialog.reason.setPlainText("motivo")
        self.assertFalse(dialog.undo_button.isEnabled())

    def test_permission_denied_code_uses_the_mapped_text(self):
        service = FakeUndoService(outcomes=[AppError("x", error_code="PERMISSION_DENIED")])
        dialog, _ = self._dialog(service, candidate=candidate())
        dialog.reason.setPlainText("motivo")
        dialog.submit()
        self.assertEqual(dialog.error_label.text(), UNDO_ERROR_MESSAGES["PERMISSION_DENIED"])

    def test_cancel_does_not_post(self):
        dialog, service = self._dialog(candidate=candidate())
        dialog.cancel_button.click()
        self.assertEqual(service.post_calls, [])
        self.assertEqual(dialog.result(), dialog.DialogCode.Rejected)


class UndoProviderTests(QtCase):
    CONTEXT = ProposalActionContext(proposal_id=10, area="PRODUCAO", current_status="INICIADO", proposal_number="CP1", client_name="X")

    class Inner:
        def get_actions(self, context):
            return BackendActionProvider(ProductionFakeService("INICIADO")).get_actions(context)

    def _actions(self, service):
        return UndoActionProvider(self.Inner(), service).get_actions(self.CONTEXT)

    def test_adds_attention_card_last_and_never_primary(self):
        actions = self._actions(FakeUndoService([candidate()]))
        undo = actions[-1]
        self.assertEqual(undo.id, UNDO_ACTION_ID)
        self.assertEqual(undo.category, ActionCategory.ATTENTION)
        self.assertEqual(CATEGORY_TO_CARD_TYPE[undo.category], "warning")
        self.assertEqual(undo.raw["candidate"]["proposal_version"], 7)
        self.assertNotIn(UNDO_ACTION_ID, [key[0] for key in PRIMARY_ACTION_KEYS])
        self.assertEqual(sum(1 for action in actions if action.category == ActionCategory.PRIMARY), 1)
        self.assertNotEqual(next(a for a in actions if a.category == ActionCategory.PRIMARY).id, UNDO_ACTION_ID)

    def test_card_disappears_when_the_get_fails(self):
        actions = self._actions(FakeUndoService([AppError("falhou")]))
        self.assertNotIn(UNDO_ACTION_ID, [action.id for action in actions])
        self.assertTrue(actions)  # as demais acoes seguem intactas

    def test_card_disappears_without_a_last_action(self):
        self.assertNotIn(UNDO_ACTION_ID, [a.id for a in self._actions(NoUndoActionMixin())])

    def test_non_dict_candidate_is_ignored(self):
        class Weird:
            def undo_candidate(self, process_id):
                return object()

        self.assertNotIn(UNDO_ACTION_ID, [a.id for a in self._actions(Weird())])

    def test_not_undoable_action_still_gets_a_card_that_explains_why(self):
        actions = self._actions(FakeUndoService([candidate(undoable=False, can_undo=False, cannot_undo_reason="não dá")]))
        undo = actions[-1]
        self.assertEqual(undo.id, UNDO_ACTION_ID)
        self.assertIn("não pode ser desfeita", undo.description)


class _UndoProductionService(ProductionFakeService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.get_calls = 0

    def undo_candidate(self, process_id):
        self.get_calls += 1
        return candidate()


class StatusDialogUndoTests(QtCase):
    def test_registry_resolves_the_undo_handler(self):
        self.assertIsInstance(StatusDialog._build_registry().resolve(UNDO_ACTION_ID, "PRODUCAO"), UndoLastActionHandler)

    def test_status_dialog_shows_undo_card_and_keeps_the_primary(self):
        dialog = StatusDialog(_UndoProductionService("INICIADO"), 1, "PRODUCAO")
        by_id = {action.id: action for action in dialog.context.available_actions}
        self.assertEqual(by_id[UNDO_ACTION_ID].category, ActionCategory.ATTENTION)
        self.assertEqual(by_id["REGISTER_PRODUCTION"].category, ActionCategory.PRIMARY)
        self.assertEqual(dialog.service.get_calls, 1)
        dialog.reload_context()
        self.assertEqual(dialog.service.get_calls, 2)

    def test_status_dialog_without_last_action_has_no_undo_card(self):
        dialog = StatusDialog(ProductionFakeService("INICIADO"), 1, "PRODUCAO")
        self.assertNotIn(UNDO_ACTION_ID, [action.id for action in dialog.context.available_actions])

    def test_handler_closes_center_only_when_undone(self):
        dialog = StatusDialog(_UndoProductionService("INICIADO"), 1, "PRODUCAO")
        undo = next(action for action in dialog.context.available_actions if action.id == UNDO_ACTION_ID)
        for accepted in (0, 1):
            with patch("app.ui.action_center.handlers.undo.UndoActionDialog") as ctor:
                ctor.return_value.exec.return_value = accepted
                with patch.object(dialog, "accept") as accept:
                    result = UndoLastActionHandler().execute(dialog.context, undo, dialog)
            self.assertEqual(ctor.call_args.kwargs["candidate"]["proposal_version"], 7)
            self.assertEqual(accept.called, bool(accepted))
            self.assertEqual(result.changed, bool(accepted))


class _EmptyGalvanizationService(_UndoProductionService):
    def process_actions(self, process_id, area):
        return []

    def current_location(self, process):
        return ("GALVANIZACAO", "Galvanizacao", "AGUARDANDO_ENVIO")

    def process_loads(self, process_id):
        return []


class EmptyStateWithUndoCardTests(QtCase):
    def test_caption_still_explains_when_only_the_undo_card_exists(self):
        from PySide6.QtWidgets import QLabel

        dialog = StatusDialog(_EmptyGalvanizationService("AGUARDANDO_ENVIO"), 1, "GALVANIZACAO")
        self.assertEqual([a.id for a in dialog.context.available_actions], [UNDO_ACTION_ID])
        texts = [label.text() for label in dialog._actions_container.findChildren(QLabel)]
        self.assertIn("Esta movimentação é controlada pela tela Cargas.", texts)
        self.assertEqual(len(dialog._action_buttons), 1)


class HistoryUndoneRowTests(QtCase):
    def test_undone_row_is_struck_muted_and_labelled(self):
        class Service:
            palette = OFFICIAL_COLOR_PALETTES["claro"]

            def process_history_rows(self, process_id):
                base = {"area": "PRODUCAO", "status_real_novo": "INICIADO", "status_anterior": "", "data_hora": "05/11/2026 10:00:00",
                        "titulo": "Maria iniciou a produção.", "detalhe": "", "quantidade": 1, "observacao": ""}
                return [
                    {**base, "data_hora": "05/11/2026 10:00:00", "desfeita": True},
                    {**base, "data_hora": "05/11/2026 11:00:00", "titulo": "Maria desfez a ação."},
                ]

            def area_status_label(self, area, status):
                return status

        tab = HistoricoTab(Service())
        tab.load([10])
        newest, undone = 0, 1  # mais recente primeiro
        self.assertEqual(tab.table.item(undone, 3).text(), "Desfeita")
        self.assertTrue(tab.table.item(undone, 2).font().strikeOut())
        self.assertFalse(tab.table.item(undone, 3).font().strikeOut())
        self.assertNotEqual(tab.table.item(undone, 2).foreground(), tab.table.item(newest, 2).foreground())
        self.assertFalse(tab.table.item(newest, 2).font().strikeOut())
        self.assertEqual(tab.table.item(newest, 3).text(), "INICIADO")
        # sem botao por linha
        self.assertIsNone(tab.table.cellWidget(undone, 3))


class DetailDialogUndoButtonTests(QtCase):
    def setUp(self):
        super().setUp()
        self._dialogs: list[ProcessDetailDialog] = []

    def tearDown(self):
        for dialog in self._dialogs:
            for thread in dialog.findChildren(QThread):
                thread.quit()
                thread.wait(2000)
            dialog.deleteLater()
        self.app.processEvents()

    def _open(self, **kwargs) -> ProcessDetailDialog:
        service = FakeDetailService()
        dialog = ProcessDetailDialog(service, 10, None, **kwargs)
        self._dialogs.append(dialog)
        done = {"ok": False}
        dialog.loaded.connect(lambda *_: done.__setitem__("ok", True))
        deadline = time.monotonic() + 5.0
        while not done["ok"] and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        return dialog

    def test_ghost_button_is_present_and_not_the_primary(self):
        dialog = self._open()
        self.assertEqual(dialog.undo_button.text(), "Desfazer última ação")
        self.assertEqual(dialog.undo_button.variant(), "ghost")
        self.assertEqual(dialog.actions_button.variant(), "primary")
        self.assertFalse(dialog.undo_button.isHidden())
        self.assertTrue(dialog.undo_button.isEnabled())

    def test_button_hides_with_more_than_one_process(self):
        dialog = self._open(process_ids=[10, 11])
        self.assertTrue(dialog.undo_button.isHidden())

    def test_click_opens_the_dialog_and_reloads_only_when_undone(self):
        for accepted in (0, 1):
            dialog = self._open()
            with patch("app.ui.process_detail_dialog.UndoActionDialog") as ctor, patch.object(dialog, "load") as load:
                ctor.return_value.exec.return_value = accepted
                dialog.undo_button.click()
            ctor.assert_called_once_with(dialog.service, 10, dialog)
            self.assertEqual(load.called, bool(accepted))
            self.assertEqual(dialog.changed, bool(accepted))


if __name__ == "__main__":
    unittest.main()
