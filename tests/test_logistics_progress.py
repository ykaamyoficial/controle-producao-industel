from __future__ import annotations

import os
import unittest
from datetime import timedelta
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QMessageBox

from app.services.backend_adapter import AppError
from app.ui import logistics_dialogs as dialogs_module
from app.ui.logistics_dialogs import LogDetailDialog
from app.ui.logistics_progress import LOG_OUTCOMES, RecordLogProgressDialog
from test_logistics_desktop import FIXED_TODAY, FakeLogisticsApi, FakeService, QtCase, _log

YESTERDAY = (FIXED_TODAY - timedelta(days=1)).isoformat()  # "Ontem" com a data fixada em FIXED_TODAY
LINKS = ("NF-1.pdf", "NF-1.xml", "PD.pdf")


def _progress(stage="reservada", **changes):
    api = FakeLogisticsApi()
    log = _log(stage=stage, **changes)
    api.result = log
    dialog = RecordLogProgressDialog(FakeService(api), log)
    api.calls.clear()
    return dialog, api


class OutcomesTests(unittest.TestCase):
    def test_outcomes_per_stage(self):
        self.assertEqual([o.label for o in LOG_OUTCOMES["reservada"]], ["Documentação enviada", "Entregue no CD"])
        self.assertEqual([o.label for o in LOG_OUTCOMES["docs"]], ["Aprovada para entrega", "Entregue no CD"])
        self.assertEqual([o.label for o in LOG_OUTCOMES["aprovada"]], ["Entregue no CD"])


