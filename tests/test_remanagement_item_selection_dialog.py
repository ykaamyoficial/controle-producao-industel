from __future__ import annotations

import unittest
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from app.services.remanagement_flow_state import RemanagementFlowState, RemanagementItemSelection
from app.ui.remanagement_item_selection_dialog import (
    COLUMN_CHECK, COLUMN_REMANAGE, RemanagementItemSelectionStepDialog,
)


class FakeItemSelectionService:
    def __init__(self):
        self.destinations = [
            {"id": 9, "proposta": "CP05385", "cliente": "MNS Engenharia", "obra_site": "MSNVL002_A", "status_expedicao": "SEPARADO", "api_version": 4},
        ]
        self.items = [
            {"item_id": 101, "item_version": 1, "item_number": "1", "product_code": "300.23", "description": "PECA X", "unit": "UN", "total_quantity": "15.0000", "already_attended": "0.0000", "remanageable_need": "15.0000", "selectable": True, "block_reason": None},
            {"item_id": 102, "item_version": 1, "item_number": "2", "product_code": "300.17", "description": "CHAPA Y", "unit": "UN", "total_quantity": "55.0000", "already_attended": "20.0000", "remanageable_need": "35.0000", "selectable": True, "block_reason": None},
            {"item_id": 103, "item_version": 1, "item_number": "3", "product_code": None, "description": "SEM CODIGO", "unit": "UN", "total_quantity": "5.0000", "already_attended": "0.0000", "remanageable_need": "5.0000", "selectable": False, "block_reason": "Item sem codigo de produto para busca de remanejamento."},
            {"item_id": 104, "item_version": 1, "item_number": "4", "product_code": "400.01", "description": "SEM NECESSIDADE", "unit": "UN", "total_quantity": "3.0000", "already_attended": "3.0000", "remanageable_need": "0.0000", "selectable": False, "block_reason": "Item sem necessidade pendente de remanejamento."},
        ]
        self.destination_item_calls = 0

    def early_delivery_destination_candidates(self, search: str = ""):
        return [dict(row) for row in self.destinations]

    def remanagement_destination_items(self, destination_id: int):
        self.destination_item_calls += 1
        return [dict(row) for row in self.items]


def _state(destination_id: int = 9, version: int = 4) -> RemanagementFlowState:
    state = RemanagementFlowState()
    state.set_destination(destination_id, version)
    return state


def _row_for_item(dialog, item_id: int) -> int:
    for row in range(dialog.table.rowCount()):
        if int(dialog.table.item(row, COLUMN_CHECK).data(Qt.UserRole)) == item_id:
            return row
    raise AssertionError(f"item {item_id} not rendered")


class RemanagementItemSelectionStepDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_loads_header_and_items(self):
        dialog = RemanagementItemSelectionStepDialog(FakeItemSelectionService(), None, _state())
        self.assertIsNone(dialog.load_error)
        self.assertIn("CP05385", dialog.destination_label.text())
        self.assertEqual(dialog.table.rowCount(), 4)

    def test_item_without_code_is_not_selectable(self):
        dialog = RemanagementItemSelectionStepDialog(FakeItemSelectionService(), None, _state())
        row = _row_for_item(dialog, 103)
        check = dialog.table.item(row, COLUMN_CHECK)
        self.assertFalse(bool(check.flags() & Qt.ItemIsEnabled))

    def test_item_without_need_is_not_selectable(self):
        dialog = RemanagementItemSelectionStepDialog(FakeItemSelectionService(), None, _state())
        row = _row_for_item(dialog, 104)
        check = dialog.table.item(row, COLUMN_CHECK)
        self.assertFalse(bool(check.flags() & Qt.ItemIsEnabled))

    def test_destination_no_longer_eligible_sets_load_error(self):
        service = FakeItemSelectionService()
        service.destinations = []
        dialog = RemanagementItemSelectionStepDialog(service, None, _state())
        self.assertIsNotNone(dialog.load_error)
        self.assertEqual(dialog.table.rowCount(), 0)

    def test_items_fetch_failure_sets_load_error(self):
        service = FakeItemSelectionService()
        service.remanagement_destination_items = lambda destination_id: (_ for _ in ()).throw(RuntimeError("falhou"))
        dialog = RemanagementItemSelectionStepDialog(service, None, _state())
        self.assertEqual(dialog.load_error, "falhou")

    def test_checking_item_sets_default_quantity_to_need(self):
        dialog = RemanagementItemSelectionStepDialog(FakeItemSelectionService(), None, _state())
        row = _row_for_item(dialog, 101)
        dialog.table.item(row, COLUMN_CHECK).setCheckState(Qt.Checked)
        self.assertEqual(dialog._quantities[101], Decimal("15.0000"))
        self.assertEqual(dialog.table.item(row, COLUMN_REMANAGE).text(), "15")

    def test_unchecking_item_clears_quantity_and_removes_from_payload(self):
        dialog = RemanagementItemSelectionStepDialog(FakeItemSelectionService(), None, _state())
        row = _row_for_item(dialog, 101)
        dialog.table.item(row, COLUMN_CHECK).setCheckState(Qt.Checked)
        dialog.table.item(row, COLUMN_CHECK).setCheckState(Qt.Unchecked)
        self.assertNotIn(101, dialog._checked)
        self.assertNotIn(101, dialog._quantities)
        self.assertEqual(dialog.table.item(row, COLUMN_REMANAGE).text(), "0")

    def test_select_multiple_items_updates_summary(self):
        dialog = RemanagementItemSelectionStepDialog(FakeItemSelectionService(), None, _state())
        dialog.table.item(_row_for_item(dialog, 101), COLUMN_CHECK).setCheckState(Qt.Checked)
        dialog.table.item(_row_for_item(dialog, 102), COLUMN_CHECK).setCheckState(Qt.Checked)
        self.assertEqual({101, 102}, dialog._checked)
        self.assertIn("2 item(ns) selecionado(s)", dialog.summary_label.text())
        self.assertIn("50", dialog.summary_label.text())  # 15 + 35 UN, mesma unidade

    def test_search_filters_without_losing_selection(self):
        dialog = RemanagementItemSelectionStepDialog(FakeItemSelectionService(), None, _state())
        dialog.table.item(_row_for_item(dialog, 101), COLUMN_CHECK).setCheckState(Qt.Checked)
        dialog.search.setText("300.17")
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertIn(101, dialog._checked)
        dialog.search.clear()
        self.assertEqual(dialog.table.rowCount(), 4)
        row = _row_for_item(dialog, 101)
        self.assertEqual(dialog.table.item(row, COLUMN_CHECK).checkState(), Qt.Checked)
        self.assertEqual(dialog.table.item(row, COLUMN_REMANAGE).text(), "15")

    def test_select_eligible_ignores_blocked_items(self):
        dialog = RemanagementItemSelectionStepDialog(FakeItemSelectionService(), None, _state())
        dialog._select_eligible()
        self.assertEqual(dialog._checked, {101, 102})
        self.assertEqual(dialog._quantities[102], Decimal("35.0000"))

    def test_clear_selection_unchecks_everything(self):
        dialog = RemanagementItemSelectionStepDialog(FakeItemSelectionService(), None, _state())
        dialog._select_eligible()
        dialog._clear_selection()
        self.assertEqual(dialog._checked, set())
        self.assertEqual(dialog._quantities, {})
        self.assertFalse(dialog.advance_button.isEnabled())

    def test_quantity_equal_to_need_is_accepted(self):
        dialog = RemanagementItemSelectionStepDialog(FakeItemSelectionService(), None, _state())
        row = _row_for_item(dialog, 101)
        dialog.table.item(row, COLUMN_CHECK).setCheckState(Qt.Checked)
        dialog.table.item(row, COLUMN_REMANAGE).setText("15")
        self.assertEqual(dialog._quantities[101], Decimal("15"))

    def test_quantity_above_need_is_clamped(self):
        dialog = RemanagementItemSelectionStepDialog(FakeItemSelectionService(), None, _state())
        row = _row_for_item(dialog, 101)
        dialog.table.item(row, COLUMN_CHECK).setCheckState(Qt.Checked)
        dialog.table.item(row, COLUMN_REMANAGE).setText("999")
        self.assertEqual(dialog._quantities[101], Decimal("15.0000"))
        self.assertEqual(dialog.table.item(row, COLUMN_REMANAGE).text(), "15")

    def test_quantity_zero_or_negative_is_clamped_and_disables_advance(self):
        dialog = RemanagementItemSelectionStepDialog(FakeItemSelectionService(), None, _state())
        row = _row_for_item(dialog, 101)
        dialog.table.item(row, COLUMN_CHECK).setCheckState(Qt.Checked)
        dialog.table.item(row, COLUMN_REMANAGE).setText("-5")
        self.assertEqual(dialog._quantities[101], Decimal("0"))
        self.assertFalse(dialog.advance_button.isEnabled())

    def test_decimal_quantity_is_preserved(self):
        dialog = RemanagementItemSelectionStepDialog(FakeItemSelectionService(), None, _state())
        row = _row_for_item(dialog, 101)
        dialog.table.item(row, COLUMN_CHECK).setCheckState(Qt.Checked)
        dialog.table.item(row, COLUMN_REMANAGE).setText("2,5")
        self.assertEqual(dialog._quantities[101], Decimal("2.5"))

    def test_advance_disabled_without_selection(self):
        dialog = RemanagementItemSelectionStepDialog(FakeItemSelectionService(), None, _state())
        self.assertFalse(dialog.advance_button.isEnabled())

    def test_advance_builds_payload_and_sets_state(self):
        state = _state()
        dialog = RemanagementItemSelectionStepDialog(FakeItemSelectionService(), None, state)
        row101, row102 = _row_for_item(dialog, 101), _row_for_item(dialog, 102)
        dialog.table.item(row101, COLUMN_CHECK).setCheckState(Qt.Checked)
        dialog.table.item(row102, COLUMN_CHECK).setCheckState(Qt.Checked)
        dialog.table.item(row102, COLUMN_REMANAGE).setText("10")
        dialog._advance()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual({row.destination_item_id for row in state.item_selections}, {101, 102})
        self.assertEqual(state.selected_item_ids, [row.destination_item_id for row in state.item_selections])
        by_id = {row.destination_item_id: row for row in state.item_selections}
        self.assertEqual(by_id[102].remanage_quantity, Decimal("10"))
        self.assertEqual(by_id[102].product_code, "300.17")

    def test_voltar_returns_custom_result_code_without_writing(self):
        state = _state()
        dialog = RemanagementItemSelectionStepDialog(FakeItemSelectionService(), None, state)
        dialog.done(RemanagementItemSelectionStepDialog.RESULT_BACK)
        self.assertEqual(dialog.result(), RemanagementItemSelectionStepDialog.RESULT_BACK)
        self.assertEqual(state.item_selections, [])

    def test_reopening_with_existing_state_restores_checked_items_and_quantities(self):
        state = _state()
        state.set_item_selections([
            RemanagementItemSelection(destination_item_id=101, product_code="300.23", description="PECA X", unit="UN", remanage_quantity=Decimal("10"), current_need=Decimal("15")),
        ])
        dialog = RemanagementItemSelectionStepDialog(FakeItemSelectionService(), None, state)
        self.assertIn(101, dialog._checked)
        row = _row_for_item(dialog, 101)
        self.assertEqual(dialog.table.item(row, COLUMN_CHECK).checkState(), Qt.Checked)
        self.assertEqual(dialog.table.item(row, COLUMN_REMANAGE).text(), "10")

    def test_refresh_prunes_selection_that_lost_eligibility_or_shrank_below_need(self):
        state = _state()
        state.set_item_selections([
            RemanagementItemSelection(destination_item_id=101, product_code="300.23", description="PECA X", unit="UN", remanage_quantity=Decimal("15"), current_need=Decimal("15")),
            RemanagementItemSelection(destination_item_id=103, product_code="X", description="SEM CODIGO", unit="UN", remanage_quantity=Decimal("5"), current_need=Decimal("5")),
        ])
        service = FakeItemSelectionService()
        service.items[0]["remanageable_need"] = "5.0000"  # necessidade do item 101 encolheu
        dialog = RemanagementItemSelectionStepDialog(service, None, state)
        self.assertNotIn(103, dialog._checked)  # nunca foi selecionavel, nao sobrevive ao refresh
        self.assertIn(101, dialog._checked)
        self.assertEqual(dialog._quantities[101], Decimal("5.0000"))  # nunca acima do novo saldo

    def test_trocar_destino_na_etapa_1_descarta_selecao_da_etapa_2(self):
        state = _state()
        state.set_item_selections([
            RemanagementItemSelection(destination_item_id=101, product_code="300.23", description="PECA X", unit="UN", remanage_quantity=Decimal("15"), current_need=Decimal("15")),
        ])
        state.set_destination(20, 1)
        self.assertEqual(state.item_selections, [])
        self.assertEqual(state.selected_item_ids, [])


if __name__ == "__main__":
    unittest.main()
