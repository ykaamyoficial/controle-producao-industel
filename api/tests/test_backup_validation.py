from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from api.app.backup.models import ValidationStatus
from api.app.backup.validation import BackupValidator


class BackupValidatorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.backup_dir = Path(self._tmp.name)
        self.validator = BackupValidator(pg_restore_path="pg_restore", timeout_seconds=5)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_is_invalid_without_calling_pg_restore(self):
        outcome = self.validator.validate(self.backup_dir / "nao-existe.dump")
        self.assertEqual(outcome.status, ValidationStatus.INVALID)

    def test_empty_file_is_invalid_without_calling_pg_restore(self):
        path = self.backup_dir / "vazio.dump"
        path.write_bytes(b"")
        with patch("api.app.backup.validation.subprocess.run") as run:
            outcome = self.validator.validate(path)
        run.assert_not_called()
        self.assertEqual(outcome.status, ValidationStatus.INVALID)

    def test_pg_restore_not_found_is_unknown_not_invalid(self):
        path = self.backup_dir / "presente.dump"
        path.write_bytes(b"conteudo")
        with patch("api.app.backup.validation.shutil.which", return_value=None):
            outcome = self.validator.validate(path)
        self.assertEqual(outcome.status, ValidationStatus.UNKNOWN)

    def test_pg_restore_nonzero_exit_is_invalid(self):
        path = self.backup_dir / "corrompido.dump"
        path.write_bytes(b"conteudo-nao-e-um-dump-de-verdade")
        with patch("api.app.backup.validation.shutil.which", return_value="/usr/bin/pg_restore"), \
             patch("api.app.backup.validation.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stdout = b""
            run.return_value.stderr = b"input file does not appear to be a valid archive"
            outcome = self.validator.validate(path)
        self.assertEqual(outcome.status, ValidationStatus.INVALID)
        self.assertIn("valid archive", outcome.detail)

    def test_pg_restore_empty_listing_is_invalid(self):
        path = self.backup_dir / "sem-objetos.dump"
        path.write_bytes(b"conteudo")
        with patch("api.app.backup.validation.shutil.which", return_value="/usr/bin/pg_restore"), \
             patch("api.app.backup.validation.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = b"   "
            run.return_value.stderr = b""
            outcome = self.validator.validate(path)
        self.assertEqual(outcome.status, ValidationStatus.INVALID)

    def test_pg_restore_success_with_listing_is_valid(self):
        path = self.backup_dir / "valido.dump"
        path.write_bytes(b"conteudo")
        with patch("api.app.backup.validation.shutil.which", return_value="/usr/bin/pg_restore"), \
             patch("api.app.backup.validation.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = b"3436; 1259 16400 TABLE public users controle_dev\n"
            run.return_value.stderr = b""
            outcome = self.validator.validate(path)
        self.assertEqual(outcome.status, ValidationStatus.VALID)

    def test_timeout_is_unknown(self):
        path = self.backup_dir / "lento.dump"
        path.write_bytes(b"conteudo")
        with patch("api.app.backup.validation.shutil.which", return_value="/usr/bin/pg_restore"), \
             patch("api.app.backup.validation.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pg_restore", timeout=5)):
            outcome = self.validator.validate(path)
        self.assertEqual(outcome.status, ValidationStatus.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
