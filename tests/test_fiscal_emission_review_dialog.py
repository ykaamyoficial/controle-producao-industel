from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication

from app.ui.fiscal_emission_review_dialog import FiscalEmissionReviewDialog


class FiscalEmissionReviewDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_review_groups_proposals_and_expands_only_selected_items(self):
        draft = [
            {"proposal_id": 10, "proposal_number": "CP00010", "client_name": "A", "invoice_number": "NF-10", "selection_type": "TOTAL", "items": [{"item_id": 101, "pending_quantity": "5", "pending_weight": "10", "product_code": "A", "description": "Suporte"}]},
            {"proposal_id": 20, "proposal_number": "CP00020", "client_name": "B", "invoice_number": "NF-20", "selection_type": "PARCIAL", "items": [{"item_id": 201, "pending_quantity": "3", "pending_weight": None, "product_code": "B", "description": "Perfil"}]},
        ]
        dialog = FiscalEmissionReviewDialog(draft)
        self.assertEqual(dialog.tree.topLevelItemCount(), 2)
        self.assertEqual(dialog.tree.topLevelItem(0).childCount(), 1)
        self.assertIn("CP00010", dialog.tree.topLevelItem(0).text(0))
        self.assertIn("2 proposta(s)", dialog.summary.text())

    def test_confirm_disables_buttons_before_accepting(self):
        draft = [{"proposal_id": 10, "proposal_number": "CP00010", "invoice_number": "NF-10", "selection_type": "TOTAL", "items": [{"item_id": 101, "pending_quantity": "1"}]}]
        dialog = FiscalEmissionReviewDialog(draft)
        dialog._confirm()
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.assertFalse(dialog.back_button.isEnabled())

    def test_error_message_maps_known_backend_codes(self):
        class FakeError(Exception):
            def __init__(self, error_code):
                super().__init__("mensagem tecnica")
                self.error_code = error_code

        self.assertIn("saldo fiscal", FiscalEmissionReviewDialog._error_message(FakeError("FISCAL_QUANTITY_EXCEEDED")))
        self.assertIn("concluida", FiscalEmissionReviewDialog._error_message(FakeError("FISCAL_INVALID_STATE")))

    def test_error_message_falls_back_to_exception_text_for_unmapped_codes(self):
        """Regression: an exception without a recognized error_code must still
        surface its real message instead of the generic fallback text. This is
        what makes the confirm-batch flow debuggable -- previously any error
        without a mapped code (including AppError instances that lost their
        error_code while being wrapped by BackendService) always displayed the
        same unhelpful "Nao foi possivel concluir a emissao fiscal." message.
        """
        exc = ValueError("Draft fiscal possui item sem identificador.")
        self.assertEqual(FiscalEmissionReviewDialog._error_message(exc), str(exc))

    def test_error_message_uses_generic_fallback_only_when_exception_has_no_text(self):
        class BlankError(Exception):
            def __str__(self):
                return ""

        self.assertEqual(FiscalEmissionReviewDialog._error_message(BlankError()), "Nao foi possivel concluir a emissao fiscal.")


if __name__ == "__main__":
    unittest.main()
