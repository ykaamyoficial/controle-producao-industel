from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from app.ui.fiscal_item_selection_dialog import FiscalItemSelectionDialog


class FakeFiscalSelectionService:
    def __init__(self):
        self.rows = {
            10: {"fiscal_processo_id": 10, "proposta": "CP00010", "cliente": "Cliente A"},
            20: {"fiscal_processo_id": 20, "proposta": "CP00020", "cliente": "Cliente B"},
        }
        self.items = {
            10: [
                {"id": 101, "fiscal_processo_id": 10, "numero_item": "1", "codigo_produto": "A", "descricao": "Suporte", "quantidade_total": "5", "quantidade_faturada": "0", "quantidade_pendente": "5", "peso_total": "10", "peso_pendente": "10", "status_item_fiscal": "PENDENTE"},
                {"id": 102, "fiscal_processo_id": 10, "numero_item": "2", "codigo_produto": "B", "descricao": "Chapa", "quantidade_total": "2", "quantidade_faturada": "2", "quantidade_pendente": "0", "peso_total": "4", "status_item_fiscal": "FATURADO"},
            ],
            20: [
                {"id": 201, "fiscal_processo_id": 20, "numero_item": "1", "codigo_produto": "C", "descricao": "Perfil", "quantidade_total": "3", "quantidade_faturada": "0", "quantidade_pendente": "3", "peso_total": "", "status_item_fiscal": "PENDENTE"},
            ],
        }

    def fiscal_rows(self, _filters):
        return list(self.rows.values())

    def fiscal_items(self, proposal_id):
        return [dict(item) for item in self.items.get(proposal_id, [])]

    def fiscal_status_label(self, value):
        return value


class FiscalItemSelectionDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_loads_one_or_many_proposals_without_mixing_items(self):
        dialog = FiscalItemSelectionDialog(FakeFiscalSelectionService(), [10, 20])
        self.assertEqual(len(dialog.groups), 2)
        self.assertEqual({item["id"] for item in dialog.groups[0]["items"]}, {101, 102})
        self.assertEqual({item["id"] for item in dialog.groups[1]["items"]}, {201})
        self.assertEqual(dialog.tree.topLevelItemCount(), 2)
        self.assertEqual(dialog.tree.topLevelItem(0).childCount(), 2)

    def test_parent_and_item_selection_updates_summary_and_contract(self):
        dialog = FiscalItemSelectionDialog(FakeFiscalSelectionService(), [10, 20])
        dialog.tree.topLevelItem(0).setCheckState(0, Qt.Checked)
        self.assertEqual(dialog.selected_item_ids, {101})
        self.assertEqual(dialog.selection_result().as_payload(), {"proposals": [{"proposal_id": 10, "selection_type": "TOTAL", "items": [{"item_id": 101, "pending_quantity": "5", "pending_weight": "10"}]}]})
        self.assertTrue(dialog.advance_button.isEnabled())

    def test_select_all_ignores_fully_billed_items_and_filter_preserves_selection(self):
        dialog = FiscalItemSelectionDialog(FakeFiscalSelectionService(), [10, 20])
        dialog._set_all(True)
        self.assertEqual(dialog.selected_item_ids, {101, 201})
        dialog.search.setText("Chapa")
        self.assertEqual(dialog.selected_item_ids, {101, 201})
        dialog.search.clear()
        self.assertEqual(dialog.selection_result().item_count, 2)

    def test_partial_selection_is_marked_partial_and_uses_pending_saldo(self):
        dialog = FiscalItemSelectionDialog(FakeFiscalSelectionService(), [10, 20])
        dialog.selected_item_ids.add(101)
        result = dialog.selection_result().as_payload()
        self.assertEqual(result["proposals"][0]["selection_type"], "TOTAL")
        self.assertEqual(result["proposals"][0]["items"][0]["pending_quantity"], "5")
        dialog.selected_item_ids.update({101, 201})
        result = dialog.selection_result().as_payload()
        self.assertEqual({row["proposal_id"] for row in result["proposals"]}, {10, 20})

    def test_inconsistent_or_empty_saldo_is_not_selectable(self):
        service = FakeFiscalSelectionService()
        service.items[10].append({"id": 103, "fiscal_processo_id": 10, "numero_item": "3", "quantidade_total": "1", "quantidade_faturada": "2", "quantidade_pendente": "-1", "status_item_fiscal": "PENDENTE"})
        dialog = FiscalItemSelectionDialog(service, [10])
        self.assertEqual({item["id"] for item in dialog.groups[0]["available"]}, {101})
        dialog._set_all(True)
        self.assertNotIn(103, dialog.selected_item_ids)

    def test_cancel_does_not_write_or_create_result(self):
        dialog = FiscalItemSelectionDialog(FakeFiscalSelectionService(), [10])
        dialog.reject()
        self.assertIsNone(dialog.result)


if __name__ == "__main__":
    unittest.main()
