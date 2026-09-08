from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.services.remanagement_flow_state import (
    RemanagementFlowState, RemanagementItemAllocation, RemanagementItemAvailability,
    RemanagementItemSelection, RemanagementSourceAllocation, RemanagementSourceCandidate,
)
from app.ui.remanagement_review_dialog import RemanagementReviewStepDialog


class FakeReviewService:
    def __init__(self):
        self.destinations = [
            {"id": 9, "proposta": "CP05385", "cliente": "MNS Engenharia", "obra_site": "MSNVL002_A", "status_expedicao": "SEPARADO", "api_version": 4},
        ]
        self.response = {
            "destination_proposal_id": 9,
            "valid": True,
            "warnings": [],
            "errors": [],
            "summary": {
                "product_count": 2, "source_proposal_count": 3, "source_item_count": 3,
                "total_quantity": "25", "total_unit": "UN",
                "complete_items": 2, "partial_items": 0, "not_allocated_items": 0, "invalid_items": 0,
            },
            "items": [
                {
                    "destination_item_id": 101, "product_code": "300.23", "requested": "20", "allocated": "20", "remaining": "0", "status": "COMPLETO",
                    "sources": [
                        {"source_proposal_id": 20, "source_item_id": 501, "ready_transfer": "12", "production_compensation": "12", "source_before": "15", "source_after_simulated": "3"},
                        {"source_proposal_id": 21, "source_item_id": 502, "ready_transfer": "8", "production_compensation": "8", "source_before": "10", "source_after_simulated": "2"},
                    ],
                },
                {
                    "destination_item_id": 102, "product_code": "401.20", "requested": "5", "allocated": "5", "remaining": "0", "status": "COMPLETO",
                    "sources": [
                        {"source_proposal_id": 23, "source_item_id": 700, "ready_transfer": "5", "production_compensation": "5", "source_before": "7", "source_after_simulated": "2"},
                    ],
                },
            ],
        }
        self.calls: list[tuple] = []
        self.confirm_calls: list[tuple] = []
        self.confirm_error: Exception | None = None
        self.confirm_response = {
            "operation_id": "op-test-0001", "status": "CONFIRMED", "destination_proposal_id": 9,
            "source_proposals": [20, 21, 23], "products": 2, "allocations": 3,
            "confirmed_at": "2026-08-17T12:00:00Z", "remanagements": [],
        }

    def early_delivery_destination_candidates(self, search: str = ""):
        return [dict(row) for row in self.destinations]

    def remanagement_review(self, destination_id, items, allocations, reason):
        self.calls.append((destination_id, items, allocations, reason))
        return self.response

    def remanagement_confirm(self, operation_id, destination_id, items, allocations, reason):
        self.confirm_calls.append((operation_id, destination_id, items, allocations, reason))
        if self.confirm_error is not None:
            raise self.confirm_error
        return self.confirm_response


