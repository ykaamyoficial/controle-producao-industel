from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from api.app.backup.connection import PgConnectionParams, parse_database_url
from api.app.backup.lock import BackupLock, BackupLockError
from api.app.backup.models import BackupResult, BackupStatus, ValidationStatus
from api.app.backup.naming import build_backup_id, dump_filename, manifest_filename
from api.app.backup.retention import RetentionPolicy, apply_retention
from api.app.backup.validation import BackupValidator
from api.app.core.config import API_CONTRACT_VERSION, API_VERSION, Settings, get_settings

log = logging.getLogger("api.backup")

ROOT_DIR = Path(__file__).resolve().parents[3]


class PreDeploymentBackupService:
    """Servico independente de UI/HTTP para gerar, validar e registrar um backup
    pre-deployment do PostgreSQL (Fase 05). Chamavel manualmente hoje
    (scripts/run_predeployment_backup.py) e por um deployer/pipeline nas fases
    futuras -- nao acoplado a PySide nem a nenhum endpoint.

    Fluxo (Secao 11): lock -> metadados -> espaco em disco -> pg_dump -> exit
    code -> arquivo/tamanho -> pg_restore --list -> SHA-256 -> manifest atomico
    -> retencao. Qualquer etapa que falhar produz BackupResult(status=FAILED,
    validation_status != VALID) -- nunca uma excecao nao tratada, e nunca um
    sucesso parcial.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        connection: PgConnectionParams | None = None,
        backup_dir: Path | None = None,
        retention_policy: RetentionPolicy | None = None,
    ):
        self._settings = settings or get_settings()
        self._connection = connection
        configured_dir = Path(self._settings.backup_dir)
        self._backup_dir = backup_dir or (configured_dir if configured_dir.is_absolute() else ROOT_DIR / configured_dir)
        self._retention_policy = retention_policy or RetentionPolicy(
            keep_last_successful=self._settings.backup_retention_keep_last_successful,
            minimum_age_before_delete_days=self._settings.backup_retention_minimum_age_days,
        )
        self._validator = BackupValidator(
            pg_restore_path=self._settings.pg_restore_path,
            timeout_seconds=self._settings.backup_timeout_seconds,
        )

    def run(
        self,
        *,
        database_revision: str | None,
        target_release_version: str | None = None,
        environment: str | None = None,
        build_sha: str | None = None,
    ) -> BackupResult:
        created_at = datetime.now(timezone.utc)
        connection = self._resolve_connection()
        backup_id = "predeploy-metadata-unavailable"

        if connection is None:
            return self._failed(backup_id, created_at, database_name="unknown", error_code="INVALID_DATABASE_URL", error_message="DATABASE_URL invalida ou nao configurada.")
        if not database_revision:
            return self._failed(
                backup_id, created_at, database_name=connection.dbname,
                error_code="DATABASE_REVISION_UNAVAILABLE",
                error_message="Nao foi possivel determinar a revisao atual do banco antes do backup.",
            )

        backup_id = build_backup_id(server_version=API_VERSION, database_revision=database_revision, now=created_at)
        log.info("BACKUP_STARTED | backup_id=%s | database=%s | database_revision=%s", backup_id, connection.dbname, database_revision)

        lock_path = self._backup_dir / ".predeployment-backup.lock"
        try:
            with BackupLock(lock_path, timeout_seconds=self._settings.backup_lock_timeout_seconds):
                return self._run_locked(
                    backup_id=backup_id,
                    created_at=created_at,
                    connection=connection,
                    database_revision=database_revision,
                    target_release_version=target_release_version,
                    environment=environment,
                    build_sha=build_sha,
                )
        except BackupLockError as exc:
            log.warning("BACKUP_FAILED | backup_id=%s | error_code=LOCK_TIMEOUT", backup_id)
            return self._failed(backup_id, created_at, database_name=connection.dbname, error_code="LOCK_TIMEOUT", error_message=str(exc))

    def _run_locked(
        self,
        *,
        backup_id: str,
        created_at: datetime,
        connection: PgConnectionParams,
        database_revision: str,
        target_release_version: str | None,
        environment: str | None,
        build_sha: str | None,
    ) -> BackupResult:
        try:
            self._ensure_destination()
        except OSError as exc:
            return self._failed(backup_id, created_at, database_name=connection.dbname, error_code="DESTINATION_UNAVAILABLE", error_message=connection.sanitize_for_log(str(exc)))

        space_error = self._check_disk_space()
        if space_error is not None:
            return self._failed(backup_id, created_at, database_name=connection.dbname, error_code="INSUFFICIENT_DISK_SPACE", error_message=space_error)

        file_path = self._backup_dir / dump_filename(backup_id)
        dump_error = self._run_pg_dump(file_path, connection)
        if dump_error is not None:
            code, message = dump_error
            return self._failed(backup_id, created_at, database_name=connection.dbname, error_code=code, error_message=connection.sanitize_for_log(message))

        log.info("BACKUP_DUMP_CREATED | backup_id=%s | file=%s", backup_id, file_path.name)

        outcome = self._validator.validate(file_path)
        if outcome.status != ValidationStatus.VALID:
            result = self._failed(
                backup_id, created_at, database_name=connection.dbname,
                error_code="VALIDATION_FAILED", error_message=outcome.detail,
                file_path=file_path, validation_status=outcome.status,
                database_revision=database_revision,
            )
            self._write_manifest(result)
            return result

        try:
            sha256 = self._sha256(file_path)
        except OSError as exc:
            result = self._failed(
                backup_id, created_at, database_name=connection.dbname,
                error_code="HASH_FAILED", error_message=str(exc),
                file_path=file_path, validation_status=ValidationStatus.UNKNOWN,
                database_revision=database_revision,
            )
            self._write_manifest(result)
            return result

        completed_at = datetime.now(timezone.utc)
        result = BackupResult(
            status=BackupStatus.SUCCESS,
            backup_id=backup_id,
            created_at_utc=created_at,
            completed_at_utc=completed_at,
            database_name=connection.dbname,
            server_version=API_VERSION,
            validation_status=ValidationStatus.VALID,
            file_path=str(file_path),
            size_bytes=file_path.stat().st_size,
            sha256=sha256,
            database_revision=database_revision,
            api_contract_version=API_CONTRACT_VERSION,
            target_release_version=target_release_version,
            environment=environment or self._settings.app_env,
            build_sha=build_sha,
        )

        try:
            self._write_manifest(result)
        except OSError as exc:
            return self._failed(
                backup_id, created_at, database_name=connection.dbname,
                error_code="MANIFEST_WRITE_FAILED", error_message=str(exc),
                file_path=file_path, validation_status=ValidationStatus.VALID,
                database_revision=database_revision,
            )

        log.info(
            "BACKUP_VALIDATED | backup_id=%s | size_bytes=%s | sha256=%s | duration_s=%.1f",
            backup_id, result.size_bytes, sha256, (completed_at - created_at).total_seconds(),
        )

        try:
            removed = apply_retention(self._backup_dir, policy=self._retention_policy, current_backup_id=backup_id)
            if removed:
                log.info("BACKUP_RETENTION_APPLIED | removed=%s", ",".join(removed))
        except Exception:
            log.exception("backup_retention_unexpected_error | backup_id=%s", backup_id)

        return result

    # -- etapas internas ---------------------------------------------------

    def _resolve_connection(self) -> PgConnectionParams | None:
        if self._connection is not None:
            return self._connection
        try:
            return parse_database_url(self._settings.database_url)
        except ValueError:
            return None

    def _ensure_destination(self) -> None:
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    def _check_disk_space(self) -> str | None:
        try:
            usage = shutil.disk_usage(self._backup_dir)
        except OSError as exc:
            return f"Nao foi possivel medir espaco livre em '{self._backup_dir}': {exc}"
        free_mb = usage.free / (1024 * 1024)
        minimum = self._settings.backup_min_free_space_mb
        if free_mb < minimum:
            return f"Espaco livre insuficiente em '{self._backup_dir}': {free_mb:.0f}MB disponiveis, minimo exigido {minimum}MB."
        return None

    def _run_pg_dump(self, file_path: Path, connection: PgConnectionParams) -> tuple[str, str] | None:
        pg_dump_path = self._settings.pg_dump_path
        if shutil.which(pg_dump_path) is None:
            return "PG_DUMP_NOT_FOUND", f"pg_dump nao encontrado em '{pg_dump_path}' (verifique PATH ou PG_DUMP_PATH)."

        args = [
            pg_dump_path,
            "--format=custom",
            f"--file={file_path}",
            "--no-owner",
            "--no-privileges",
            *connection.as_args(),
            connection.dbname,
        ]
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                timeout=self._settings.backup_timeout_seconds,
                env=connection.env(),
            )
        except subprocess.TimeoutExpired:
            return "TIMEOUT", f"pg_dump excedeu o timeout de {self._settings.backup_timeout_seconds}s."
        except OSError as exc:
            return "PG_DUMP_EXECUTION_ERROR", f"Falha ao executar pg_dump: {exc}"

        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            return "PG_DUMP_FAILED", f"pg_dump terminou com exit code {proc.returncode}: {stderr[:400]}"
        return None

    def _sha256(self, file_path: Path) -> str:
        digest = hashlib.sha256()
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _write_manifest(self, result: BackupResult) -> Path:
        manifest_path = self._backup_dir / manifest_filename(result.backup_id)
        payload = result.to_manifest_dict()
        fd, tmp_name = tempfile.mkstemp(dir=str(self._backup_dir), prefix=".manifest-tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False)
            os.replace(tmp_name, manifest_path)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return manifest_path

    def _failed(
        self,
        backup_id: str,
        created_at: datetime,
        *,
        database_name: str,
        error_code: str,
        error_message: str,
        file_path: Path | None = None,
        validation_status: ValidationStatus = ValidationStatus.UNKNOWN,
        database_revision: str | None = None,
    ) -> BackupResult:
        log.warning("BACKUP_FAILED | backup_id=%s | error_code=%s", backup_id, error_code)
        return BackupResult(
            status=BackupStatus.FAILED,
            backup_id=backup_id,
            created_at_utc=created_at,
            completed_at_utc=datetime.now(timezone.utc),
            database_name=database_name,
            server_version=API_VERSION,
            validation_status=validation_status,
            file_path=str(file_path) if file_path is not None else None,
            size_bytes=file_path.stat().st_size if file_path is not None and file_path.exists() else None,
            database_revision=database_revision,
            api_contract_version=API_CONTRACT_VERSION,
            error_code=error_code,
            error_message=error_message,
        )
