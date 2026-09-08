from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.app.backup.retention import RetentionPolicy, apply_retention


def _write_manifest(backup_dir: Path, backup_id: str, *, age_days: float, validation: str = "VALID") -> None:
    created_at = datetime.now(timezone.utc) - timedelta(days=age_days)
    dump_path = backup_dir / f"{backup_id}.dump"
    dump_path.write_bytes(b"conteudo")
    manifest_path = backup_dir / f"{backup_id}.manifest.json"
    manifest_path.write_text(
        json.dumps({
            "backup_id": backup_id,
            "created_at_utc": created_at.isoformat(),
            "validation": validation,
            "file_path": str(dump_path),
        }),
        encoding="utf-8",
    )


class ApplyRetentionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.backup_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_never_removes_the_backup_protecting_the_current_deployment(self):
        # current_backup_id e o unico backup existente, muito antigo e sozinho
        # (fora de qualquer janela de quantidade/idade) -- ainda assim protegido.
        _write_manifest(self.backup_dir, "current", age_days=400)
        removed = apply_retention(self.backup_dir, policy=RetentionPolicy(keep_last_successful=1, minimum_age_before_delete_days=0), current_backup_id="current")
        self.assertEqual(removed, [])
        self.assertTrue((self.backup_dir / "current.dump").exists())

    def test_keeps_last_n_successful_backups_regardless_of_age(self):
        for index in range(5):
            _write_manifest(self.backup_dir, f"b{index}", age_days=100 + index)
        removed = apply_retention(self.backup_dir, policy=RetentionPolicy(keep_last_successful=5, minimum_age_before_delete_days=0), current_backup_id=None)
        self.assertEqual(removed, [])

    def test_removes_backups_outside_count_window_and_past_minimum_age(self):
        for index in range(5):
            _write_manifest(self.backup_dir, f"b{index}", age_days=30 + index)
        removed = apply_retention(self.backup_dir, policy=RetentionPolicy(keep_last_successful=2, minimum_age_before_delete_days=7), current_backup_id=None)
        self.assertEqual(len(removed), 3)
        self.assertFalse((self.backup_dir / "b2.dump").exists())
        self.assertTrue((self.backup_dir / "b0.dump").exists())
        self.assertTrue((self.backup_dir / "b1.dump").exists())

    def test_does_not_remove_recent_backups_even_when_outside_count_window(self):
        for index in range(5):
            _write_manifest(self.backup_dir, f"b{index}", age_days=1 + index * 0.1)
        removed = apply_retention(self.backup_dir, policy=RetentionPolicy(keep_last_successful=1, minimum_age_before_delete_days=7), current_backup_id=None)
        self.assertEqual(removed, [])

    def test_ignores_backups_with_invalid_validation_status(self):
        _write_manifest(self.backup_dir, "bad", age_days=100, validation="INVALID")
        removed = apply_retention(self.backup_dir, policy=RetentionPolicy(keep_last_successful=0, minimum_age_before_delete_days=0), current_backup_id=None)
        self.assertEqual(removed, [])
        self.assertTrue((self.backup_dir / "bad.dump").exists())

    def test_never_touches_files_without_a_recognized_manifest(self):
        stray = self.backup_dir / "arbitrary_file.dump"
        stray.write_bytes(b"nao deveria ser tocado")
        removed = apply_retention(self.backup_dir, policy=RetentionPolicy(keep_last_successful=0, minimum_age_before_delete_days=0), current_backup_id=None)
        self.assertEqual(removed, [])
        self.assertTrue(stray.exists())

    def test_empty_directory_is_a_noop(self):
        removed = apply_retention(self.backup_dir, policy=RetentionPolicy(), current_backup_id=None)
        self.assertEqual(removed, [])

    def test_nonexistent_directory_is_a_noop(self):
        removed = apply_retention(self.backup_dir / "does-not-exist", policy=RetentionPolicy(), current_backup_id=None)
        self.assertEqual(removed, [])


if __name__ == "__main__":
    unittest.main()
