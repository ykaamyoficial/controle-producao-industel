from __future__ import annotations

import unittest
from decimal import Decimal

from PySide6.QtWidgets import QApplication, QDialog, QLabel

from app.services.remanagement_flow_state import RemanagementFlowState, RemanagementItemSelection
from app.ui.remanagement_availability_dialog import RemanagementAvailabilityStepDialog


class FakeAvailabilityService:
    def __init__(self):
        self.destinations = [
            {"id": 9, "proposta": "CP05385", "cliente": "MNS Engenharia", "obra_site": "MSNVL002_A", "status_expedicao": "SEPARADO", "api_version": 4},
        ]
        self.response = {
            "destination_proposal_id": 9,
            "items": [
                {
                    "destination_item_id": 101, "product_code": "300.23", "description": "PECA W17", "unit": "UN",
                    "requested_quantity": "10", "total_available": "37", "coverage_status": "SUFICIENTE",
                    "candidates": [
                        {"source_proposal_id": 20, "source_proposal_number": "CP05236", "source_item_id": 501, "source_item_version": 1, "client": "ENERGY SYSTEM", "site": "SE CAMPESTRE", "available_quantity": "15", "unit": "UN", "operational_status": "SEPARADO"},
                        {"source_proposal_id": 21, "source_proposal_number": "CP05301", "source_item_id": 502, "source_item_version": 1, "client": "MNS ENGENHARIA", "site": "TAMTROI0013", "available_quantity": "8", "unit": "UN", "operational_status": "SEPARADO"},
                    ],
                },
                {
                    "destination_item_id": 102, "product_code": "401.20", "description": "CANTONEIRA", "unit": "UN",
                    "requested_quantity": "5", "total_available": "0", "coverage_status": "SEM_DISPONIBILIDADE",
                    "candidates": [],
                },
            ],
        }
        self.calls: list[tuple[int, list[dict]]] = []

    def early_delivery_destination_candidates(self, search: str = ""):
        return [dict(row) for row in self.destinations]

    def remanagement_availability(self, destination_id: int, items: list[dict]):
        self.calls.append((destination_id, items))
        return self.response


def _state_with_selection(destination_id: int = 9) -> RemanagementFlowState:
    state = RemanagementFlowState()
    state.set_destination(destination_id, 4)
    state.set_item_selections([
        RemanagementItemSelection(destination_item_id=101, product_code="300.23", description="PECA W17", unit="UN", remanage_quantity=Decimal("10"), current_need=Decimal("10")),
        RemanagementItemSelection(destination_item_id=102, product_code="401.20", description="CANTONEIRA", unit="UN", remanage_quantity=Decimal("5"), current_need=Decimal("5")),
    ])
    return state


def _summary_texts(dialog) -> list[str]:
    texts = []
    for row in range(dialog.groups_layout.count()):
        frame = dialog.groups_layout.itemAt(row).widget()
        if frame is None:
            continue
        texts.extend(label.text() for label in frame.findChildren(QLabel))
    return texts


class RemanagementAvailabilityStepDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_loads_header_and_groups(self):
        dialog = RemanagementAvailabilityStepDialog(FakeAvailabilityService(), None, _state_with_selection())
        self.assertIsNone(dialog.load_error)
        self.assertIn("CP05385", dialog.destination_label.text())
        self.assertEqual(len(dialog._groups), 2)

    def test_search_is_automatic_without_extra_input(self):
        service = FakeAvailabilityService()
        RemanagementAvailabilityStepDialog(service, None, _state_with_selection())
        self.assertEqual(len(service.calls), 1)

    def test_request_payload_matches_item_selections(self):
        service = FakeAvailabilityService()
        RemanagementAvailabilityStepDialog(service, None, _state_with_selection())
        destination_id, items = service.calls[0]
        self.assertEqual(destination_id, 9)
        self.assertEqual(
            {(row["destination_item_id"], row["requested_quantity"]) for row in items},
            {(101, Decimal("10")), (102, Decimal("5"))},
        )

    def test_advance_enabled_when_any_group_has_candidates(self):
        dialog = RemanagementAvailabilityStepDialog(FakeAvailabilityService(), None, _state_with_selection())
        self.assertTrue(dialog.advance_button.isEnabled())

    def test_advance_disabled_when_no_group_has_candidates(self):
        service = FakeAvailabilityService()
        for group in service.response["items"]:
            group["candidates"] = []
            group["coverage_status"] = "SEM_DISPONIBILIDADE"
        dialog = RemanagementAvailabilityStepDialog(service, None, _state_with_selection())
        self.assertFalse(dialog.advance_button.isEnabled())

    def test_empty_state_shown_for_item_without_candidates(self):
        dialog = RemanagementAvailabilityStepDialog(FakeAvailabilityService(), None, _state_with_selection())
        texts = _summary_texts(dialog)
        self.assertTrue(any("Nenhum material pronto disponivel" in text for text in texts))

    def test_coverage_labels_rendered_in_portuguese(self):
        dialog = RemanagementAvailabilityStepDialog(FakeAvailabilityService(), None, _state_with_selection())
        texts = " ".join(_summary_texts(dialog))
        self.assertIn("Material disponivel suficiente", texts)

    def test_missing_destination_sets_load_error(self):
        service = FakeAvailabilityService()
        service.destinations = []
        dialog = RemanagementAvailabilityStepDialog(service, None, _state_with_selection())
        self.assertIsNotNone(dialog.load_error)

    def test_missing_item_selections_sets_load_error(self):
        service = FakeAvailabilityService()
        state = RemanagementFlowState()
        state.set_destination(9, 4)
        dialog = RemanagementAvailabilityStepDialog(service, None, state)
        self.assertIn("Nenhum item", dialog.load_error)
        self.assertEqual(service.calls, [])

    def test_service_error_sets_load_error(self):
        service = FakeAvailabilityService()
        service.remanagement_availability = lambda destination_id, items: (_ for _ in ()).throw(RuntimeError("falhou"))
        dialog = RemanagementAvailabilityStepDialog(service, None, _state_with_selection())
        self.assertEqual(dialog.load_error, "falhou")

    def test_state_availability_populated_after_load(self):
        state = _state_with_selection()
        RemanagementAvailabilityStepDialog(FakeAvailabilityService(), None, state)
        self.assertEqual(len(state.availability), 2)
        first = next(row for row in state.availability if row.destination_item_id == 101)
        self.assertEqual(first.product_code, "300.23")
        self.assertEqual(len(first.candidates), 2)
        self.assertEqual(first.total_available, Decimal("37"))
        self.assertEqual(first.coverage_status, "SUFICIENTE")

    def test_voltar_returns_custom_result_code_without_writing(self):
        dialog = RemanagementAvailabilityStepDialog(FakeAvailabilityService(), None, _state_with_selection())
        dialog.done(RemanagementAvailabilityStepDialog.RESULT_BACK)
        self.assertEqual(dialog.result(), RemanagementAvailabilityStepDialog.RESULT_BACK)

    def test_advance_accepts(self):
        dialog = RemanagementAvailabilityStepDialog(FakeAvailabilityService(), None, _state_with_selection())
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.Accepted)

    def test_refresh_reruns_search_and_updates_state(self):
        service = FakeAvailabilityService()
        dialog = RemanagementAvailabilityStepDialog(service, None, _state_with_selection())
        service.response["items"][1]["candidates"] = [
            {"source_proposal_id": 30, "source_proposal_number": "CP05306", "source_item_id": 700, "source_item_version": 1, "client": "GREGO", "site": "OBRA", "available_quantity": "7", "unit": "UN", "operational_status": "SEPARADO"},
        ]
        service.response["items"][1]["total_available"] = "7"
        service.response["items"][1]["coverage_status"] = "SUFICIENTE"
        dialog._refresh_clicked()
        self.assertEqual(len(service.calls), 2)
        updated = next(row for row in dialog.state.availability if row.destination_item_id == 102)
        self.assertEqual(updated.coverage_status, "SUFICIENTE")
        self.assertEqual(len(updated.candidates), 1)


if __name__ == "__main__":
    unittest.main()
