from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.integrations.api.exceptions import ApiBusinessError
from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui import warehouse_enter_dialog as dialog_module
from app.ui.components.modern_button import ModernButton
from app.ui.process_page import ProcessPage
from app.ui.warehouse_enter_dialog import MAX_NUMBERS, WarehouseEnterDialog, parse_proposal_numbers
from test_visual_pages import FakeService as ProposalService


def _sync_worker(owner, operation, on_success, on_error, *, operation_name=None):
    try:
        result = operation()
    except Exception as exc:  # noqa: BLE001 - igual ao worker real: o erro vai para on_error
        on_error(exc)
    else:
        on_success(result)


def _result(number, result="ENTROU", message="ok", proposal_id=1):
    return {"number": number, "result": result, "proposal_id": proposal_id, "message": message}


class ParserTests(unittest.TestCase):
    def test_splits_on_comma_semicolon_space_tab_and_newlines(self):
        self.assertEqual(parse_proposal_numbers("A1, B2;C3 D4\tE5\nF6\r\nG7"), ["A1", "B2", "C3", "D4", "E5", "F6", "G7"])

    def test_drops_empties_and_repeats_ignoring_case_keeping_the_first_and_the_order(self):
        self.assertEqual(parse_proposal_numbers(",, cp1 ,\n\nCP2;; CP1 cp2 CP3"), ["cp1", "CP2", "CP3"])
        self.assertEqual(parse_proposal_numbers("   \n ,; "), [])
        self.assertEqual(parse_proposal_numbers(""), [])

    def test_strips_straight_and_curly_quotes_and_trailing_punctuation(self):
        # Foco de revisao 5: a API so faz trim, entao `"E-1"` e `E-1.` virariam NAO_ENCONTRADA.
        self.assertEqual(parse_proposal_numbers('"E-1", “E-2” ‘E-3’ \'E-4\' E-5. E-6.; «E-7»'), ["E-1", "E-2", "E-3", "E-4", "E-5", "E-6", "E-7"])
        self.assertEqual(parse_proposal_numbers('"E-1".'), ["E-1"])
        self.assertEqual(parse_proposal_numbers('"", ".", ";"'), [])

    def test_non_breaking_space_separates_and_is_never_part_of_the_number(self):
        self.assertEqual(parse_proposal_numbers("CP1 CP2  CP3​"), ["CP1", "CP2", "CP3"])

    def test_quote_after_dedup_still_matches_the_clean_form(self):
        self.assertEqual(parse_proposal_numbers('CP1 "CP1" CP1.'), ["CP1"])


class FakeService(ProposalService):
    def __init__(self, results=None, error=None):
        super().__init__(["EM_SEPARACAO"])
        self.palette = OFFICIAL_COLOR_PALETTES["claro"]
        self.results = results
        self.error = error
        self.calls: list[list[str]] = []

    def warehouse_enter(self, numbers):
        self.calls.append(list(numbers))
        if self.error is not None:
            raise self.error
        return self.results if self.results is not None else [_result(n) for n in numbers]

    def can_edit_area(self, area):
        return area != "BLOQUEADA"


class QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        patcher = patch.object(dialog_module, "start_worker", _sync_worker)
        patcher.start()
        self.addCleanup(patcher.stop)


