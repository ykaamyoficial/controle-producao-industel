from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.updater.swap import SwapError, apply_swap, demote_to_backup, promote_staging, rollback_swap


class SwapTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.install = self.tmp / "install"
        self.install.mkdir()
        (self.install / "old.exe").write_text("old")
        self.staging = self.tmp / "staging"
        self.staging.mkdir()
        (self.staging / "new.exe").write_text("new")
        self.backup = self.tmp / "backup"

    def test_apply_swap_promotes_staging_and_creates_backup(self):
        apply_swap(install_dir=self.install, staging_dir=self.staging, backup_dir=self.backup)
        self.assertEqual((self.install / "new.exe").read_text(), "new")
        self.assertEqual((self.backup / "old.exe").read_text(), "old")
        self.assertFalse(self.staging.exists())

    def test_apply_swap_fails_when_backup_dir_already_exists(self):
        self.backup.mkdir()
        with self.assertRaises(SwapError):
            apply_swap(install_dir=self.install, staging_dir=self.staging, backup_dir=self.backup)
        # nada deve ter sido tocado
        self.assertTrue((self.install / "old.exe").exists())

    def test_promote_failure_restores_backup_automatically(self):
        demote_to_backup(install_dir=self.install, backup_dir=self.backup)
        self.assertFalse(self.install.exists())
        # staging_dir inexistente forca falha na promocao
        missing_staging = self.tmp / "does-not-exist"
        with self.assertRaises(SwapError):
            promote_staging(staging_dir=missing_staging, install_dir=self.install, backup_dir=self.backup)
        # install_dir deve ter sido restaurado automaticamente a partir do backup
        self.assertTrue((self.install / "old.exe").exists())

    def test_rollback_swap_restores_backup_and_quarantines_current(self):
        apply_swap(install_dir=self.install, staging_dir=self.staging, backup_dir=self.backup)
        quarantine = rollback_swap(install_dir=self.install, backup_dir=self.backup)
        self.assertEqual((self.install / "old.exe").read_text(), "old")
        self.assertIsNotNone(quarantine)
        self.assertEqual((quarantine / "new.exe").read_text(), "new")

    def test_rollback_swap_without_backup_raises(self):
        with self.assertRaises(SwapError):
            rollback_swap(install_dir=self.install, backup_dir=self.tmp / "no-such-backup")


if __name__ == "__main__":
    unittest.main()
