from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.updater.lock import UpdaterLock, UpdaterLockError


class UpdaterLockTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.lock_path = Path(self._tmp.name) / ".updater.lock"

    def test_acquire_and_release(self):
        with UpdaterLock(self.lock_path, timeout_seconds=60):
            self.assertTrue(self.lock_path.exists())
        self.assertFalse(self.lock_path.exists())

    def test_second_concurrent_acquire_fails(self):
        # dois Updaters nao aplicam update simultaneamente (Secao 29).
        first = UpdaterLock(self.lock_path, timeout_seconds=60)
        first._acquire()
        try:
            with self.assertRaises(UpdaterLockError):
                UpdaterLock(self.lock_path, timeout_seconds=60)._acquire()
        finally:
            first.release()

    def test_stale_lock_is_recovered(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.lock_path.write_text(f'{{"owner": "old", "pid": 1, "hostname": "h", "acquired_at_utc": "{old_time}"}}', encoding="utf-8")
        with UpdaterLock(self.lock_path, timeout_seconds=60):
            self.assertTrue(self.lock_path.exists())

    def test_corrupted_lock_is_treated_as_active(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text("not valid json", encoding="utf-8")
        with self.assertRaises(UpdaterLockError):
            UpdaterLock(self.lock_path, timeout_seconds=60)._acquire()


if __name__ == "__main__":
    unittest.main()