class DialogTests(QtCase):
    def _dialog(self, service=None):
        service = service or FakeService()
        dialog = WarehouseEnterDialog(service)
        self.addCleanup(dialog.deleteLater)
        return dialog, service

    def test_add_is_the_only_primary_button_and_starts_disabled(self):
        dialog, _ = self._dialog()
        primaries = [b.text() for b in dialog.findChildren(ModernButton) if b.variant() == "primary"]
        self.assertEqual(primaries, ["Adicionar"])
        self.assertFalse(dialog.add_button.isEnabled())
        dialog.numbers_edit.setPlainText("CP1")
        self.assertTrue(dialog.add_button.isEnabled())
        self.assertEqual(dialog.counter_label.text(), "1 número.")

    def test_submit_sends_the_cleaned_list_and_shows_one_row_per_number(self):
        service = FakeService(results=[
            _result("CP1"), _result("CP2", "JA_NA_ABA", "ja esta"), _result("CP3", "NAO_ENCONTRADA", "nao existe", None),
        ])
        dialog, _ = self._dialog(service)
        dialog.numbers_edit.setPlainText('"CP1", cp1\nCP2; CP3.')
        dialog.submit()
        self.assertEqual(service.calls, [["CP1", "CP2", "CP3"]])
        table = dialog.results_table
        self.assertEqual(table.rowCount(), 3)
        self.assertEqual([table.item(row, 0).text() for row in range(3)], ["CP1", "CP2", "CP3"])
        self.assertEqual([table.item(row, 2).text() for row in range(3)], ["ok", "ja esta", "nao existe"])
        badges = [table.cellWidget(row, 1).findChild(dialog_module.QLabel).text() for row in range(3)]
        self.assertEqual(badges, ["Entrou", "Já estava na aba", "Não encontrada"])
        self.assertIn("1 proposta entrou", dialog.summary_label.text())
        self.assertIn("2 não entraram", dialog.summary_label.text())
        self.assertTrue(dialog.changed)

    def test_nothing_entered_does_not_flag_a_reload(self):
        service = FakeService(results=[_result("CP1", "JA_ENTREGUE", "entregue"), _result("CP2", "CANCELADA", "cancelada")])
        dialog, _ = self._dialog(service)
        dialog.numbers_edit.setPlainText("CP1 CP2")
        dialog.submit()
        self.assertFalse(dialog.changed)

    def test_every_api_result_has_a_badge(self):
        for result in ("ENTROU", "JA_NA_ABA", "JA_ENTREGUE", "NAO_ENCONTRADA", "CANCELADA", "PROPOSTA_PARCIAL"):
            self.assertIn(result, dialog_module.RESULT_BADGES)

    def test_add_stays_off_until_the_text_changes(self):
        dialog, _service = self._dialog()
        dialog.numbers_edit.setPlainText("CP1")
        dialog.submit()
        self.assertFalse(dialog.add_button.isEnabled())
        dialog.numbers_edit.setPlainText("CP1 CP2")
        self.assertTrue(dialog.add_button.isEnabled())

    def test_more_than_the_limit_is_blocked_without_calling_the_api(self):
        dialog, service = self._dialog()
        dialog.numbers_edit.setPlainText(" ".join(f"CP{n:05d}" for n in range(MAX_NUMBERS + 1)))
        self.assertFalse(dialog.add_button.isEnabled())
        self.assertFalse(dialog.notice_label.isHidden())
        self.assertIn(str(MAX_NUMBERS), dialog.notice_label.text())
        dialog.submit()
        self.assertEqual(service.calls, [])
        self.assertFalse(dialog.numbers_edit.property("validationState") == "")
        # Exatamente no limite passa; repetidos nao contam.
        dialog.numbers_edit.setPlainText(" ".join(f"CP{n:05d}" for n in range(MAX_NUMBERS)) + " cp00000")
        self.assertTrue(dialog.add_button.isEnabled())
        self.assertTrue(dialog.notice_label.isHidden())

    def test_api_error_is_shown_inline_and_keeps_the_text_for_a_new_try(self):
        service = FakeService(error=ApiBusinessError("VALIDATION_ERROR", "Lista invalida", status_code=422))
        dialog, _ = self._dialog(service)
        dialog.numbers_edit.setPlainText("CP1")
        dialog.submit()
        self.assertFalse(hasattr(dialog_module, "QMessageBox"))  # erro sempre em linha, nunca modal
        self.assertFalse(dialog.notice_label.isHidden())
        self.assertEqual(dialog.numbers_edit.toPlainText(), "CP1")
        self.assertTrue(dialog.add_button.isEnabled())
        self.assertFalse(dialog.changed)

    def test_does_not_resubmit_while_running(self):
        dialog, service = self._dialog()
        dialog.numbers_edit.setPlainText("CP1")
        dialog._running = True
        dialog.submit()
        self.assertEqual(service.calls, [])


class ProcessPageButtonTests(QtCase):
    def _page(self, area, editable=True):
        service = FakeService()
        service.can_edit_area = lambda _area: editable
        page = ProcessPage(service, area, area.title())
        self.addCleanup(page.deleteLater)
        return page

    def test_button_only_in_warehouse_with_permission(self):
        warehouse = self._page("ALMOXARIFADO")
        self.assertFalse(warehouse.add_proposals_button.isHidden())
        self.assertIsNotNone(warehouse.add_proposals_button.parentWidget())
        self.assertEqual(warehouse.add_proposals_button.variant(), "secondary")
        self.assertIsNone(self._page("PRODUCAO").add_proposals_button.parentWidget())
        self.assertIsNone(self._page("ALMOXARIFADO", editable=False).add_proposals_button.parentWidget())

    def test_button_is_hidden_in_batch_mode_and_comes_back(self):
        page = self._page("ALMOXARIFADO")
        page.activate_batch_selection()
        self.assertTrue(page.add_proposals_button.isHidden())
        page.cancel_batch_selection()
        self.assertFalse(page.add_proposals_button.isHidden())

    def test_reload_only_when_something_entered(self):
        page = self._page("ALMOXARIFADO")
        page.refresh = MagicMock()
        with patch("app.ui.process_page.WarehouseEnterDialog") as dialog_class:
            dialog_class.return_value.changed = False
            page.open_warehouse_enter()
            page.refresh.assert_not_called()
            dialog_class.return_value.changed = True
            page.open_warehouse_enter()
            page.refresh.assert_called_once()
        self.assertEqual(dialog_class.call_args.args[0], page.service)

    def test_without_permission_the_dialog_does_not_open(self):
        page = self._page("ALMOXARIFADO", editable=False)
        with patch("app.ui.process_page.WarehouseEnterDialog") as dialog_class, patch("app.ui.process_page.ToastNotification"):
            page.open_warehouse_enter()
        dialog_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()
