from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from api.app.maintenance.exceptions import MaintenanceStateCorruptedError
from api.app.maintenance.models import MaintenanceReasonCode, MaintenanceState, MaintenanceStateName
from api.app.maintenance.store import MaintenanceStateStore


def _state(**overrides) -> MaintenanceState:
    base = MaintenanceState(
        state=MaintenanceStateName.ACTIVE,
        maintenance_id="mnt-20260812-000001",
        reason_code=MaintenanceReasonCode.DEPLOYMENT,
        message="Deploy em andamento.",
        policy_revision=1,
        updated_at=datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc),
    )
    return base.replace(**overrides) if overrides else base


class MaintenanceStateStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "maintenance.json"
        self.store = MaintenanceStateStore(self.path)

    def test_load_returns_none_when_file_does_not_exist_yet(self):
        self.assertIsNone(self.store.load())

    def test_save_then_load_round_trips(self):
        state = _state()
        self.store.save(state)
        self.assertEqual(self.store.load(), state)

    def test_save_writes_atomically_no_leftover_tmp_files(self):
        self.store.save(_state())
        leftovers = list(self.path.parent.glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_save_also_writes_backup_of_last_valid_state(self):
        state = _state()
        self.store.save(state)
        backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        self.assertTrue(backup_path.exists())
        self.assertEqual(self.store.load_last_valid_backup(), state)

    def test_load_raises_on_corrupted_json_never_returns_none_or_off(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{ nao e json valido", encoding="utf-8")

        with self.assertRaises(MaintenanceStateCorruptedError):
            self.store.load()

    def test_load_raises_when_root_is_not_an_object(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("[1, 2, 3]", encoding="utf-8")

        with self.assertRaises(MaintenanceStateCorruptedError):
            self.store.load()

    def test_load_raises_when_required_field_missing(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text('{"state": "ACTIVE"}', encoding="utf-8")

        with self.assertRaises(MaintenanceStateCorruptedError):
            self.store.load()

    def test_corrupted_current_file_does_not_touch_existing_backup(self):
        good_state = _state()
        self.store.save(good_state)
        self.path.write_text("{ corrompido", encoding="utf-8")

        with self.assertRaises(MaintenanceStateCorruptedError):
            self.store.load()
        self.assertEqual(self.store.load_last_valid_backup(), good_state)

    def test_second_save_overwrites_previous_state_completely(self):
        self.store.save(_state(policy_revision=1))
        self.store.save(_state(policy_revision=2, message="Segunda escrita"))
        loaded = self.store.load()
        self.assertEqual(loaded.policy_revision, 2)
        self.assertEqual(loaded.message, "Segunda escrita")


if __name__ == "__main__":
    unittest.main()
