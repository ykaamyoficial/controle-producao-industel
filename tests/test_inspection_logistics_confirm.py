from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from app.services.api_proposal_storage import OfficialProposalApiStorage
from app.services.backend_adapter import AppError
from app.ui.inspection_logistics_confirm import ask_inspection_logistics_confirmation, confirmation_text
from app.ui.process_form_dialog import ProcessFormDialog
from app.ui.status_dialog import StatusDialog
from tests.test_action_center import FakeControlGeneralService, _synchronous_start_worker
from tests.test_process_form_official_api import OfficialServiceSpy

QUESTION = "app.ui.inspection_logistics_confirm.QMessageBox.question"

CANCEL_INFO = {
    "action": "cancel",
    "inspection": {"id": 1, "pd_code": "PD-1201", "nqt_code": "NQT-1", "stage": "nqt"},
    "log": {"id": 2, "code": "LOG101", "stage": "docs", "in_load": False},
    "other_proposals_with_old_pd": 0,
    "inspection_follows_new_pd": False,
    "new_pd_has_inspection": False,
    "leaves_log": True,
}
CHANGE_INFO = {**CANCEL_INFO, "action": "change_order", "inspection_follows_new_pd": True}


def _confirmation(info) -> AppError:
    return AppError("Esta proposta tem inspeção ou LOG.", error_code="INSPECTION_LOGISTICS_CONFIRMATION_REQUIRED", details=info)


class TextTests(unittest.TestCase):
    def test_cancel_text_says_what_happens(self):
        text = confirmation_text(CANCEL_INFO)
        self.assertIn("sai do LOG101", text)
        self.assertIn("inspeção do PD PD-1201 continua", text)

    def test_change_order_text_follows_new_pd_and_leaves_log(self):
        text = confirmation_text(CHANGE_INFO)
        self.assertIn("única proposta com o PD PD-1201", text)
        self.assertIn("passa a acompanhar o novo PD", text)
        self.assertIn("sai do LOG101", text)
        stays = confirmation_text({**CHANGE_INFO, "inspection_follows_new_pd": False, "new_pd_has_inspection": True, "leaves_log": False})
        self.assertIn("já tem inspeção própria", stays)
        self.assertIn("continua no LOG101", stays)

    def test_other_errors_return_none_and_no_question(self):
        with patch(QUESTION) as question:
            self.assertIsNone(ask_inspection_logistics_confirmation(None, AppError("x", error_code="OUTRO")))
        question.assert_not_called()

    def test_without_details_falls_back_to_api_message(self):
        self.assertEqual(confirmation_text({}, "Mensagem da API."), "Mensagem da API.")


class StorageFlagTests(unittest.TestCase):
    def test_flag_goes_in_cancel_and_update_payloads_only_when_confirmed(self):
        sent = {}

        class Proposals:
            def cancel_proposal(self, token, proposal_id, payload):
                sent["cancel"] = payload
                return {"id": proposal_id}

            def get_proposal(self, token, proposal_id):
                return {"id": proposal_id, "version": 3, "items": []}

            def update_proposal(self, token, proposal_id, payload):
                sent["update"] = payload
                return {"id": proposal_id}

        class Client:
            def close(self):
                pass

        storage = OfficialProposalApiStorage.__new__(OfficialProposalApiStorage)
        storage._client = lambda: (Client(), Proposals(), "tok")
        storage._sync_items = lambda *args, **kwargs: None
        with patch("app.services.api_proposal_storage._api_proposal_to_process", lambda row: row):
            storage.cancel_process(1, 3, "motivo")
            self.assertEqual(sent["cancel"], {"version": 3, "reason": "motivo"})
            storage.cancel_process(1, 3, "motivo", True)
            self.assertEqual(sent["cancel"], {"version": 3, "reason": "motivo", "confirm_inspection_logistics": True})
        storage.save_process({"cliente": "C", "pedido_compra": "PD-9", "itens": []}, 1)
        self.assertNotIn("confirm_inspection_logistics", sent["update"])
        storage.save_process({"cliente": "C", "pedido_compra": "PD-9", "itens": []}, 1, None, True)
        self.assertEqual(sent["update"]["purchase_order"], "PD-9")
        self.assertTrue(sent["update"]["confirm_inspection_logistics"])


