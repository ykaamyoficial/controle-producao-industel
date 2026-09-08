from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.app.backup.lock import BackupLock, BackupLockError


class BackupLockTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.lock_path = Path(self._tmp.name) / "backup.lock"

    def tearDown(self):
        self._tmp.cleanup()

    def test_acquires_and_releases_cleanly(self):
        with BackupLock(self.lock_path, timeout_seconds=60):
            self.assertTrue(self.lock_path.exists())
        self.assertFalse(self.lock_path.exists())

    def test_second_concurrent_acquire_fails_with_explicit_error(self):
        lock_a = BackupLock(self.lock_path, timeout_seconds=60)
        lock_a.__enter__()
        try:
            with self.assertRaises(BackupLockError):
                BackupLock(self.lock_path, timeout_seconds=60).__enter__()
        finally:
            lock_a.release()

    def test_release_is_idempotent(self):
        lock = BackupLock(self.lock_path, timeout_seconds=60)
        lock.__enter__()
        lock.release()
        lock.release()  # nao pode levantar
        self.assertFalse(self.lock_path.exists())

    def test_fresh_lock_is_never_treated_as_abandoned(self):
        with BackupLock(self.lock_path, timeout_seconds=3600):
            with self.assertRaises(BackupLockError):
                BackupLock(self.lock_path, timeout_seconds=3600).__enter__()

    def test_expired_lock_is_recovered_explicitly_not_silently(self):
        # simula um lock antigo, deixado por um processo que morreu
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=120)
        self.lock_path.write_text(json.dumps({"owner": "x", "pid": 1, "acquired_at_utc": stale_time.isoformat()}), encoding="utf-8")

        with BackupLock(self.lock_path, timeout_seconds=60):
            self.assertTrue(self.lock_path.exists())

    def test_corrupted_lock_file_is_treated_as_active_never_removed_blindly(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.write_text("isto nao e json valido", encoding="utf-8")

        with self.assertRaises(BackupLockError):
            BackupLock(self.lock_path, timeout_seconds=1).__enter__()
        # o conteudo corrompido permanece -- nao foi apagado as cegas
        self.assertEqual(self.lock_path.read_text(encoding="utf-8"), "isto nao e json valido")

    def test_lock_file_records_owner_pid_and_timestamp_for_diagnostics(self):
        with BackupLock(self.lock_path, timeout_seconds=60, owner="predeployment-backup"):
            payload = json.loads(self.lock_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["owner"], "predeployment-backup")
            self.assertIn("pid", payload)
            self.assertIn("acquired_at_utc", payload)


if __name__ == "__main__":
    unittest.main()
