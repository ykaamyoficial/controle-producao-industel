from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from api.app.audit.models import ActorType, AuditEventType, Component, EventResult, EventSeverity, UpdateAuditEvent
from api.app.audit.spool import AuditSpool


def _event(event_id: str | None = None) -> UpdateAuditEvent:
    kwargs = dict(
        event_type=AuditEventType.DEPLOYMENT_STARTED, severity=EventSeverity.INFO,
        actor_type=ActorType.DEPLOY_RUNNER, component=Component.DEPLOYMENT,
        result=EventResult.STARTED, message="deploy iniciado",
    )
    if event_id is not None:
        kwargs["event_id"] = event_id
    return UpdateAuditEvent(**kwargs)


class AuditSpoolTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.spool = AuditSpool(
            pending_dir=self.dir / "pending", processed_dir=self.dir / "processed", failed_dir=self.dir / "failed",
        )


class WritePendingTests(AuditSpoolTestCase):
    def test_write_pending_persists_the_event_as_json_readable_back(self):
        event = _event()
        self.spool.write_pending(event)
        pending = self.spool.list_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].event_id, event.event_id)

    def test_pending_count_reflects_number_of_files(self):
        self.spool.write_pending(_event())
        self.spool.write_pending(_event())
        self.assertEqual(self.spool.pending_count(), 2)

    def test_pending_count_is_zero_when_directory_does_not_exist_yet(self):
        self.assertEqual(self.spool.pending_count(), 0)


class MarkProcessedTests(AuditSpoolTestCase):
    def test_mark_processed_moves_file_from_pending_to_processed(self):
        event = _event()
        self.spool.write_pending(event)
        self.spool.mark_processed(event.event_id)
        self.assertEqual(self.spool.list_pending(), [])
        processed = self.spool.list_processed()
        self.assertEqual(len(processed), 1)
        self.assertEqual(processed[0].event_id, event.event_id)

    def test_mark_processed_for_unknown_event_id_is_a_harmless_noop(self):
        self.spool.mark_processed("does-not-exist")
        self.assertEqual(self.spool.list_pending(), [])
        self.assertEqual(self.spool.list_processed(), [])


class MarkFailedTests(AuditSpoolTestCase):
    def test_mark_failed_moves_file_from_pending_to_failed(self):
        event = _event()
        self.spool.write_pending(event)
        self.spool.mark_failed(event.event_id)
        self.assertEqual(self.spool.list_pending(), [])
        self.assertEqual(len(self.spool.list_failed()), 1)

    def test_transient_failure_does_not_use_mark_failed_event_stays_pending(self):
        # Simula o padrao real (service.drain_spool_to_database): uma falha
        # transitoria de banco NUNCA chama mark_failed, so deixa o arquivo em
        # pending para a proxima tentativa.
        event = _event()
        self.spool.write_pending(event)
        self.assertEqual(len(self.spool.list_pending()), 1)


class CorruptedEntryTests(AuditSpoolTestCase):
    def test_corrupted_pending_file_is_moved_to_failed_without_blocking_others(self):
        good_event = _event()
        self.spool.write_pending(good_event)
        pending_dir = self.dir / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / "corrupted.json").write_text("{ nao e json valido", encoding="utf-8")

        pending = self.spool.list_pending()

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].event_id, good_event.event_id)
        self.assertTrue((self.dir / "failed" / "corrupted.json").exists())
        self.assertFalse((pending_dir / "corrupted.json").exists())

    def test_json_missing_required_key_is_quarantined(self):
        pending_dir = self.dir / "pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / "incomplete.json").write_text(json.dumps({"event_id": "x"}), encoding="utf-8")

        pending = self.spool.list_pending()

        self.assertEqual(pending, [])
        self.assertTrue((self.dir / "failed" / "incomplete.json").exists())


if __name__ == "__main__":
    unittest.main()
