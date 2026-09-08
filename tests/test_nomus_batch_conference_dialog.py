from __future__ import annotations

import os
import unittest
from datetime import date
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.services.nomus_batch_import import (
    NomusBatchImportResult,
    NomusBatchMetrics,
    NomusBatchTargetResult,
    NomusBatchTargetState,
)
from app.services.nomus_batch_persistence import NomusPersistenceStatus, ProposalImportPersistenceService
from app.services.proposal_import.schemas import (
    ImportedProposalData,
    ImportedProposalItem,
    ProposalImportMetadata,
    StandardProposalImportResult,
)
from app.ui.nomus_batch_conference_dialog import NomusBatchConferenceDialog


class FakeStorage:
    def __init__(self):
        self.saved: list[str] = []
        self.fail_once: set[str] = set()

    def proposal_exists(self, proposal_number):
        return proposal_number in self.saved

    def save_process(self, data, process_id=None, import_metadata=None):
        proposal = data["proposta"]
        if proposal in self.fail_once:
            self.fail_once.remove(proposal)
            raise RuntimeError("falha controlada")
        self.saved.append(proposal)
        return len(self.saved)


class NomusBatchConferenceDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_only_ready_rows_start_selected_and_can_be_checked(self):
        dialog = self._dialog(_batch_with_mixed_states())
        try:
            self.assertTrue(dialog.model.rows[0].selected)
            self.assertTrue(dialog.model.rows[0].eligible)
            self.assertFalse(dialog.model.rows[1].eligible)
            self.assertFalse(dialog.model.rows[2].eligible)
            self.assertTrue(dialog.model.flags(dialog.model.index(0, 0)) & Qt.ItemIsUserCheckable)
            self.assertFalse(dialog.model.flags(dialog.model.index(1, 0)) & Qt.ItemIsUserCheckable)
            self.assertIn("Gravar 1 proposta", dialog.save_button.text())
            self.assertEqual(dialog.conference_metrics.proposal_count, 3)
            self.assertGreaterEqual(dialog.conference_metrics.conference_ms, 0.0)
        finally:
            dialog.close()

    def test_selection_controls_disable_save_when_cleared(self):
        dialog = self._dialog(_batch_with_mixed_states())
        try:
            dialog.model.select_eligible(False)
            self.assertFalse(dialog.save_button.isEnabled())
            dialog.model.select_eligible(True)
            self.assertTrue(dialog.save_button.isEnabled())
        finally:
            dialog.close()

    def test_save_updates_progress_and_does_not_persist_ineligible_rows(self):
        storage = FakeStorage()
        dialog = self._dialog(_batch_with_mixed_states(), storage)
        try:
            dialog.start_persistence()

            self.assertEqual(storage.saved, ["CP05301"])
            self.assertEqual(dialog.progress_bar.value(), 100)
            self.assertEqual(dialog.model.rows[0].persistence_status, NomusPersistenceStatus.SAVED)
            self.assertIn("Gravadas: 1", dialog.summary_label.text())
        finally:
            dialog.close()

    def test_retry_persists_only_previous_write_failures(self):
        storage = FakeStorage()
        storage.fail_once.add("CP05301")
        batch = NomusBatchImportResult(
            [_target(5301, NomusBatchTargetState.READY), _target(5302, NomusBatchTargetState.READY)],
            NomusBatchMetrics(),
        )
        dialog = self._dialog(batch, storage)
        try:
            dialog.start_persistence()
            self.assertEqual(storage.saved, ["CP05302"])
            self.assertTrue(dialog.retry_button.isEnabled())

            dialog.retry_failed()

            self.assertEqual(storage.saved, ["CP05302", "CP05301"])
            self.assertEqual(storage.saved.count("CP05302"), 1)
            self.assertFalse(dialog.retry_button.isEnabled())
        finally:
            dialog.close()

    def test_details_show_items_and_missing_weight_without_blocking(self):
        dialog = self._dialog(_batch_with_mixed_states())
        try:
            dialog.table.selectRow(0)
            dialog._show_row_details(dialog.model.index(0, 0), dialog.model.index(0, 0))

            self.assertEqual(dialog.detail_labels["client"].text(), "Cliente 5301")
            self.assertEqual(dialog.items_table.rowCount(), 1)
            self.assertEqual(dialog.items_table.item(0, 4).text(), "Nao informado")
        finally:
            dialog.close()

    def _dialog(self, batch, storage=None):
        storage = storage or FakeStorage()
        return NomusBatchConferenceDialog(
            batch,
            storage,
            persistence_service_factory=lambda: ProposalImportPersistenceService(storage),
            synchronous=True,
        )


def _batch_with_mixed_states():
    return NomusBatchImportResult(
        [
            _target(5301, NomusBatchTargetState.READY),
            _target(5302, NomusBatchTargetState.ALREADY_EXISTS, prepared=False),
            _target(5303, NomusBatchTargetState.FAILED, prepared=False),
        ],
        NomusBatchMetrics(),
    )


def _target(number: int, state: NomusBatchTargetState, *, prepared=True):
    return NomusBatchTargetResult(
        raw_input=f"CP{number:05d}",
        index=number,
        state=state,
        canonical_identifier=f"CP{number:05d}",
        proposal_number=number,
        error="Falha de consulta" if state == NomusBatchTargetState.FAILED else None,
        prepared_result=_prepared(number) if prepared else None,
    )


def _prepared(number: int):
    return StandardProposalImportResult(
        proposal=ImportedProposalData(
            proposal_number=f"CP{number:05d}",
            proposal_date=date(2026, 8, 18),
            client=f"Cliente {number}",
        ),
        items=[
            ImportedProposalItem(
                item_number=1,
                product_code="COD",
                description="Item",
                quantity=Decimal("1"),
                unit="un",
            )
        ],
        field_confidences={},
        overall_confidence=Decimal("1"),
        metadata=ProposalImportMetadata(source="nomus_api", extraction_method="nomus_api"),
    )


if __name__ == "__main__":
    unittest.main()
