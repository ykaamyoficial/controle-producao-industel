"""Desktop: cancelar nota inteira com motivo, corrigir emissao e aba Cancelamentos."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QTabWidget, QTableWidget

from app.integrations.api.proposals_client import ProposalsApiClient
from app.services.api_proposal_storage import OfficialProposalApiStorage, _api_fiscal_invoice_to_legacy
from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES, AppError
from app.ui.action_center.descriptor import ActionCategory
from app.ui.action_center.fiscal_action_center import FiscalActionCenter
from app.ui.fiscal_invoice_cancel_dialog import FiscalInvoiceCancelDialog
from app.ui.fiscal_invoice_common import fiscal_error_message
from app.ui.fiscal_invoice_correction_dialog import FiscalInvoiceCorrectionDialog
from app.ui.fiscal_page import FiscalPage, FiscalProposalDetailDialog

ROW = {"fiscal_processo_id": 60, "proposta": "CP00060", "cliente": "ACME", "situacao_fiscal": "NF_PARCIAL"}


def sync_worker(_owner, operation, on_success, on_error, *, operation_name=None):
    try:
        result = operation()
    except Exception as exc:  # noqa: BLE001 - espelha o Worker real
        on_error(exc)
    else:
        on_success(result)


def invoice(invoice_id, number, lines, *, series="1", status="ATIVA", issued="2026-11-05T10:30:00Z", **extra):
    return {
        "id": invoice_id, "numero_controle": number, "serie": series, "status": status,
        "data_emissao": "05/11/2026 10:30:00", "data_emissao_iso": issued, "observacao": "obs",
        "quantidade_itens": len(lines), "quantidade_emitida": sum(float(line["quantity"]) for line in lines),
        "peso_emitido": "10", "itens": lines, **extra,
    }


def line(fiscal_item_id, quantity, *, weight="10", active=True):
    return {
        "id": fiscal_item_id * 10, "fiscal_item_id": fiscal_item_id, "item_number": str(fiscal_item_id),
        "quantity": quantity, "weight": weight, "active": active,
    }


def fiscal_item(item_id, total, pending, *, weight_pending="0", weight_billed="0"):
    return {
        "id": item_id, "numero_item": str(item_id), "codigo_produto": "X", "descricao": "Parafuso",
        "quantidade_total": total, "quantidade_faturada": "0", "quantidade_pendente": pending,
        "peso_total": "100", "peso_faturado": weight_billed, "peso_pendente": weight_pending,
    }


class FakeFiscalService:
    palette = OFFICIAL_COLOR_PALETTES["claro"]

    def __init__(self, invoices=None, items=None, cancelled=None):
        self.invoices = invoices if invoices is not None else []
        self.items = items if items is not None else []
        self.cancelled = cancelled if cancelled is not None else []
        self.calls = []
        self.error = None
        self.cancellations_payload = {"items": [], "total": 0}
        self.register_allowed = True
        self.cancel_allowed = True

    def can_register_fiscal_emission(self):
        return self.register_allowed

    def can_cancel_fiscal_emission(self):
        return self.cancel_allowed

    def fiscal_status_label(self, value):
        return value

    def fiscal_items(self, _fiscal_id):
        return [dict(item) for item in self.items]

    def fiscal_emissions(self, _fiscal_id):
        return [dict(item) for item in self.invoices]

    def fiscal_cancelled_invoices(self, _fiscal_id):
        return [dict(item) for item in self.cancelled]

    def fiscal_movements(self, _fiscal_id):
        return []

    def cancel_fiscal_invoice(self, fiscal_id, invoice_id, reason):
        self.calls.append(("cancel", fiscal_id, invoice_id, reason))
        if self.error:
            raise self.error
        return {"id": invoice_id, "status": "CANCELADA"}

    def correct_fiscal_invoice(self, fiscal_id, invoice_id, data):
        self.calls.append(("correct", fiscal_id, invoice_id, data))
        if self.error:
            raise self.error
        return {"id": invoice_id}

    def fiscal_cancellations(self, search, limit, offset):
        self.calls.append(("cancellations", search, limit, offset))
        return self.cancellations_payload


class QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])


class ErrorMappingTests(unittest.TestCase):
    def test_each_new_fiscal_code_has_its_own_message(self):
        codes = [
            "FISCAL_INVOICE_DUPLICATED", "FISCAL_INVOICE_NOT_FOUND", "FISCAL_INVOICE_ALREADY_CANCELLED",
            "FISCAL_INVOICE_WITHDRAWN", "FISCAL_INVOICE_CORRECTION_INVALID", "FISCAL_VERSION_CONFLICT",
            "FISCAL_QUANTITY_EXCEEDED",
        ]
        messages = set()
        for code in codes:
            message = FiscalPage._fiscal_error_message(AppError("tecnico", error_code=code))
            self.assertNotEqual(message, "tecnico", code)
            messages.add(message)
        self.assertEqual(len(messages), len(codes))
        self.assertEqual(fiscal_error_message(AppError("tecnico", error_code="OUTRO")), "tecnico")


class StorageTests(unittest.TestCase):
    def _storage(self, proposals):
        storage = OfficialProposalApiStorage.__new__(OfficialProposalApiStorage)
        client = MagicMock()
        storage._client = lambda: (client, proposals, "tok")
        return storage, client

    def test_cancelled_invoice_keeps_status_reason_author_and_date(self):
        legacy = _api_fiscal_invoice_to_legacy({
            "id": 7, "invoice_number": "123", "series": "1", "status": "CANCELADA",
            "issued_at": "2026-11-05T10:30:00Z", "cancelled_at": "2026-11-06T09:00:00Z",
            "cancelled_by_name": "Maria", "cancel_reason": "NF errada", "items": [{"fiscal_item_id": 1}],
        })
        self.assertEqual(legacy["status"], "CANCELADA")
        self.assertEqual(legacy["cancelado_por"], "Maria")
        self.assertEqual(legacy["motivo_cancelamento"], "NF errada")
        self.assertEqual(legacy["cancelado_em"], "06/11/2026 09:00:00")
        self.assertEqual(legacy["data_emissao_iso"], "2026-11-05T10:30:00Z")
        active = _api_fiscal_invoice_to_legacy({"id": 8, "invoice_number": "9", "status": "ATIVA"})
        self.assertEqual(active["cancelado_em"], "")
        self.assertEqual(active["motivo_cancelamento"], "")

    def test_cancel_invoice_sends_record_version_and_returns_cancelled_invoice(self):
        proposals = MagicMock()
        proposals.get_fiscal_record.return_value = {"version": 5}
        proposals.cancel_invoice.return_value = {
            "invoices": [], "cancelled_invoices": [{"id": 7, "invoice_number": "123", "status": "CANCELADA", "cancel_reason": "x"}],
        }
        storage, client = self._storage(proposals)
        result = storage.cancel_fiscal_invoice(60, 7, "x")
        proposals.cancel_invoice.assert_called_once_with("tok", 7, 5, "x")
        self.assertEqual(result["status"], "CANCELADA")
        client.close.assert_called_once()

    def test_correct_invoice_payload_follows_contract(self):
        proposals = MagicMock()
        proposals.get_fiscal_record.return_value = {"version": 5}
        proposals.correct_invoice.return_value = {"invoices": [{"id": 7, "invoice_number": "124"}]}
        storage, _client = self._storage(proposals)
        result = storage.correct_fiscal_invoice(60, 7, {
            "numero_controle": " 124 ", "serie": "", "data_emissao": None, "observacao": " ",
            "emissions": [{"fiscal_item_id": 1, "quantidade_emitida": 3, "peso_emitido": 1.5}],
        })
        proposals.correct_invoice.assert_called_once_with("tok", 7, {
            "version": 5, "invoice_number": "124", "series": None, "issued_at": None, "observation": None,
            "items": [{"fiscal_item_id": 1, "quantity": "3", "weight": "1.5"}],
        })
        self.assertEqual(result["numero_controle"], "124")

    def test_old_cancel_is_one_atomic_call_per_invoice_not_per_line(self):
        proposals = MagicMock()
        proposals.get_fiscal_record.return_value = {"version": 5, "invoices": [{
            "id": 7, "status": "ATIVA", "items": [{"id": 1, "active": True}, {"id": 2, "active": True}, {"id": 3, "active": False}],
        }]}
        storage, _client = self._storage(proposals)
        self.assertEqual(storage.cancel_latest_fiscal_emission(60, ""), 2)
        proposals.cancel_invoice.assert_called_once_with("tok", 7, 5, "Cancelamento interno pelo Desktop")
        proposals.cancel_fiscal_invoice_item.assert_not_called()

    def test_cancellations_page_is_mapped(self):
        proposals = MagicMock()
        proposals.list_cancellations.return_value = {"total": 1, "items": [{
            "invoice_id": 7, "fiscal_record_id": 60, "proposal_id": 10, "proposal_number": "CP1", "customer_name": "ACME",
            "invoice_number": "123", "series": "1", "issued_at": "2026-11-05T10:30:00Z", "item_count": 1, "quantity": "2",
            "weight": "5", "items": [{"item_number": "1", "quantity": "2"}], "cancelled_by_name": "Maria",
            "cancelled_at": "2026-11-06T09:00:00Z", "cancel_reason": "errada", "emission_type": "TOTAL",
        }]}
        storage, _client = self._storage(proposals)
        page = storage.fiscal_cancellations(" CP1 ", 50, 100)
        proposals.list_cancellations.assert_called_once_with("tok", search="CP1", limit=50, offset=100)
        row = page["items"][0]
        self.assertEqual((page["total"], row["proposta"], row["numero_controle"], row["motivo_cancelamento"]), (1, "CP1", "123", "errada"))
        self.assertEqual(row["fiscal_processo_id"], 60)

    def test_api_client_uses_contract_paths_and_body(self):
        client = MagicMock()
        api = ProposalsApiClient(client)
        api.cancel_invoice("tok", 7, 5, "motivo")
        client.post.assert_called_with("/api/v1/fiscal/invoices/7/cancel", json_payload={"version": 5, "reason": "motivo"}, access_token="tok")
        api.correct_invoice("tok", 7, {"version": 5})
        client.post.assert_called_with("/api/v1/fiscal/invoices/7/correct", json_payload={"version": 5}, access_token="tok")
        api.list_cancellations("tok", search="a b", limit=50, offset=0)
        client.get.assert_called_with("/api/v1/fiscal/cancellations?search=a+b&limit=50&offset=0", access_token="tok")


class CancelDialogTests(QtCase):
    def _dialog(self, invoices, service=None):
        service = service or FakeFiscalService(invoices)
        return FiscalInvoiceCancelDialog(service, ROW, invoices), service

    def test_confirm_stays_disabled_until_note_and_reason_are_given(self):
        dialog, _service = self._dialog([invoice(1, "111", [line(1, "2")]), invoice(2, "222", [line(2, "1")])])
        self.assertFalse(dialog.confirm_button.isEnabled())
        dialog.invoice_list.setCurrentRow(1)
        self.assertFalse(dialog.confirm_button.isEnabled())
        dialog.reason.setPlainText("   ")
        self.assertFalse(dialog.confirm_button.isEnabled())
        dialog.reason.setPlainText("NF emitida errada")
        self.assertTrue(dialog.confirm_button.isEnabled())
        dialog.reason.setPlainText("x" * 1001)
        self.assertFalse(dialog.confirm_button.isEnabled())

    def test_single_note_is_preselected_and_cancelled_ones_are_not_listed(self):
        dialog, _service = self._dialog([invoice(1, "111", [line(1, "2")]), invoice(2, "222", [], status="CANCELADA")])
        self.assertEqual(dialog.invoice_list.count(), 1)
        self.assertEqual(dialog.selected_invoice_id(), 1)

    def test_confirm_cancels_the_chosen_note_with_trimmed_reason(self):
        dialog, service = self._dialog([invoice(1, "111", [line(1, "2")]), invoice(2, "222", [line(2, "1")])])
        dialog.invoice_list.setCurrentRow(1)
        dialog.reason.setPlainText("  NF errada  ")
        with patch("app.ui.fiscal_invoice_cancel_dialog.start_worker", sync_worker):
            dialog.confirm()
        self.assertEqual(service.calls, [("cancel", 60, 2, "NF errada")])
        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertEqual(dialog.cancelled_invoice["status"], "CANCELADA")

    def test_confirm_without_reason_does_not_call_service(self):
        dialog, service = self._dialog([invoice(1, "111", [line(1, "2")])])
        with patch("app.ui.fiscal_invoice_cancel_dialog.start_worker", sync_worker):
            dialog.confirm()
        self.assertEqual(service.calls, [])

    def test_api_error_shows_mapped_message_and_keeps_dialog_open(self):
        dialog, service = self._dialog([invoice(1, "111", [line(1, "2")])])
        service.error = AppError("tecnico", error_code="FISCAL_INVOICE_ALREADY_CANCELLED")
        dialog.reason.setPlainText("motivo")
        with patch("app.ui.fiscal_invoice_cancel_dialog.start_worker", sync_worker), \
                patch("app.ui.fiscal_invoice_cancel_dialog.QMessageBox.warning") as warning:
            dialog.confirm()
        warning.assert_called_once()
        self.assertIn("já foi cancelada", warning.call_args.args[2])
        self.assertNotEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertTrue(dialog.confirm_button.isEnabled())


class CorrectionDialogTests(QtCase):
    def _dialog(self, invoices, items, service=None):
        service = service or FakeFiscalService(invoices, items)
        return FiscalInvoiceCorrectionDialog(service, ROW, invoices), service

    def test_form_is_prefilled_with_the_chosen_note_and_balance_includes_its_own_lines(self):
        note = invoice(7, "123", [line(1, "4", weight="40")], series="2")
        dialog, _service = self._dialog([note], [fiscal_item(1, "10", "6", weight_pending="60", weight_billed="40"), fiscal_item(2, "5", "5", weight_pending="50")])
        self.assertEqual(dialog.control_number.text(), "123")
        self.assertEqual(dialog.series.text(), "2")
        self.assertEqual(dialog.observation.toPlainText(), "obs")
        self.assertEqual(dialog.issue_date.date(), QDate(2026, 11, 5))
        self.assertEqual(dialog.selection_items[1].checkState(), Qt.Checked)
        self.assertEqual(dialog.selection_items[2].checkState(), Qt.Unchecked)
        self.assertEqual(dialog.quantity_inputs[1].value(), 4)
        self.assertEqual(dialog.quantity_inputs[1].maximum(), 10)
        self.assertFalse(dialog.invoice_picker.isVisibleTo(dialog))

    def test_confirm_sends_changed_number_series_items_and_keeps_original_date(self):
        note = invoice(7, "123", [line(1, "4", weight="40")])
        dialog, service = self._dialog([note], [fiscal_item(1, "10", "6", weight_pending="60", weight_billed="40"), fiscal_item(2, "5", "5", weight_pending="50")])
        dialog.control_number.setText("124")
        dialog.series.setText("3")
        dialog.quantity_inputs[1].setValue(5)
        dialog.selection_items[2].setCheckState(Qt.Checked)
        dialog.quantity_inputs[2].setValue(2)
        with patch("app.ui.fiscal_invoice_correction_dialog.start_worker", sync_worker):
            dialog.confirm()
        kind, fiscal_id, invoice_id, data = service.calls[0]
        self.assertEqual((kind, fiscal_id, invoice_id), ("correct", 60, 7))
        self.assertEqual((data["numero_controle"], data["serie"], data["data_emissao"], data["observacao"]), ("124", "3", None, "obs"))
        by_item = {row["fiscal_item_id"]: row for row in data["emissions"]}
        self.assertEqual(by_item[1]["quantidade_emitida"], 5)
        self.assertAlmostEqual(by_item[1]["peso_emitido"], 50.0)
        self.assertEqual(by_item[2]["quantidade_emitida"], 2)
        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)

    def test_changed_date_is_sent_as_midnight_utc(self):
        dialog, service = self._dialog([invoice(7, "123", [line(1, "4")])], [fiscal_item(1, "10", "6", weight_pending="60", weight_billed="10")])
        dialog.issue_date.setDate(QDate(2026, 11, 1))
        with patch("app.ui.fiscal_invoice_correction_dialog.start_worker", sync_worker):
            dialog.confirm()
        self.assertEqual(service.calls[0][3]["data_emissao"], "2026-11-01T00:00:00Z")

    def test_blank_number_or_no_items_blocks_submit_without_calling_service(self):
        dialog, service = self._dialog([invoice(7, "123", [line(1, "4")])], [fiscal_item(1, "10", "6", weight_pending="60", weight_billed="10")])
        with patch("app.ui.fiscal_invoice_correction_dialog.start_worker", sync_worker), \
                patch("app.ui.fiscal_invoice_correction_dialog.QMessageBox.warning") as warning:
            dialog.control_number.setText("  ")
            dialog.confirm()
            dialog.control_number.setText("123")
            dialog.clear_selection()
            dialog.confirm()
        self.assertEqual(warning.call_count, 2)
        self.assertEqual(service.calls, [])

    def test_fractional_line_is_preserved_untouched(self):
        note = invoice(7, "123", [line(1, "1.5", weight="15")])
        dialog, service = self._dialog([note], [fiscal_item(1, "10", "8.5", weight_pending="85", weight_billed="15")])
        self.assertFalse(dialog.quantity_inputs[1].isEnabled())
        self.assertEqual(dialog.quantity_inputs[1].text(), "1.5")
        with patch("app.ui.fiscal_invoice_correction_dialog.start_worker", sync_worker):
            dialog.confirm()
        self.assertEqual(service.calls[0][3]["emissions"], [{"fiscal_item_id": 1, "quantidade_emitida": "1.5", "peso_emitido": "15"}])

    def test_choosing_another_note_reloads_the_form(self):
        notes = [invoice(7, "123", [line(1, "4")]), invoice(8, "456", [line(2, "2")], series="9")]
        dialog, _service = self._dialog(notes, [fiscal_item(1, "10", "6", weight_pending="60", weight_billed="10"), fiscal_item(2, "5", "3", weight_pending="30", weight_billed="20")])
        self.assertTrue(dialog.invoice_picker.isVisibleTo(dialog))
        dialog.invoice_picker.setCurrentIndex(1)
        self.assertEqual(dialog.control_number.text(), "456")
        self.assertEqual(dialog.series.text(), "9")
        self.assertEqual(dialog.selection_items[1].checkState(), Qt.Unchecked)
        self.assertEqual(dialog.selection_items[2].checkState(), Qt.Checked)
        self.assertEqual(dialog.quantity_inputs[2].value(), 2)

    def test_api_error_is_mapped_and_dialog_stays_open(self):
        dialog, service = self._dialog([invoice(7, "123", [line(1, "4")])], [fiscal_item(1, "10", "6", weight_pending="60", weight_billed="10")])
        service.error = AppError("tecnico", error_code="FISCAL_INVOICE_DUPLICATED")
        with patch("app.ui.fiscal_invoice_correction_dialog.start_worker", sync_worker), \
                patch("app.ui.fiscal_invoice_correction_dialog.QMessageBox.warning") as warning:
            dialog.confirm()
        self.assertIn("Já existe outra nota", warning.call_args.args[2])
        self.assertNotEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertTrue(dialog.confirm_button.isEnabled())


class ActionCenterTests(QtCase):
    def _ids(self, service, row=ROW):
        center = FiscalActionCenter(service, row, {})
        return {action.id: action for action in center._descriptors()}

    def test_cancel_is_destructive_and_correct_is_attention_when_there_is_an_active_note(self):
        actions = self._ids(FakeFiscalService([invoice(1, "111", [line(1, "2")])]))
        self.assertEqual(actions["CANCEL_FISCAL_EMISSION"].category, ActionCategory.DESTRUCTIVE)
        self.assertEqual(actions["CORRECT_FISCAL_EMISSION"].label, "Corrigir emissão fiscal")
        self.assertEqual(actions["CORRECT_FISCAL_EMISSION"].category, ActionCategory.ATTENTION)
        self.assertEqual(actions["REGISTER_FISCAL_EMISSION"].category, ActionCategory.PRIMARY)

    def test_no_active_note_offers_neither_cancel_nor_correct(self):
        actions = self._ids(FakeFiscalService([]))
        self.assertNotIn("CANCEL_FISCAL_EMISSION", actions)
        self.assertNotIn("CORRECT_FISCAL_EMISSION", actions)

    def test_withdrawn_note_cannot_be_corrected_but_can_be_cancelled(self):
        actions = self._ids(FakeFiscalService([invoice(1, "111", [line(1, "2")])]), {**ROW, "situacao_fiscal": "NF_RETIRADA_CLIENTE"})
        self.assertNotIn("CORRECT_FISCAL_EMISSION", actions)
        self.assertIn("CANCEL_FISCAL_EMISSION", actions)

    def test_permissions_hide_the_actions(self):
        service = FakeFiscalService([invoice(1, "111", [line(1, "2")])])
        service.register_allowed = False
        service.cancel_allowed = False
        actions = self._ids(service)
        self.assertNotIn("CANCEL_FISCAL_EMISSION", actions)
        self.assertNotIn("CORRECT_FISCAL_EMISSION", actions)

    def test_card_runs_the_registered_handler(self):
        handler = MagicMock(return_value=True)
        service = FakeFiscalService([invoice(1, "111", [line(1, "2")])])
        center = FiscalActionCenter(service, ROW, {"CANCEL_FISCAL_EMISSION": handler})
        center._run(next(a for a in center._descriptors() if a.id == "CANCEL_FISCAL_EMISSION"))
        handler.assert_called_once()
        self.assertEqual(center.result(), center.DialogCode.Accepted)


class PageTests(QtCase):
    def _page(self, service=None):
        return FiscalPage(service or FakeFiscalService())

    def test_cancellations_tab_sits_next_to_withdrawn_and_reports(self):
        page = self._page()
        titles = [page.tabs.tabText(i) for i in range(page.tabs.count())]
        self.assertEqual(titles[1:4], ["Notas fiscais retiradas", "Cancelamentos", "Relatórios fiscais"])

    def test_cancellations_tab_lists_reason_author_and_items_with_paging(self):
        service = FakeFiscalService()
        service.cancellations_payload = {"total": 120, "items": [invoice(
            7, "123", [line(1, "2"), line(2, "3")], status="CANCELADA", proposta="CP1", cliente="ACME",
            cancelado_por="Maria", cancelado_em="06/11/2026 09:00:00", motivo_cancelamento="NF errada",
        )]}
        page = self._page(service)
        with patch("app.ui.fiscal_page.start_worker", sync_worker), patch("app.ui.fiscal_page.show_operation_error"):
            page.tabs.setCurrentWidget(page.cancellations_tab)
            self.assertEqual(service.calls[-1], ("cancellations", "", 50, 0))
            model = page.cancellations_model
            values = {key: model.index(0, col).data() for col, (key, _label) in enumerate(model.columns)}
            self.assertEqual(values["motivo_cancelamento"], "NF errada")
            self.assertEqual(values["cancelado_por"], "Maria")
            self.assertEqual(values["itens_resumo"], "1: 2, 2: 3")
            self.assertIn("Página 1 de 3", page.cancellations_status.text())
            self.assertFalse(page.cancellations_prev_btn.isEnabled())
            self.assertTrue(page.cancellations_next_btn.isEnabled())

            page.cancellations_search.setText(" CP1 ")
            page.change_cancellations_page(1)
            self.assertEqual(service.calls[-1], ("cancellations", "CP1", 50, 50))
            page.search_cancellations()
            self.assertEqual(service.calls[-1], ("cancellations", "CP1", 50, 0))

    def test_empty_cancellations_show_message(self):
        page = self._page()
        with patch("app.ui.fiscal_page.start_worker", sync_worker), patch("app.ui.fiscal_page.show_operation_error"):
            page.refresh_cancellations()
        self.assertEqual(page.cancellations_status.text(), "Nenhuma nota cancelada encontrada.")
        self.assertFalse(page.cancellations_next_btn.isEnabled())

    def test_cancel_emission_opens_dialog_and_refreshes_without_real_message_box(self):
        service = FakeFiscalService([invoice(1, "111", [line(1, "2")])])
        page = self._page(service)
        page.refresh = MagicMock()
        page.refresh_cancellations = MagicMock()
        with patch("app.ui.fiscal_page.FiscalInvoiceCancelDialog") as dialog_cls, \
                patch("app.ui.fiscal_page.QMessageBox.information") as info:
            dialog_cls.return_value.exec.return_value = 1
            self.assertTrue(page.cancel_emission(ROW))
        dialog_cls.assert_called_once()
        self.assertEqual(dialog_cls.call_args.args[2], service.invoices)
        page.refresh.assert_called_once()
        page.refresh_cancellations.assert_called_once()
        info.assert_called_once()

    def test_cancel_emission_without_active_note_warns_instead_of_opening_dialog(self):
        page = self._page(FakeFiscalService([]))
        with patch("app.ui.fiscal_page.FiscalInvoiceCancelDialog") as dialog_cls, \
                patch("app.ui.fiscal_page.QMessageBox.information") as info:
            self.assertFalse(page.cancel_emission(ROW))
        dialog_cls.assert_not_called()
        info.assert_called_once()

    def test_correct_emission_opens_correction_dialog(self):
        service = FakeFiscalService([invoice(1, "111", [line(1, "2")])])
        page = self._page(service)
        page.refresh = MagicMock()
        with patch("app.ui.fiscal_page.FiscalInvoiceCorrectionDialog") as dialog_cls, \
                patch("app.ui.fiscal_page.QMessageBox.information"):
            dialog_cls.return_value.exec.return_value = 0
            self.assertFalse(page.correct_emission(ROW))
            dialog_cls.return_value.exec.return_value = 1
            self.assertTrue(page.correct_emission(ROW))
        page.refresh.assert_called_once()


class DetailDialogTests(QtCase):
    def _tabs(self, service):
        dialog = FiscalProposalDetailDialog(service, ROW)
        return dialog, dialog.findChild(QTabWidget)

    def test_cancelled_notes_get_their_own_tab_and_stay_out_of_emissions(self):
        cancelled = invoice(
            9, "999", [line(1, "2", active=False)], status="CANCELADA",
            cancelado_por="Maria", cancelado_em="06/11/2026 09:00:00", motivo_cancelamento="NF errada",
        )
        service = FakeFiscalService([invoice(1, "111", [line(1, "2")])], [fiscal_item(1, "5", "3")], [cancelled])
        dialog, tabs = self._tabs(service)
        titles = [tabs.tabText(i) for i in range(tabs.count())]
        self.assertIn("Cancelamento (1)", titles)
        self.assertLess(titles.index("Emissões"), titles.index("Cancelamento (1)"))
        self.assertEqual(len(dialog.emissions), 1)
        self.assertEqual(dialog.emissions[0]["numero_controle"], "111")
        table = tabs.widget(titles.index("Cancelamento (1)")).findChild(QTableWidget)
        texts = [table.item(0, c).text() for c in range(table.columnCount())]
        self.assertIn("999", texts)
        self.assertIn("NF errada", texts)
        self.assertIn("Maria", texts)
        self.assertIn("1: 2", texts)

    def test_no_cancellation_tab_when_nothing_was_cancelled(self):
        _dialog, tabs = self._tabs(FakeFiscalService([invoice(1, "111", [line(1, "2")])], [fiscal_item(1, "5", "3")]))
        self.assertFalse([tabs.tabText(i) for i in range(tabs.count()) if tabs.tabText(i).startswith("Cancelamento")])


if __name__ == "__main__":
    unittest.main()
