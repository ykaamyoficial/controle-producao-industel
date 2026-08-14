from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from api.app.updates.models import ArtifactInfo, ReleaseRecord, ReleaseState
from api.app.updates.state_store import ReleaseStateStore


def _record(version: str = "2.6.0", state: ReleaseState = ReleaseState.READY) -> ReleaseRecord:
    now = datetime.now(UTC)
    return ReleaseRecord(
        version=version, state=state, manifest_schema_version=1, channel="production",
        minimum_server_version="0.8.0", api_contract_version="v1",
        artifact=ArtifactInfo(filename="Setup.exe", size_bytes=10, sha256="a" * 64),
        manifest={"release_version": version}, source="test", created_at=now, updated_at=now,
    )


class ReleaseStateStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = ReleaseStateStore(Path(self._tmp.name))

    def test_returns_none_for_missing_version(self):
        self.assertIsNone(self.store.load("9.9.9"))

    def test_save_then_load_round_trips(self):
        record = _record()
        self.store.save(record)
        loaded = self.store.load("2.6.0")
        self.assertEqual(loaded.version, "2.6.0")
        self.assertEqual(loaded.state, ReleaseState.READY)
        self.assertEqual(loaded.artifact.sha256, "a" * 64)

    def test_save_overwrites_same_version(self):
        self.store.save(_record(state=ReleaseState.READY))
        self.store.save(_record(state=ReleaseState.AUTHORIZED))
        self.assertEqual(self.store.load("2.6.0").state, ReleaseState.AUTHORIZED)

    def test_list_all_orders_by_created_at(self):
        older = _record(version="2.5.0")
        newer = _record(version="2.6.0").replace(created_at=older.created_at.replace(year=older.created_at.year + 1))
        self.store.save(newer)
        self.store.save(older)
        versions = [record.version for record in self.store.list_all()]
        self.assertEqual(versions, ["2.5.0", "2.6.0"])

    def test_corrupted_file_is_skipped_not_raised(self):
        self.store.save(_record())
        bad_path = Path(self._tmp.name) / "corrupted.json"
        bad_path.write_text("{not valid json", encoding="utf-8")
        records = self.store.list_all()
        self.assertEqual(len(records), 1)

    def test_load_missing_directory_returns_none(self):
        missing_store = ReleaseStateStore(Path(self._tmp.name) / "nonexistent")
        self.assertIsNone(missing_store.load("2.6.0"))
        self.assertEqual(missing_store.list_all(), [])


if __name__ == "__main__":
    unittest.main()