class RecordLogProgressTests(QtCase):
    def test_docs_outcome_sends_three_links_with_yesterday_and_note(self):
        dialog, api = _progress()
        self.assertEqual(dialog.form.outcome().key, "docs")
        dialog.form.occurred.yesterday_button.click()
        dialog.form.note.setText("NF e XML por e-mail")
        dialog.submit()
        self.assertEqual(dialog.error_label.text(), "Informe os links de NF, XML e BIM.")
        self.assertEqual(api.calls, [])
        for key, value in zip(("nf_link", "xml_link", "bim_link"), LINKS):
            dialog.form.fields[key].setText(value)
        api.result = _log(stage="docs", nf_link="a", xml_link="b", bim_link="c")
        dialog.submit()
        self.assertEqual(
            api.calls,
            [("send_docs", 1, *LINKS, {"occurred_on": YESTERDAY, "note": "NF e XML por e-mail"})],
        )
        self.assertIsNotNone(dialog.result_data)

    def test_fields_show_only_for_the_chosen_outcome(self):
        dialog, _api = _progress()
        self.assertFalse(dialog.form.fields["nf_link"].isHidden())
        self.assertTrue(dialog.form.fields["delivery_proof_link"].isHidden())
        dialog.form.radios["delivered"].setChecked(True)
        self.assertTrue(dialog.form.fields["nf_link"].isHidden())
        self.assertFalse(dialog.form.fields["delivery_proof_link"].isHidden())

    def test_approve_in_docs_stage_sends_date(self):
        dialog, api = _progress(stage="docs")
        dialog.form.occurred.yesterday_button.click()
        dialog.submit()
        self.assertEqual(api.calls, [("approve_log", 1, {"occurred_on": YESTERDAY})])

    def test_delivery_with_proof_link_and_yesterday(self):
        dialog, api = _progress(stage="aprovada")
        api.result = _log(stage="aprovada", delivered_on=YESTERDAY, delivery_proof_link="https://x.example/a.pdf")
        dialog.form.occurred.yesterday_button.click()
        dialog.form.fields["delivery_proof_link"].setText("https://x.example/a.pdf")
        dialog.submit()
        self.assertEqual(api.calls, [("log_delivery", 1, YESTERDAY, "https://x.example/a.pdf", None)])
        self.assertEqual(dialog.result_data["delivered_on"], YESTERDAY)

    def test_delivery_without_proof_sends_no_link(self):
        dialog, api = _progress(stage="reservada")
        dialog.form.radios["delivered"].setChecked(True)
        dialog.form.occurred.set_date(FIXED_TODAY)
        dialog.submit()
        self.assertEqual(api.calls[-1][:4], ("log_delivery", 1, FIXED_TODAY.isoformat(), None))

    def test_date_warning_shows_in_panel_and_confirm_resends(self):
        dialog, api = _progress(stage="docs")
        api.error = AppError("Há avisos", error_code="DATE_CONFIRMATION_REQUIRED", details={"warnings": [{"message": "Domingo."}]})
        dialog.submit()
        self.assertFalse(dialog.warning_panel.isHidden())
        self.assertEqual(dialog.warning_panel.label.text(), "Domingo.")
        self.assertIsNone(dialog.result_data)
        self.assertTrue(dialog.register_button.isEnabled())
        api.error = None
        dialog.warning_panel.confirm_button.click()
        self.assertEqual(api.calls[-1][2]["confirm_dates"], True)
        self.assertEqual(api.calls[-1][:2], ("approve_log", 1))
        self.assertIsNotNone(dialog.result_data)

    def test_date_warning_choose_again_keeps_data_and_hides_panel(self):
        dialog, api = _progress(stage="docs")
        dialog.form.note.setText("obs")
        api.error = AppError("Há avisos", error_code="DATE_CONFIRMATION_REQUIRED", details={"warnings": [{"message": "Feriado."}]})
        dialog.submit()
        dialog.warning_panel.choose_button.click()
        self.assertTrue(dialog.warning_panel.isHidden())
        self.assertEqual(dialog.form.note.text(), "obs")
        self.assertEqual(len([c for c in api.calls if c[0] == "approve_log"]), 1)

    def test_stale_stage_reloads_and_keeps_note(self):
        dialog, api = _progress(stage="reservada")
        api.result = _log(stage="docs")
        dialog.form.note.setText("ficou escrito")
        dialog.form.fields["nf_link"].setText(LINKS[0])
        dialog.form.fields["xml_link"].setText(LINKS[1])
        dialog.form.fields["bim_link"].setText(LINKS[2])
        real_send_docs = api.send_docs

        def stale_once(*args, **kwargs):
            api.send_docs = real_send_docs  # so a primeira chamada falha
            raise AppError("O LOG mudou de etapa. Os dados foram atualizados.", error_code="LOGISTICS_INVALID_STAGE")

        api.send_docs = stale_once
        dialog.submit()
        self.assertEqual(api.calls[-1], ("get_log", 1))
        self.assertTrue(dialog.reloaded)
        self.assertEqual(dialog.log["stage"], "docs")
        self.assertEqual(dialog.form.outcome().key, "approve")
        self.assertEqual(dialog.form.note.text(), "ficou escrito")
        self.assertEqual(dialog.error_label.text(), "O LOG mudou de etapa. Os dados foram atualizados.")
        self.assertTrue(dialog.register_button.isEnabled())
        self.assertIn("Documentação enviada", dialog.subtitle.text())

    def test_no_outcome_disables_register(self):
        dialog, _api = _progress(stage="cadastro")
        self.assertFalse(dialog.register_button.isEnabled())

    def test_detail_opens_progress_and_applies_result(self):
        api = FakeLogisticsApi()
        api.result = _log(stage="docs")
        detail = LogDetailDialog(FakeService(api), _log(stage="docs"), can_edit=True)

        def run(progress):
            progress.result_data = _log(stage="aprovada")
            return 1

        button = next(b for b in detail.action_buttons if b.text() == "Registrar andamento")
        with patch.object(dialogs_module.RecordLogProgressDialog, "exec", run):
            button.click()
        self.assertEqual(detail.stage_badge.text(), "Aprovada para entrega")
        self.assertTrue(detail.changed)


class InspectionQuestionTests(QtCase):
    def test_question_lists_pending_proposals_and_confirms(self):
        proposals = [{"proposal_number": "10489/C", "customer_name": "Rede Sul", "inspection_stage": "nqt"}]
        clicks = []

        def exec_and_click(box):
            clicks.append([b.text() for b in box.buttons()])
            next(b for b in box.buttons() if b.text() == "Incluir mesmo assim").click()
            return 0

        class ClickingBox(QMessageBox):
            def exec(self):  # so a caixa deste modulo; QMessageBox.exec global ficaria com o teste inteiro
                return exec_and_click(self)

        with patch.object(dialogs_module, "QMessageBox", ClickingBox):
            self.assertTrue(dialogs_module.ask_inspection_confirmation(None, proposals))
        self.assertIn("Incluir mesmo assim", clicks[0])
        self.assertIn("Cancelar", clicks[0])


if __name__ == "__main__":
    unittest.main()
