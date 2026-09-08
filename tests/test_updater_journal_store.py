from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.updater.contract import UpdateJournal, UpdateState
from app.updater.journal_store import UpdateJournalStore

NOW = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)


def _journal(**overrides) -> UpdateJournal:
    base = dict(
        request_id="req-1", current_version="1.0.0", target_version="1.1.0", state=UpdateState.REQUESTED,
        staging_path="/staging/req-1", backup_path="/backup/req-1", started_at=NOW, last_step="REQUESTED",
    )
    base.update(overrides)
    return UpdateJournal(**base)


class UpdateJournalStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = UpdateJournalStore(Path(self._tmp.name))

    def test_save_then_load_round_trips(self):
        journal = _journal()
        self.store.save(journal)
        self.assertEqual(self.store.load("req-1"), journal)

    def test_load_missing_returns_none(self):
        self.assertIsNone(self.store.load("nope"))

    def test_list_all_sorted_by_started_at(self):
        older = _journal(request_id="a", started_at=NOW)
        newer = _journal(request_id="b", started_at=NOW + timedelta(hours=1))
        self.store.save(newer)
        self.store.save(older)
        self.assertEqual([j.request_id for j in self.store.list_all()], ["a", "b"])

    def test_latest_returns_most_recent(self):
        self.store.save(_journal(request_id="a", started_at=NOW))
        self.store.save(_journal(request_id="b", started_at=NOW + timedelta(hours=1)))
        self.assertEqual(self.store.latest().request_id, "b")

    def test_latest_incomplete_skips_terminal_states(self):
        self.store.save(_journal(request_id="a", started_at=NOW, state=UpdateState.SUCCESS))
        self.store.save(_journal(request_id="b", started_at=NOW + timedelta(hours=1), state=UpdateState.APPLYING))
        incomplete = self.store.latest_incomplete()
        self.assertEqual(incomplete.request_id, "b")

    def test_latest_incomplete_returns_none_when_all_terminal(self):
        self.store.save(_journal(request_id="a", state=UpdateState.SUCCESS))
        self.store.save(_journal(request_id="b", started_at=NOW + timedelta(hours=1), state=UpdateState.ROLLED_BACK))
        self.assertIsNone(self.store.latest_incomplete())

    def test_corrupted_file_is_skipped(self):
        self.store.save(_journal())
        (Path(self._tmp.name) / "corrupted.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(len(self.store.list_all()), 1)


if __name__ == "__main__":
    unittest.main()
