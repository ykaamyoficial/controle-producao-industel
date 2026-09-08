from __future__ import annotations

import unittest

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QLineEdit

from app.ui.fiscal_emission_draft_dialog import FiscalEmissionDraftDialog


class FiscalDraftService:
    pass


class FiscalEmissionDraftDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, drafts=None):
        selection = {
            "proposals": [
                {"proposal_id": 10, "selection_type": "TOTAL", "items": [{"item_id": 101, "pending_quantity": "5", "pending_weight": "10"}]},
                {"proposal_id": 20, "selection_type": "PARCIAL", "items": [{"item_id": 201, "pending_quantity": "3", "pending_weight": None}]},
            ]
        }
        rows = [
            {"fiscal_processo_id": 10, "proposta": "CP00010", "cliente": "Cliente A"},
            {"fiscal_processo_id": 20, "proposta": "CP00020", "cliente": "Cliente B"},
        ]
        return FiscalEmissionDraftDialog(FiscalDraftService(), selection, rows, drafts=drafts)

    def test_one_line_per_proposal_preserves_selection_type_and_items(self):
        dialog = self._dialog()
        self.assertEqual(dialog.table.rowCount(), 2)
        self.assertEqual(dialog.table.item(0, 1).text(), "TOTAL")
        self.assertEqual(dialog.table.item(1, 1).text(), "PARCIAL")
        dialog.table.cellWidget(0, 4).setText("NF-10")
        dialog.table.cellWidget(1, 4).setText("NF-20")
        drafts, errors = dialog._collect()
        self.assertFalse(errors)
        self.assertEqual(drafts[0]["items"][0]["item_id"], 101)
        self.assertEqual(drafts[0]["emission_date"], QDate.currentDate().toString("yyyy-MM-dd"))

    def test_apply_date_to_all_and_edit_individual_line(self):
        dialog = self._dialog()
        dialog.default_date.setDate(QDate(2026, 8, 17))
        dialog.table.cellWidget(0, 4).setText("NF-10")
        dialog.table.cellWidget(1, 4).setText("NF-20")
        dialog.apply_date_to_all()
        dialog.table.cellWidget(1, 6).setDate(QDate(2026, 8, 18))
        drafts, errors = dialog._collect()
        self.assertFalse(errors)
        self.assertEqual(drafts[0]["emission_date"], "2026-08-17")
        self.assertEqual(drafts[1]["emission_date"], "2026-08-18")

    def test_nf_is_trimmed_and_drafts_are_only_in_memory(self):
        dialog = self._dialog()
        nf = dialog.table.cellWidget(0, 4)
        self.assertIsInstance(nf, QLineEdit)
        nf.setText("  NF-85421  ")
        dialog.table.cellWidget(1, 4).setText("NF-20")
        drafts, errors = dialog._collect()
        self.assertFalse(errors)
        self.assertEqual(drafts[0]["invoice_number"], "NF-85421")
        self.assertIsNone(dialog.result)

    def test_back_draft_rehydrates_fields(self):
        dialog = self._dialog({10: {"invoice_number": "85421", "series": "1", "emission_date": "2026-08-17", "note": "ok"}})
        self.assertEqual(dialog.table.cellWidget(0, 4).text(), "85421")
        self.assertEqual(dialog.table.cellWidget(0, 5).text(), "1")
        self.assertEqual(dialog.table.cellWidget(0, 6).date(), QDate(2026, 8, 17))


if __name__ == "__main__":
    unittest.main()
