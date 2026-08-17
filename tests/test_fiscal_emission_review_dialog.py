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


if __name__ == "__main__":
    unittest.main()
