from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from api.app.backup.connection import PgConnectionParams
from api.app.backup.lock import BackupLock
from api.app.backup.models import BackupStatus, ValidationStatus
from api.app.backup.service import PreDeploymentBackupService
from api.app.core.config import Settings


def _fake_connection(*, password: str = "controle_dev") -> PgConnectionParams:
    return PgConnectionParams(host="127.0.0.1", port=55432, user="controle_dev", password=password, dbname="controle_producao_test")


def _settings(**overrides) -> Settings:
    # PG_DUMP_PATH/PG_RESTORE_PATH sao fixados aqui (nao apenas via default do
    # campo) para o teste nao depender/vazar do ambiente real do host -- o fake
    # de subprocess abaixo reconhece literalmente "pg_dump"/"pg_restore".
    base = dict(
        DATABASE_URL="postgresql+asyncpg://controle_dev:controle_dev@127.0.0.1:55432/controle_producao_test",
        SECRET_KEY="x" * 32,
        PG_DUMP_PATH="pg_dump",
        PG_RESTORE_PATH="pg_restore",
        BACKUP_TIMEOUT_SECONDS=5,
        BACKUP_MIN_FREE_SPACE_MB=0,
        BACKUP_LOCK_TIMEOUT_SECONDS=5,
        BACKUP_RETENTION_KEEP_LAST_SUCCESSFUL=10,
        BACKUP_RETENTION_MINIMUM_AGE_DAYS=7,
    )
    base.update(overrides)
    return Settings(**base)


def _fake_subprocess_run(
    *,
    dump_returncode: int = 0,
    dump_stderr: bytes = b"",
    dump_content: bytes = b"conteudo-do-dump",
    restore_returncode: int = 0,
    restore_stdout: bytes = b"1; 1259 16400 TABLE public users controle_dev\n",
    restore_stderr: bytes = b"",
):
    def _run(args, **kwargs):
        result = MagicMock()
        command = args[0]
        if command == "pg_dump":
            file_arg = next(a for a in args if a.startswith("--file="))
            file_path = Path(file_arg.split("=", 1)[1])
            result.returncode = dump_returncode
            result.stdout = b""
            result.stderr = dump_stderr
            if dump_returncode == 0:
                file_path.write_bytes(dump_content)
            return result
        if command == "pg_restore":
            result.returncode = restore_returncode
            result.stdout = restore_stdout
            result.stderr = restore_stderr
            return result
        raise AssertionError(f"comando inesperado em teste: {args}")

    return _run


class PreDeploymentBackupServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.backup_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _service(self, *, connection: PgConnectionParams | None = None, **settings_overrides) -> PreDeploymentBackupService:
        return PreDeploymentBackupService(
            settings=_settings(**settings_overrides),
            connection=connection or _fake_connection(),
            backup_dir=self.backup_dir,
        )

    def _run(self, service, *, run_fn=None, which_result: str | None = "/usr/bin/pg_dump", **kwargs):
        run_fn = run_fn or _fake_subprocess_run()
        with patch("shutil.which", return_value=which_result), \
             patch("api.app.backup.service.subprocess.run", side_effect=run_fn), \
             patch("api.app.backup.validation.subprocess.run", side_effect=run_fn):
            kwargs.setdefault("database_revision", "20260810_0015")
            return service.run(**kwargs)

    def test_happy_path_returns_success_with_all_fields(self):
        service = self._service()
        result = self._run(service)

        self.assertEqual(result.status, BackupStatus.SUCCESS)
        self.assertEqual(result.validation_status, ValidationStatus.VALID)
        self.assertTrue(result.is_usable_for_deployment)
        self.assertIsNotNone(result.file_path)
        self.assertTrue(Path(result.file_path).exists())
        self.assertGreater(result.size_bytes, 0)
        self.assertEqual(len(result.sha256), 64)
        self.assertEqual(result.database_name, "controle_producao_test")
        self.assertEqual(result.database_revision, "20260810_0015")

        manifest_path = self.backup_dir / f"{result.backup_id}.manifest.json"
        self.assertTrue(manifest_path.exists())

    def test_manifest_never_contains_the_password(self):
        service = self._service(connection=_fake_connection(password="s3nha-secreta-unica"))
        result = self._run(service)
        manifest_text = (self.backup_dir / f"{result.backup_id}.manifest.json").read_text(encoding="utf-8")
        self.assertNotIn("s3nha-secreta-unica", manifest_text)

    def test_fails_when_pg_dump_exit_code_nonzero(self):
        service = self._service()
        result = self._run(service, run_fn=_fake_subprocess_run(dump_returncode=1, dump_stderr=b"connection refused"))
        self.assertEqual(result.status, BackupStatus.FAILED)
        self.assertEqual(result.error_code, "PG_DUMP_FAILED")
        self.assertFalse(result.is_usable_for_deployment)

    def test_fails_when_pg_dump_binary_not_found(self):
        service = self._service()
        result = self._run(service, which_result=None)
        self.assertEqual(result.status, BackupStatus.FAILED)
        self.assertEqual(result.error_code, "PG_DUMP_NOT_FOUND")

    def test_fails_when_dump_file_not_created_despite_zero_exit(self):
        service = self._service()

        def run_fn(args, **kwargs):
            result = MagicMock()
            if args[0] == "pg_dump":
                result.returncode = 0
                result.stdout = b""
                result.stderr = b""
                return result  # nao cria o arquivo, mesmo com exit code 0
            raise AssertionError("pg_restore nao deveria ser chamado quando o arquivo nao existe")

        result = self._run(service, run_fn=run_fn)
        self.assertEqual(result.status, BackupStatus.FAILED)
        self.assertEqual(result.error_code, "VALIDATION_FAILED")

    def test_fails_when_dump_file_has_zero_size(self):
        service = self._service()
        result = self._run(service, run_fn=_fake_subprocess_run(dump_content=b""))
        self.assertEqual(result.status, BackupStatus.FAILED)
        self.assertEqual(result.error_code, "VALIDATION_FAILED")

    def test_fails_when_pg_restore_list_rejects_the_dump(self):
        service = self._service()
        result = self._run(service, run_fn=_fake_subprocess_run(restore_returncode=1, restore_stderr=b"not a valid archive"))
        self.assertEqual(result.status, BackupStatus.FAILED)
        self.assertEqual(result.error_code, "VALIDATION_FAILED")
        self.assertFalse(result.is_usable_for_deployment)

    def test_never_marks_success_before_all_validations_pass(self):
        service = self._service()
        result = self._run(service, run_fn=_fake_subprocess_run(restore_stdout=b"   "))
        self.assertNotEqual(result.status, BackupStatus.SUCCESS)

    def test_fails_when_database_revision_is_missing(self):
        service = self._service()
        with patch("shutil.which", return_value="/usr/bin/pg_dump"):
            result = service.run(database_revision=None)
        self.assertEqual(result.status, BackupStatus.FAILED)
        self.assertEqual(result.error_code, "DATABASE_REVISION_UNAVAILABLE")

    def test_fails_when_insufficient_disk_space(self):
        service = self._service(BACKUP_MIN_FREE_SPACE_MB=10**9)
        result = self._run(service)
        self.assertEqual(result.status, BackupStatus.FAILED)
        self.assertEqual(result.error_code, "INSUFFICIENT_DISK_SPACE")

    def test_lock_prevents_concurrent_backup_execution(self):
        service = self._service(BACKUP_LOCK_TIMEOUT_SECONDS=1)
        lock_path = self.backup_dir / ".predeployment-backup.lock"
        holder = BackupLock(lock_path, timeout_seconds=3600)
        holder.__enter__()
        try:
            result = self._run(service)
            self.assertEqual(result.status, BackupStatus.FAILED)
            self.assertEqual(result.error_code, "LOCK_TIMEOUT")
        finally:
            holder.release()

    def test_retention_is_applied_after_a_successful_backup_and_protects_the_new_one(self):
        service = self._service(BACKUP_RETENTION_KEEP_LAST_SUCCESSFUL=1, BACKUP_RETENTION_MINIMUM_AGE_DAYS=0)
        first = self._run(service)
        second = self._run(service)

        self.assertFalse((self.backup_dir / f"{first.backup_id}.manifest.json").exists())
        self.assertTrue((self.backup_dir / f"{second.backup_id}.manifest.json").exists())
        self.assertTrue(Path(second.file_path).exists())


if __name__ == "__main__":
    unittest.main()