class _ConfirmingService(FakeControlGeneralService):
    """Primeira chamada sem flag recebe o 409; com a flag, cancela."""

    def update_status(self, process_id, area, status, observation="", item_ids=None, produced_weight=None, confirm_inspection_logistics=False):
        if status == "CANCELADA" and not confirm_inspection_logistics:
            self.calls.append(("update_status", process_id, "sem flag"))
            raise _confirmation(CANCEL_INFO)
        self.calls.append(("update_status", process_id, status, confirm_inspection_logistics))
        return {}


class CancelProposalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _cancel(self, service, answer):
        dialog = StatusDialog(service, 1, "CONTROLE GERAL")
        dialog.observation.setPlainText("cliente desistiu")
        action = next(a for a in dialog.context.available_actions if a.status == "CANCELADA")
        asked = []

        def question(parent, title, text, *args):
            # QMessageBox.question e o mesmo atributo de classe nos dois modulos: separa pela pergunta.
            if "definitivamente" in text:
                return QMessageBox.Yes
            asked.append(text)
            return answer

        with patch(QUESTION, side_effect=question) as mocked:
            with patch("app.ui.action_center.proposal_action_center.start_worker", side_effect=_synchronous_start_worker):
                with patch("app.ui.action_center.proposal_action_center.QMessageBox.warning") as warning:
                    dialog.run_action(action)
        mocked.asked = asked
        return dialog, mocked, warning

    def test_yes_resends_with_confirm_flag(self):
        service = _ConfirmingService("AGUARDANDO_LIBERACAO")
        dialog, question, warning = self._cancel(service, QMessageBox.Yes)
        self.assertEqual(len(question.asked), 1)
        self.assertIn("sai do LOG101", question.asked[0])
        self.assertEqual(service.calls, [("update_status", 1, "sem flag"), ("update_status", 1, "CANCELADA", True)])
        warning.assert_not_called()
        self.assertEqual(dialog.result(), 1)

    def test_no_does_not_resend_and_shows_no_error(self):
        service = _ConfirmingService("AGUARDANDO_LIBERACAO")
        dialog, question, warning = self._cancel(service, QMessageBox.No)
        self.assertEqual(len(question.asked), 1)
        self.assertEqual(service.calls, [("update_status", 1, "sem flag")])
        warning.assert_not_called()
        self.assertNotEqual(dialog.result(), 1)

    def test_other_errors_keep_the_normal_warning(self):
        class Failing(_ConfirmingService):
            def update_status(self, *args, **kwargs):
                raise AppError("Servidor fora do ar.", error_code="OUTRO")

        dialog, question, warning = self._cancel(Failing("AGUARDANDO_LIBERACAO"), QMessageBox.Yes)
        self.assertEqual(question.asked, [])
        warning.assert_called_once()


class ChangeOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    class Spy(OfficialServiceSpy):
        def save_process(self, data, process_id=None, import_metadata=None, confirm_inspection_logistics=False):
            self.save_calls.append((process_id, confirm_inspection_logistics))
            if not confirm_inspection_logistics:
                raise _confirmation(CHANGE_INFO)
            return 123

    def _form(self, answer):
        service = self.Spy()
        form = ProcessFormDialog(service, process_id=10)
        form.fields["pedido_compra"].setText("PD-NOVO") if "pedido_compra" in form.fields else None
        with patch(QUESTION, return_value=answer) as question, patch.object(QMessageBox, "warning") as warning:
            form.save()
        return form, service, question, warning

    def test_yes_saves_again_with_flag(self):
        form, service, question, warning = self._form(QMessageBox.Yes)
        try:
            self.assertEqual(service.save_calls, [(10, False), (10, True)])
            self.assertIn("passa a acompanhar o novo PD", question.call_args.args[2])
            warning.assert_not_called()
            self.assertEqual(form.result(), form.DialogCode.Accepted)
        finally:
            form.close()

    def test_no_keeps_form_open(self):
        form, service, _question, warning = self._form(QMessageBox.No)
        try:
            self.assertEqual(service.save_calls, [(10, False)])
            warning.assert_not_called()
            self.assertNotEqual(form.result(), form.DialogCode.Accepted)
        finally:
            form.close()


if __name__ == "__main__":
    unittest.main()
