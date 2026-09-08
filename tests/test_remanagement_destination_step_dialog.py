from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.ui.components.modern_button import ModernButton
from app.ui.early_remanagement_dialog import EarlyRemanagementDeliveryDialog
from app.ui.remanagement_destination_step_dialog import RemanagementDestinationStepDialog


class FakeRemanagementService:
    def __init__(self):
        self.destinations = [
            {"id": 1, "proposta": "CP05385", "cliente": "MNS Engenharia", "obra_site": "MSN Obra 1", "status_expedicao": "SEPARADO", "api_version": 3},
            {"id": 2, "proposta": "CP05401", "cliente": "MNS Comercio", "obra_site": "MSR Obra 2", "status_expedicao": "PENDENTE", "api_version": 7},
        ]

    def early_delivery_destination_candidates(self, search: str = ""):
        text = (search or "").strip().upper()
        return [
            row for row in self.destinations
            if not text or text in row["proposta"].upper() or text in row["cliente"].upper() or text in row["obra_site"].upper()
        ]

    def remanagement_source_candidates(self, exclude_process_id=None, search=""):
        return []

    def remanagement_compatible_items(self, source_id, destination_id):
        raise AssertionError("nao deve ser chamado sem uma origem selecionada")


class RemanagementDestinationStepDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_lists_eligible_destinations(self):
        dialog = RemanagementDestinationStepDialog(FakeRemanagementService())
        self.assertEqual(dialog.table.rowCount(), 2)

    def test_search_filters_by_proposal_client_and_site(self):
        dialog = RemanagementDestinationStepDialog(FakeRemanagementService())
        dialog.search.setText("05401")
        self.assertEqual(dialog.table.rowCount(), 1)
        dialog.search.setText("Comercio")
        self.assertEqual(dialog.table.rowCount(), 1)
        dialog.search.setText("Obra 1")
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertEqual(dialog.table.item(0, 0).data(Qt.UserRole), 1)

    def test_advance_disabled_without_selection(self):
        dialog = RemanagementDestinationStepDialog(FakeRemanagementService())
        self.assertFalse(dialog.advance_button.isEnabled())
        self.assertIsNone(dialog.state.destination_proposal_id)

    def test_selecting_row_updates_state_and_summary(self):
        dialog = RemanagementDestinationStepDialog(FakeRemanagementService())
        dialog.table.selectRow(1)
        self.assertEqual(dialog.state.destination_proposal_id, 2)
        self.assertEqual(dialog.state.destination_version, 7)
        self.assertIn("CP05401", dialog.summary_label.text())
        self.assertTrue(dialog.advance_button.isEnabled())

    def test_switching_selection_replaces_destination_id(self):
        dialog = RemanagementDestinationStepDialog(FakeRemanagementService())
        dialog.table.selectRow(0)
        self.assertEqual(dialog.state.destination_proposal_id, 1)
        dialog.table.selectRow(1)
        self.assertEqual(dialog.state.destination_proposal_id, 2)

    def test_selection_survives_filter_roundtrip(self):
        dialog = RemanagementDestinationStepDialog(FakeRemanagementService())
        dialog.table.selectRow(1)
        self.assertEqual(dialog.state.destination_proposal_id, 2)
        dialog.search.setText("CP")
        self.assertEqual(dialog.table.rowCount(), 2)
        self.assertEqual(dialog.state.destination_proposal_id, 2)

    def test_initial_destination_id_preselects_row(self):
        dialog = RemanagementDestinationStepDialog(FakeRemanagementService(), initial_destination_id=2)
        self.assertEqual(dialog.state.destination_proposal_id, 2)

    def test_advance_accepts_with_valid_destination(self):
        dialog = RemanagementDestinationStepDialog(FakeRemanagementService())
        dialog.table.selectRow(0)
        dialog._advance()
        self.assertEqual(dialog.result(), QDialog.Accepted)

    def test_advance_revalidates_and_blocks_removed_destination(self):
        service = FakeRemanagementService()
        dialog = RemanagementDestinationStepDialog(service)
        dialog.table.selectRow(0)
        service.destinations.pop(0)
        with patch.object(QMessageBox, "warning", return_value=None):
            dialog._advance()
        self.assertNotEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(dialog.table.rowCount(), 1)

    def test_cancel_writes_nothing_and_rejects(self):
        dialog = RemanagementDestinationStepDialog(FakeRemanagementService())
        dialog.table.selectRow(0)
        dialog.reject()
        self.assertEqual(dialog.result(), QDialog.Rejected)


class RemanagementLegacyBridgeTests(unittest.TestCase):
    """A Fase 1 preserva o fluxo legado como ponte temporaria: a nova Etapa 1
    entrega o destino ja escolhido para `EarlyRemanagementDeliveryDialog`, que
    trava a selecao e deixa origem/mapeamento/simulacao/confirmacao intactos."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_preselected_destination_locks_selection(self):
        dialog = EarlyRemanagementDeliveryDialog(FakeRemanagementService(), preselected_destination_id=2)
        self.assertEqual(EarlyRemanagementDeliveryDialog._selected_id(dialog.dest_table), 2)
        self.assertFalse(dialog.dest_table.isEnabled())
        self.assertFalse(dialog.dest_search.isEnabled())

    def test_without_preselection_destination_stays_editable(self):
        dialog = EarlyRemanagementDeliveryDialog(FakeRemanagementService())
        self.assertIsNone(EarlyRemanagementDeliveryDialog._selected_id(dialog.dest_table))
        self.assertTrue(dialog.dest_table.isEnabled())
        self.assertTrue(dialog.dest_search.isEnabled())

    def test_voltar_button_only_shown_when_bridged(self):
        bridged = EarlyRemanagementDeliveryDialog(FakeRemanagementService(), preselected_destination_id=1)
        direct = EarlyRemanagementDeliveryDialog(FakeRemanagementService())
        self.assertIn("Voltar", [b.text() for b in bridged.findChildren(ModernButton)])
        self.assertNotIn("Voltar", [b.text() for b in direct.findChildren(ModernButton)])

    def test_voltar_click_returns_custom_result_code_without_writing(self):
        dialog = EarlyRemanagementDeliveryDialog(FakeRemanagementService(), preselected_destination_id=1)
        back = next(b for b in dialog.findChildren(ModernButton) if b.text() == "Voltar")
        back.click()
        self.assertEqual(dialog.result(), EarlyRemanagementDeliveryDialog.RESULT_BACK)


if __name__ == "__main__":
    unittest.main()
