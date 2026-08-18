from __future__ import annotations

import threading
import unittest
from datetime import date
from decimal import Decimal

from app.services.nomus_batch_import import CancellationToken
from app.services.nomus_batch_persistence import (
    NomusPersistenceEventType,
    NomusPersistenceStatus,
    ProposalImportPersistenceService,
)
from app.services.proposal_import.schemas import (
    ImportedProposalData,
    ImportedProposalItem,
    ProposalImportMetadata,
    StandardProposalImportResult,
)


class FakeOfficialStorage:
    def __init__(self):
        self.existing: set[str] = set()
        self.failures: dict[str, Exception] = {}
        self.saved: list[tuple[dict, dict]] = []
        self.save_started = threading.Event()
        self.save_release: threading.Event | None = None

    def proposal_exists(self, proposal_number: str) -> bool:
        return proposal_number in self.existing

    def save_process(self, data, process_id=None, import_metadata=None):
        proposal_number = data["proposta"]
        if self.save_release is not None:
            self.save_started.set()
            self.save_release.wait(2)
        if proposal_number in self.failures:
            raise self.failures[proposal_number]
        if proposal_number in self.existing:
            raise RuntimeError("Ja existe proposta com este numero no servidor.")
        self.existing.add(proposal_number)
        self.saved.append((data, import_metadata or {}))
        return len(self.saved)


class NomusBatchPersistenceTests(unittest.TestCase):
    def test_three_valid_proposals_are_saved_with_items_and_audit_metadata(self):
        storage = FakeOfficialStorage()
        service = ProposalImportPersistenceService(storage)

        result = service.persist_batch([_prepared(5301), _prepared(5302), _prepared(5303)])

        self.assertEqual(result.counts_by_status()["SAVED"], 3)
        self.assertEqual(result.proposals_persisted, 3)
        self.assertEqual(result.persistence_failed, 0)
        self.assertGreaterEqual(result.persistence_ms, 0.0)
        self.assertEqual(result.telemetry.weight_lookup_requests, 0)
        self.assertEqual(len(storage.saved), 3)
        first_data, first_metadata = storage.saved[0]
        self.assertEqual(first_data["proposta"], "CP05301")
        self.assertEqual(first_data["itens"][0]["descricao"], "Item operacional")
        self.assertEqual(first_data["itens"][0]["peso"], "")
        self.assertEqual(first_data["_import_source"], "NOMUS_API")
        self.assertEqual(first_metadata["origem"], "NOMUS_API")
        self.assertEqual(first_metadata["extraction_method"], "nomus_api")

    def test_failure_is_isolated_and_does_not_stop_other_proposals(self):
        storage = FakeOfficialStorage()
        storage.failures["CP05302"] = RuntimeError("falha ao criar item")
        service = ProposalImportPersistenceService(storage)

        result = service.persist_batch([_prepared(5301), _prepared(5302), _prepared(5303)])

        self.assertEqual([data["proposta"] for data, _metadata in storage.saved], ["CP05301", "CP05303"])
        self.assertEqual(result.results[1].status, NomusPersistenceStatus.FAILED)
        self.assertEqual(result.results[2].status, NomusPersistenceStatus.SAVED)

    def test_duplicate_precheck_and_race_are_both_idempotent(self):
        storage = FakeOfficialStorage()
        storage.existing.add("CP05301")
        storage.failures["CP05302"] = RuntimeError("Ja existe proposta com este numero no servidor.")
        service = ProposalImportPersistenceService(storage)

        result = service.persist_batch([_prepared(5301), _prepared(5302), _prepared(5303)])

        self.assertEqual(result.results[0].status, NomusPersistenceStatus.ALREADY_EXISTS)
        self.assertEqual(result.results[1].status, NomusPersistenceStatus.ALREADY_EXISTS)
        self.assertEqual(result.results[2].status, NomusPersistenceStatus.SAVED)
        self.assertEqual([data["proposta"] for data, _metadata in storage.saved], ["CP05303"])

    def test_cancellation_after_two_stops_only_not_started_proposals(self):
        storage = FakeOfficialStorage()
        service = ProposalImportPersistenceService(storage)
        token = CancellationToken()

        def handle(event):
            if event.event_type == NomusPersistenceEventType.PROPOSAL_FINISHED and event.completed == 2:
                token.cancel()

        result = service.persist_batch(
            [_prepared(5301), _prepared(5302), _prepared(5303), _prepared(5304), _prepared(5305)],
            cancellation_token=token,
            event_callback=handle,
        )

        self.assertEqual(len(storage.saved), 2)
        self.assertEqual(result.counts_by_status()["SAVED"], 2)
        self.assertEqual(result.counts_by_status()["CANCELLED"], 3)
        self.assertEqual(result.cancelled_count, 3)
        self.assertTrue(result.cancelled)

    def test_missing_weight_is_not_blocking_and_no_product_lookup_exists(self):
        storage = FakeOfficialStorage()
        result = ProposalImportPersistenceService(storage).persist_one(_prepared(5301, weight=None))

        self.assertTrue(result.success)
        self.assertEqual(storage.saved[0][0]["itens"][0]["peso"], "")
        self.assertFalse(hasattr(storage, "get_product"))

    def test_financial_field_is_rejected_before_official_write(self):
        storage = FakeOfficialStorage()
        raw = _prepared(5301).to_dict()
        raw["proposal"]["valor_total"] = "999.00"

        result = ProposalImportPersistenceService(storage).persist_one(raw)

        self.assertEqual(result.status, NomusPersistenceStatus.FAILED)
        self.assertEqual(result.error_code, "FINANCIAL_FIELD_BLOCKED")
        self.assertEqual(storage.saved, [])

    def test_concurrent_double_submit_is_blocked_while_first_write_runs(self):
        storage = FakeOfficialStorage()
        storage.save_release = threading.Event()
        service = ProposalImportPersistenceService(storage)
        first_result = []

        thread = threading.Thread(target=lambda: first_result.append(service.persist_one(_prepared(5301))))
        thread.start()
        self.assertTrue(storage.save_started.wait(1))

        duplicate_click = service.persist_one(_prepared(5301))
        storage.save_release.set()
        thread.join(2)

        self.assertEqual(duplicate_click.status, NomusPersistenceStatus.FAILED)
        self.assertEqual(duplicate_click.error_code, "WRITE_IN_PROGRESS")
        self.assertTrue(first_result[0].success)
        self.assertEqual(len(storage.saved), 1)


def _prepared(number: int, *, weight=None) -> StandardProposalImportResult:
    return StandardProposalImportResult(
        proposal=ImportedProposalData(
            proposal_number=f"CP{number:05d}",
            proposal_date=date(2026, 8, 18),
            client=f"Cliente {number}",
            site="Obra",
            deadline_days=15,
            purchase_order=f"PC-{number}",
            lot="L1",
            operational_notes="Importacao operacional",
        ),
        items=[
            ImportedProposalItem(
                item_number=1,
                product_code="COD-1",
                description="Item operacional",
                quantity=Decimal("2"),
                unit="un",
                unit_weight=Decimal(str(weight)) if weight is not None else None,
            )
        ],
        field_confidences={},
        overall_confidence=Decimal("0.95"),
        metadata=ProposalImportMetadata(
            source="nomus_api",
            extraction_method="nomus_api",
            requires_human_review=True,
        ),
    )


if __name__ == "__main__":
    unittest.main()