def _state_with_allocations(reason: str = "") -> RemanagementFlowState:
    state = RemanagementFlowState()
    state.set_destination(9, 4)
    state.set_item_selections([
        RemanagementItemSelection(destination_item_id=101, product_code="300.23", description="PECA W17", unit="UN", remanage_quantity=Decimal("20"), current_need=Decimal("20")),
        RemanagementItemSelection(destination_item_id=102, product_code="401.20", description="CANTONEIRA", unit="UN", remanage_quantity=Decimal("5"), current_need=Decimal("5")),
    ])
    state.set_availability([
        RemanagementItemAvailability(
            destination_item_id=101, product_code="300.23", description="PECA W17", unit="UN",
            requested_quantity=Decimal("20"), total_available=Decimal("37"), coverage_status="SUFICIENTE",
            candidates=[
                RemanagementSourceCandidate(source_proposal_id=20, source_proposal_number="CP05236", source_item_id=501, source_item_version=1, client="ENERGY SYSTEM", site="SE CAMPESTRE", available_quantity=Decimal("15"), unit="UN", operational_status="SEPARADO"),
                RemanagementSourceCandidate(source_proposal_id=21, source_proposal_number="CP05301", source_item_id=502, source_item_version=1, client="MNS ENGENHARIA", site="TAMTROI0013", available_quantity=Decimal("10"), unit="UN", operational_status="SEPARADO"),
            ],
        ),
        RemanagementItemAvailability(
            destination_item_id=102, product_code="401.20", description="CANTONEIRA", unit="UN",
            requested_quantity=Decimal("5"), total_available=Decimal("7"), coverage_status="SUFICIENTE",
            candidates=[
                RemanagementSourceCandidate(source_proposal_id=23, source_proposal_number="CP05306", source_item_id=700, source_item_version=1, client="GREGO", site="OBRA", available_quantity=Decimal("7"), unit="UN", operational_status="SEPARADO"),
            ],
        ),
    ])
    state.set_allocations([
        RemanagementItemAllocation(destination_item_id=101, product_code="300.23", unit="UN", requested_quantity=Decimal("20"), allocations=[
            RemanagementSourceAllocation(source_proposal_id=20, source_item_id=501, available_snapshot=Decimal("15"), allocated_quantity=Decimal("12")),
            RemanagementSourceAllocation(source_proposal_id=21, source_item_id=502, available_snapshot=Decimal("10"), allocated_quantity=Decimal("8")),
        ]),
        RemanagementItemAllocation(destination_item_id=102, product_code="401.20", unit="UN", requested_quantity=Decimal("5"), allocations=[
            RemanagementSourceAllocation(source_proposal_id=23, source_item_id=700, available_snapshot=Decimal("7"), allocated_quantity=Decimal("5")),
        ]),
    ])
    state.set_reason(reason)
    return state


def _all_group_text(dialog) -> str:
    texts = []
    for row in range(dialog.groups_layout.count()):
        frame = dialog.groups_layout.itemAt(row).widget()
        if frame is None:
            continue
        for label in frame.findChildren(type(dialog.summary_label)):
            texts.append(label.text())
    return "\n".join(texts)


class RemanagementReviewStepDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_loads_header_summary_and_groups(self):
        service = FakeReviewService()
        dialog = RemanagementReviewStepDialog(service, None, _state_with_allocations())
        self.assertIsNone(dialog.load_error)
        self.assertIn("CP05385", dialog.destination_label.text())
        self.assertIn("2 produto(s)", dialog.summary_label.text())
        self.assertIn("25 UN alocadas", dialog.summary_label.text())

    def test_review_is_called_automatically_on_open(self):
        service = FakeReviewService()
        RemanagementReviewStepDialog(service, None, _state_with_allocations())
        self.assertEqual(len(service.calls), 1)

    def test_confirm_disabled_without_reason(self):
        service = FakeReviewService()
        dialog = RemanagementReviewStepDialog(service, None, _state_with_allocations())
        self.assertFalse(dialog.confirm_button.isEnabled())

    def test_confirm_enabled_when_valid_and_reason_filled(self):
        service = FakeReviewService()
        dialog = RemanagementReviewStepDialog(service, None, _state_with_allocations())
        dialog.reason_edit.setPlainText("Cliente solicitou retirada antecipada")
        self.assertTrue(dialog.confirm_button.isEnabled())

    def test_reason_with_only_whitespace_keeps_confirm_disabled(self):
        service = FakeReviewService()
        dialog = RemanagementReviewStepDialog(service, None, _state_with_allocations())
        dialog.reason_edit.setPlainText("    ")
        self.assertFalse(dialog.confirm_button.isEnabled())

    def test_reason_is_saved_to_state_as_typed(self):
        service = FakeReviewService()
        state = _state_with_allocations()
        dialog = RemanagementReviewStepDialog(service, None, state)
        dialog.reason_edit.setPlainText("Motivo real da operacao")
        self.assertEqual(state.reason, "Motivo real da operacao")

    def test_material_pronto_and_obrigacao_are_shown_as_separate_blocks(self):
        service = FakeReviewService()
        dialog = RemanagementReviewStepDialog(service, None, _state_with_allocations())
        text = _all_group_text(dialog)
        self.assertIn("MATERIAL PRONTO", text)
        self.assertIn("OBRIGACAO DE PRODUCAO", text)
        ready_index = text.index("MATERIAL PRONTO")
        obligation_index = text.index("OBRIGACAO DE PRODUCAO")
        self.assertLess(ready_index, obligation_index)

    def test_before_after_balance_is_shown_per_source(self):
        service = FakeReviewService()
        dialog = RemanagementReviewStepDialog(service, None, _state_with_allocations())
        text = _all_group_text(dialog)
        self.assertIn("Pronto na Expedicao: 15 -> 3", text)

    def test_partial_coverage_shows_attention_notice(self):
        service = FakeReviewService()
        service.response["items"][1]["allocated"] = "3"
        service.response["items"][1]["remaining"] = "2"
        service.response["items"][1]["status"] = "PARCIAL"
        service.response["summary"]["complete_items"] = 1
        service.response["summary"]["partial_items"] = 1
        dialog = RemanagementReviewStepDialog(service, None, _state_with_allocations())
        text = _all_group_text(dialog)
        self.assertIn("Atencao", text)
        self.assertIn("continuarao sem atendimento", text)

    def test_invalid_item_blocks_confirm_and_shows_error(self):
        service = FakeReviewService()
        service.response["valid"] = False
        service.response["errors"] = [{"code": "ALLOCATION_EXCEEDS_SOURCE_SNAPSHOT", "message": "Saldo insuficiente para CP05236.", "destination_item_id": 101, "source_item_id": 501}]
        service.response["items"][0]["status"] = "INVALIDO"
        dialog = RemanagementReviewStepDialog(service, None, _state_with_allocations())
        dialog.reason_edit.setPlainText("Motivo valido")
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.assertIn("Saldo insuficiente", dialog.warnings_label.text())

    def test_revalidate_refreshes_result_and_calls_service_again(self):
        service = FakeReviewService()
        dialog = RemanagementReviewStepDialog(service, None, _state_with_allocations())
        dialog.reason_edit.setPlainText("Motivo valido")
        service.response = dict(service.response, valid=False, errors=[{"code": "ALLOCATION_EXCEEDS_SOURCE_SNAPSHOT", "message": "Saldo caiu.", "destination_item_id": 101, "source_item_id": 501}])
        dialog._revalidate_clicked()
        self.assertEqual(len(service.calls), 2)
        self.assertFalse(dialog.confirm_button.isEnabled())

    def test_voltar_returns_custom_result_code_without_writing(self):
        service = FakeReviewService()
        dialog = RemanagementReviewStepDialog(service, None, _state_with_allocations())
        dialog.done(RemanagementReviewStepDialog.RESULT_BACK)
        self.assertEqual(dialog.result(), RemanagementReviewStepDialog.RESULT_BACK)

    def test_missing_destination_sets_load_error(self):
        service = FakeReviewService()
        service.destinations = []
        dialog = RemanagementReviewStepDialog(service, None, _state_with_allocations())
        self.assertIsNotNone(dialog.load_error)

    def test_missing_allocations_sets_load_error(self):
        service = FakeReviewService()
        state = RemanagementFlowState()
        state.set_destination(9, 4)
        dialog = RemanagementReviewStepDialog(service, None, state)
        self.assertIn("alocacao", dialog.load_error.lower())

    def test_confirm_accepts_on_yes_and_saves_trimmed_reason(self):
        service = FakeReviewService()
        state = _state_with_allocations()
        dialog = RemanagementReviewStepDialog(service, None, state)
        dialog.reason_edit.setPlainText("  Motivo real  ")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            dialog._confirm_clicked()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(state.reason, "Motivo real")

    def test_confirm_calls_service_with_state_operation_id_and_plan(self):
        service = FakeReviewService()
        state = _state_with_allocations()
        dialog = RemanagementReviewStepDialog(service, None, state)
        dialog.reason_edit.setPlainText("Motivo real")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            dialog._confirm_clicked()
        self.assertEqual(len(service.confirm_calls), 1)
        operation_id, destination_id, items, allocations, reason = service.confirm_calls[0]
        self.assertEqual(operation_id, state.operation_id)
        self.assertEqual(destination_id, 9)
        self.assertEqual(len(items), 2)
        self.assertEqual(len(allocations), 3)
        self.assertEqual(reason, "Motivo real")
        self.assertEqual(dialog.confirm_result, service.confirm_response)

    def test_confirm_cancelled_reenables_button_and_does_not_accept(self):
        service = FakeReviewService()
        dialog = RemanagementReviewStepDialog(service, None, _state_with_allocations())
        dialog.reason_edit.setPlainText("Motivo real")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
            dialog._confirm_clicked()
        self.assertNotEqual(dialog.result(), QDialog.Accepted)
        self.assertTrue(dialog.confirm_button.isEnabled())
        self.assertEqual(service.confirm_calls, [])

    def test_double_click_does_not_show_confirmation_twice(self):
        service = FakeReviewService()
        dialog = RemanagementReviewStepDialog(service, None, _state_with_allocations())
        dialog.reason_edit.setPlainText("Motivo real")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes) as question:
            dialog._confirm_clicked()
            dialog._confirm_clicked()  # botao ja desabilitado pelo primeiro clique
        self.assertEqual(question.call_count, 1)

    def test_confirm_error_shows_message_revalidates_and_does_not_accept(self):
        service = FakeReviewService()
        service.confirm_error = RuntimeError("Saldo da origem mudou desde a revisao.")
        dialog = RemanagementReviewStepDialog(service, None, _state_with_allocations())
        dialog.reason_edit.setPlainText("Motivo real")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
                patch.object(QMessageBox, "warning") as warning:
            dialog._confirm_clicked()
        warning.assert_called_once()
        self.assertIn("Saldo da origem mudou", warning.call_args[0][2])
        self.assertNotEqual(dialog.result(), QDialog.Accepted)
        # revalidou automaticamente (chamou remanagement_review de novo: 1 no
        # carregamento inicial + 1 apos o erro de confirmacao).
        self.assertEqual(len(service.calls), 2)
        self.assertTrue(dialog.confirm_button.isEnabled())

    def test_confirm_error_when_revalidation_also_fails_goes_back(self):
        service = FakeReviewService()
        service.confirm_error = RuntimeError("Conflito de concorrencia.")
        dialog = RemanagementReviewStepDialog(service, None, _state_with_allocations())
        dialog.reason_edit.setPlainText("Motivo real")
        service.destinations = []  # revalidacao pos-erro falha (destino sumiu)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), \
                patch.object(QMessageBox, "warning"):
            dialog._confirm_clicked()
        self.assertEqual(dialog.result(), RemanagementReviewStepDialog.RESULT_BACK)

    def test_operation_id_is_generated_and_stable_across_unrelated_changes(self):
        state = RemanagementFlowState()
        first_id = state.operation_id
        self.assertTrue(first_id)
        state.set_item_selections([])
        self.assertEqual(state.operation_id, first_id)

    def test_operation_id_is_regenerated_when_destination_changes(self):
        state = RemanagementFlowState()
        state.set_destination(9, 1)
        first_id = state.operation_id
        state.set_destination(10, 1)
        second_id = state.operation_id
        self.assertNotEqual(second_id, first_id)
        state.set_destination(10, 2)  # mesmo destino, so a versao mudou
        self.assertEqual(state.operation_id, second_id)

    def test_state_simulation_populated_after_load(self):
        service = FakeReviewService()
        state = _state_with_allocations()
        RemanagementReviewStepDialog(service, None, state)
        self.assertIsNotNone(state.simulation)
        self.assertTrue(state.simulation.valid)
        self.assertEqual(state.simulation.summary.product_count, 2)


if __name__ == "__main__":
    unittest.main()
