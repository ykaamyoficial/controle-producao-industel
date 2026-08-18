from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.services.remanagement_flow_state import (
    RemanagementFlowState, RemanagementItemAllocation, RemanagementItemSelection,
    RemanagementSourceAllocation, availability_from_api,
)
from app.ui.remanagement_allocation_dialog import COLUMN_SOURCE, COLUMN_TAKE, RemanagementAllocationStepDialog


class FakeAllocationService:
    def __init__(self):
        self.destinations = [
            {"id": 9, "proposta": "CP05385", "cliente": "MNS Engenharia", "obra_site": "MSNVL002_A", "status_expedicao": "SEPARADO", "api_version": 4},
        ]
        self.availability_response = {
            "destination_proposal_id": 9,
            "items": [
                {
                    "destination_item_id": 101, "product_code": "300.23", "description": "PECA W17", "unit": "UN",
                    "requested_quantity": "20", "total_available": "37", "coverage_status": "SUFICIENTE",
                    "candidates": [
                        {"source_proposal_id": 20, "source_proposal_number": "CP05236", "source_item_id": 501, "source_item_version": 1, "client": "ENERGY SYSTEM", "site": "SE CAMPESTRE", "available_quantity": "12", "unit": "UN", "operational_status": "SEPARADO"},
                        {"source_proposal_id": 21, "source_proposal_number": "CP05301", "source_item_id": 502, "source_item_version": 1, "client": "MNS ENGENHARIA", "site": "TAMTROI0013", "available_quantity": "5", "unit": "UN", "operational_status": "SEPARADO"},
                        {"source_proposal_id": 22, "source_proposal_number": "CP05401", "source_item_id": 503, "source_item_version": 1, "client": "MNS ENGENHARIA", "site": "MSRBS006_A", "available_quantity": "20", "unit": "UN", "operational_status": "SEPARADO"},
                    ],
                },
                {
                    "destination_item_id": 102, "product_code": "401.20", "description": "CANTONEIRA", "unit": "UN",
                    "requested_quantity": "5", "total_available": "7", "coverage_status": "SUFICIENTE",
                    "candidates": [
                        {"source_proposal_id": 23, "source_proposal_number": "CP05306", "source_item_id": 700, "source_item_version": 1, "client": "GREGO", "site": "OBRA", "available_quantity": "7", "unit": "UN", "operational_status": "SEPARADO"},
                    ],
                },
            ],
        }
        self.calls: list[tuple[int, list[dict]]] = []

    def early_delivery_destination_candidates(self, search: str = ""):
        return [dict(row) for row in self.destinations]

    def remanagement_availability(self, destination_id: int, items: list[dict]):
        self.calls.append((destination_id, items))
        return self.availability_response


def _state_with_availability(service: FakeAllocationService, destination_id: int = 9) -> RemanagementFlowState:
    state = RemanagementFlowState()
    state.set_destination(destination_id, 4)
    state.set_item_selections([
        RemanagementItemSelection(
            destination_item_id=int(row["destination_item_id"]), product_code=row["product_code"],
            description=row["description"], unit=row["unit"],
            remanage_quantity=Decimal(row["requested_quantity"]), current_need=Decimal(row["requested_quantity"]),
        )
        for row in service.availability_response["items"]
    ])
    state.set_availability(availability_from_api(service.availability_response["items"]))
    return state


def _row_for_source(table, source_proposal_id: int, source_item_id: int) -> int:
    for row in range(table.rowCount()):
        if table.item(row, COLUMN_SOURCE).data(Qt.UserRole) == (source_proposal_id, source_item_id):
            return row
    raise AssertionError(f"source ({source_proposal_id}, {source_item_id}) nao renderizado")


class RemanagementAllocationStepDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_loads_header_and_groups(self):
        service = FakeAllocationService()
        dialog = RemanagementAllocationStepDialog(service, None, _state_with_availability(service))
        self.assertIsNone(dialog.load_error)
        self.assertIn("CP05385", dialog.destination_label.text())
        self.assertEqual(len(dialog._tables), 2)

    def test_manual_take_clamped_to_available_quantity(self):
        service = FakeAllocationService()
        dialog = RemanagementAllocationStepDialog(service, None, _state_with_availability(service))
        table = dialog._tables[101]
        row = _row_for_source(table, 20, 501)
        table.item(row, COLUMN_TAKE).setText("999")
        self.assertEqual(dialog._allocations[101][(20, 501)], Decimal("12.0000"))

    def test_manual_take_clamped_to_remaining_need_across_rows(self):
        service = FakeAllocationService()
        dialog = RemanagementAllocationStepDialog(service, None, _state_with_availability(service))
        table = dialog._tables[101]
        row_a = _row_for_source(table, 20, 501)
        row_c = _row_for_source(table, 22, 503)
        table.item(row_a, COLUMN_TAKE).setText("12")  # requested=20, usa 12
        table.item(row_c, COLUMN_TAKE).setText("20")  # so sobram 8
        self.assertEqual(dialog._allocations[101][(22, 503)], Decimal("8.0000"))

    def test_negative_value_is_rejected_to_zero(self):
        service = FakeAllocationService()
        dialog = RemanagementAllocationStepDialog(service, None, _state_with_availability(service))
        table = dialog._tables[101]
        row = _row_for_source(table, 20, 501)
        table.item(row, COLUMN_TAKE).setText("-5")
        self.assertNotIn((20, 501), dialog._allocations.get(101, {}))
        self.assertEqual(table.item(row, COLUMN_TAKE).text(), "0")

    def test_zero_quantity_removes_allocation_entry(self):
        service = FakeAllocationService()
        dialog = RemanagementAllocationStepDialog(service, None, _state_with_availability(service))
        table = dialog._tables[101]
        row = _row_for_source(table, 20, 501)
        table.item(row, COLUMN_TAKE).setText("5")
        self.assertIn((20, 501), dialog._allocations[101])
        table.item(row, COLUMN_TAKE).setText("0")
        self.assertNotIn((20, 501), dialog._allocations.get(101, {}))

    def test_decimal_quantity_is_preserved(self):
        service = FakeAllocationService()
        dialog = RemanagementAllocationStepDialog(service, None, _state_with_availability(service))
        table = dialog._tables[101]
        row = _row_for_source(table, 20, 501)
        table.item(row, COLUMN_TAKE).setText("2,5")
        self.assertEqual(dialog._allocations[101][(20, 501)], Decimal("2.5"))

    def test_two_sources_divide_quantity(self):
        service = FakeAllocationService()
        dialog = RemanagementAllocationStepDialog(service, None, _state_with_availability(service))
        table = dialog._tables[101]
        table.item(_row_for_source(table, 20, 501), COLUMN_TAKE).setText("12")
        table.item(_row_for_source(table, 21, 502), COLUMN_TAKE).setText("5")
        self.assertEqual(sum(dialog._allocations[101].values()), Decimal("17"))

    def test_three_sources_divide_quantity(self):
        service = FakeAllocationService()
        dialog = RemanagementAllocationStepDialog(service, None, _state_with_availability(service))
        table = dialog._tables[101]
        table.item(_row_for_source(table, 20, 501), COLUMN_TAKE).setText("12")
        table.item(_row_for_source(table, 21, 502), COLUMN_TAKE).setText("5")
        table.item(_row_for_source(table, 22, 503), COLUMN_TAKE).setText("3")
        self.assertEqual(sum(dialog._allocations[101].values()), Decimal("20"))

    def test_suggest_item_prioritizes_fewest_origins(self):
        service = FakeAllocationService()
        dialog = RemanagementAllocationStepDialog(service, None, _state_with_availability(service))
        dialog._suggest_item(101)
        self.assertEqual(dialog._allocations[101], {(22, 503): Decimal("20.0000")})

    def test_reapply_suggest_replaces_instead_of_accumulating(self):
        service = FakeAllocationService()
        dialog = RemanagementAllocationStepDialog(service, None, _state_with_availability(service))
        table = dialog._tables[101]
        table.item(_row_for_source(table, 21, 502), COLUMN_TAKE).setText("5")
        dialog._suggest_item(101)
        self.assertEqual(sum(dialog._allocations[101].values()), Decimal("20"))
        self.assertEqual(dialog._allocations[101], {(22, 503): Decimal("20.0000")})

    def test_clear_item_only_clears_that_item(self):
        service = FakeAllocationService()
        dialog = RemanagementAllocationStepDialog(service, None, _state_with_availability(service))
        dialog._suggest_item(101)
        dialog._suggest_item(102)
        dialog._clear_item(101)
        self.assertEqual(dialog._allocations.get(101, {}), {})
        self.assertTrue(dialog._allocations.get(102))

    def test_clear_all_allocations(self):
        service = FakeAllocationService()
        dialog = RemanagementAllocationStepDialog(service, None, _state_with_availability(service))
        dialog._suggest_item(101)
        dialog._suggest_item(102)
        dialog._clear_all()
        self.assertEqual(dialog._allocations, {})
        self.assertFalse(dialog.advance_button.isEnabled())

    def test_multiple_products_have_independent_allocation(self):
        service = FakeAllocationService()
        dialog = RemanagementAllocationStepDialog(service, None, _state_with_availability(service))
        dialog._suggest_item(101)
        dialog._suggest_item(102)
        self.assertEqual(dialog._allocations[102], {(23, 700): Decimal("5.0000")})
        self.assertNotEqual(set(dialog._allocations[101]), set(dialog._allocations[102]))

    def test_advance_disabled_when_nothing_allocated(self):
        service = FakeAllocationService()
        dialog = RemanagementAllocationStepDialog(service, None, _state_with_availability(service))
        self.assertFalse(dialog.advance_button.isEnabled())

    def test_advance_builds_plan_and_sets_state(self):
        service = FakeAllocationService()
        state = _state_with_availability(service)
        dialog = RemanagementAllocationStepDialog(service, None, state)
        dialog._suggest_item(101)
        dialog._suggest_item(102)
        self.assertTrue(dialog.advance_button.isEnabled())
        dialog._advance()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(len(state.allocations), 2)
        item101 = next(row for row in state.allocations if row.destination_item_id == 101)
        self.assertEqual(item101.allocated_quantity, Decimal("20.0000"))
        self.assertEqual(item101.status, "COMPLETO")

    def test_voltar_returns_custom_result_code_without_writing(self):
        service = FakeAllocationService()
        dialog = RemanagementAllocationStepDialog(service, None, _state_with_availability(service))
        dialog.done(RemanagementAllocationStepDialog.RESULT_BACK)
        self.assertEqual(dialog.result(), RemanagementAllocationStepDialog.RESULT_BACK)

    def test_missing_destination_sets_load_error(self):
        service = FakeAllocationService()
        service.destinations = []
        dialog = RemanagementAllocationStepDialog(service, None, _state_with_availability(service))
        self.assertIsNotNone(dialog.load_error)

    def test_missing_availability_sets_load_error(self):
        service = FakeAllocationService()
        state = RemanagementFlowState()
        state.set_destination(9, 4)
        dialog = RemanagementAllocationStepDialog(service, None, state)
        self.assertIn("disponibilidade", dialog.load_error)

    def test_preserves_previous_allocation_when_reopened_with_state(self):
        service = FakeAllocationService()
        state = _state_with_availability(service)
        state.set_allocations([
            RemanagementItemAllocation(
                destination_item_id=101, product_code="300.23", unit="UN", requested_quantity=Decimal("20"),
                allocations=[RemanagementSourceAllocation(source_proposal_id=20, source_item_id=501, available_snapshot=Decimal("12"), allocated_quantity=Decimal("10"))],
            ),
        ])
        dialog = RemanagementAllocationStepDialog(service, None, state)
        self.assertEqual(dialog._allocations[101][(20, 501)], Decimal("10"))
        table = dialog._tables[101]
        row = _row_for_source(table, 20, 501)
        self.assertEqual(table.item(row, COLUMN_TAKE).text(), "10")

    def test_refresh_reduced_balance_marks_item_invalid_without_silent_truncation(self):
        service = FakeAllocationService()
        state = _state_with_availability(service)
        dialog = RemanagementAllocationStepDialog(service, None, state)
        table = dialog._tables[101]
        table.item(_row_for_source(table, 20, 501), COLUMN_TAKE).setText("12")
        service.availability_response["items"][0]["candidates"][0]["available_quantity"] = "4.0000"
        dialog._refresh_clicked()
        self.assertTrue(dialog._item_has_invalid_row(101))
        # nao foi truncado silenciosamente: o valor digitado (12) permanece intacto
        self.assertEqual(dialog._allocations[101][(20, 501)], Decimal("12.0000"))
        self.assertFalse(dialog.advance_button.isEnabled())

    def test_refresh_candidate_disappearing_marks_item_invalid(self):
        service = FakeAllocationService()
        state = _state_with_availability(service)
        dialog = RemanagementAllocationStepDialog(service, None, state)
        table = dialog._tables[101]
        table.item(_row_for_source(table, 20, 501), COLUMN_TAKE).setText("12")
        service.availability_response["items"][0]["candidates"] = [
            row for row in service.availability_response["items"][0]["candidates"] if row["source_item_id"] != 501
        ]
        dialog._refresh_clicked()
        self.assertTrue(dialog._item_has_invalid_row(101))
        self.assertFalse(dialog.advance_button.isEnabled())

    def test_advance_blocked_while_invalid_row_present(self):
        service = FakeAllocationService()
        state = _state_with_availability(service)
        dialog = RemanagementAllocationStepDialog(service, None, state)
        table = dialog._tables[101]
        table.item(_row_for_source(table, 20, 501), COLUMN_TAKE).setText("12")
        service.availability_response["items"][0]["candidates"][0]["available_quantity"] = "4.0000"
        dialog._refresh_clicked()
        with patch.object(QMessageBox, "warning", return_value=None):
            dialog._advance()
        self.assertNotEqual(dialog.result(), QDialog.Accepted)


if __name__ == "__main__":
    unittest.main()
