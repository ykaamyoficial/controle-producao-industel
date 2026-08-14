"""Update Distribution Service (Fase 12): sincroniza, valida, publica,
autoriza e revoga releases Desktop, e resolve o que pode ser servido aos
clientes. Unica camada que decide "qual release pode ser distribuida"
(Secao 4, regra de ouro) -- o router nunca acessa o filesystem diretamente.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from api.app.audit import service as audit_service
from api.app.audit.models import ActorType, AuditEventType, Component, EventResult, EventSeverity
from api.app.backup.lock import BackupLock, BackupLockError
from api.app.core.config import get_settings
from api.app.core.versioning import get_api_contract_version, get_server_version, is_version_at_least, parse_version
from api.app.updates import manifest_schema, paths
from api.app.updates.download_grant import mint_download_grant
from api.app.updates.exceptions import (
    ReleaseImmutableError,
    ReleaseInvalidStateError,
    ReleaseNotAuthorizedError,
    ReleaseNotFoundError,
    ReleaseSyncInProgressError,
    ReleaseValidationError,
)
from api.app.updates.models import ArtifactInfo, ReleaseRecord, ReleaseState
from api.app.updates.state_store import ReleaseStateStore

log = logging.getLogger("api.updates")


def _lock_path() -> Path:
    return paths.update_repository_root() / ".update-release.lock"


def _lock() -> BackupLock:
    settings = get_settings()
    return BackupLock(_lock_path(), timeout_seconds=settings.update_lock_timeout_seconds, owner="update-distribution")


def _state_store() -> ReleaseStateStore:
    return ReleaseStateStore(paths.state_dir())


def _now() -> datetime:
    return datetime.now(UTC)


def sync_release(*, manifest_path: Path, package_path: Path, source: str = "manual") -> ReleaseRecord:
    """Fase 12, Secao 24: staging -> validar manifest -> validar size ->
    validar sha256 -> validar compatibilidade -> promove para READY.
    Nunca autoriza automaticamente (autorizacao e uma acao explicita
    separada, ver authorize_release)."""
    paths.ensure_repository_dirs()
    try:
        with _lock():
            return _sync_release_locked(manifest_path=manifest_path, package_path=package_path, source=source)
    except BackupLockError as exc:
        raise ReleaseSyncInProgressError(str(exc)) from exc


def _sync_release_locked(*, manifest_path: Path, package_path: Path, source: str) -> ReleaseRecord:
    log.info("release_sync_started manifest=%s package=%s source=%s", manifest_path, package_path, source)

    if not manifest_path.is_file():
        raise ReleaseValidationError(f"Manifesto de origem nao encontrado: {manifest_path}.")
    if not package_path.is_file():
        raise ReleaseValidationError(f"Pacote de origem nao encontrado: {package_path}.")

    try:
        raw = manifest_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        normalized = manifest_schema.validate_manifest_dict(data)
    except (OSError, ValueError) as exc:
        log.warning("release_validation_failed reason=manifest_invalido detalhe=%s", exc)
        raise ReleaseValidationError(f"Manifesto invalido: {exc}") from exc

    version = normalized["release_version"]
    paths.safe_version_segment(version)
    artifact_data = normalized["artifact"]
    store = _state_store()
    existing = store.load(version)

    if existing is not None:
        if existing.state == ReleaseState.REVOKED:
            raise ReleaseInvalidStateError(f"Release {version} foi revogada e nao pode ser ressincronizada.")
        if existing.artifact is not None and existing.artifact.sha256 != artifact_data["sha256"]:
            raise ReleaseImmutableError(
                f"Release {version} ja foi publicada com um SHA-256 diferente. "
                "Uma versao publicada e imutavel (Secao 18) -- publique uma nova versao."
            )
        if existing.state in (ReleaseState.AUTHORIZED, ReleaseState.READY) and existing.artifact is not None and existing.artifact.sha256 == artifact_data["sha256"]:
            log.info("release_sync_completed version=%s resultado=idempotente_sem_mudancas", version)
            return existing

    now = _now()
    discovered = ReleaseRecord(
        version=version,
        state=ReleaseState.DISCOVERED,
        manifest_schema_version=normalized["manifest_schema_version"],
        channel=normalized["channel"],
        minimum_server_version=normalized["minimum_server_version"],
        api_contract_version=normalized["api_contract_version"],
        artifact=None,
        manifest=None,
        source=source,
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    store.save(discovered)
    audit_service.record_event(
        event_type=AuditEventType.RELEASE_DISCOVERED, component=Component.UPDATE_SERVER, result=EventResult.STARTED,
        actor_type=ActorType.ADMIN_API, release_id=version, version=version, correlation_id=version,
        message=f"Release {version} descoberta a partir de {source}.",
    )
    audit_service.record_event(
        event_type=AuditEventType.RELEASE_VALIDATION_STARTED, component=Component.UPDATE_SERVER, result=EventResult.STARTED,
        actor_type=ActorType.ADMIN_API, release_id=version, version=version, correlation_id=version,
        message=f"Validando manifesto/pacote de {version}.",
    )

    staging_root = paths.staging_dir()
    staging_root.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(dir=str(staging_root), prefix=f"{version}-"))
    try:
        store.save(discovered.replace(state=ReleaseState.DOWNLOADING, updated_at=_now()))
        staged_package = work_dir / artifact_data["filename"]
        shutil.copy2(package_path, staged_package)

        store.save(discovered.replace(state=ReleaseState.VERIFYING, updated_at=_now()))
        actual_size = staged_package.stat().st_size
        if actual_size != artifact_data["size_bytes"]:
            failed = discovered.replace(
                state=ReleaseState.FAILED,
                failed_reason=f"size divergente: manifesto={artifact_data['size_bytes']} arquivo={actual_size}",
                updated_at=_now(),
            )
            store.save(failed)
            log.warning("release_validation_failed version=%s reason=size_mismatch", version)
            audit_service.record_event(
                event_type=AuditEventType.RELEASE_VALIDATION_FAILED, component=Component.UPDATE_SERVER, result=EventResult.FAILED,
                severity=EventSeverity.WARNING, actor_type=ActorType.ADMIN_API, release_id=version, version=version,
                correlation_id=version, message=failed.failed_reason,
            )
            raise ReleaseValidationError(failed.failed_reason)

        actual_sha256 = manifest_schema.sha256_file(staged_package)
        if actual_sha256 != artifact_data["sha256"]:
            failed = discovered.replace(
                state=ReleaseState.FAILED,
                failed_reason=f"sha256 divergente: manifesto={artifact_data['sha256']} arquivo={actual_sha256}",
                updated_at=_now(),
            )
            store.save(failed)
            log.warning("release_validation_failed version=%s reason=sha256_mismatch", version)
            audit_service.record_event(
                event_type=AuditEventType.RELEASE_VALIDATION_FAILED, component=Component.UPDATE_SERVER, result=EventResult.FAILED,
                severity=EventSeverity.WARNING, actor_type=ActorType.ADMIN_API, release_id=version, version=version,
                correlation_id=version, message=failed.failed_reason,
            )
            raise ReleaseValidationError(failed.failed_reason)

        staged_manifest = work_dir / "manifest.json"
        staged_manifest.write_text(_canonical_manifest_json(normalized), encoding="utf-8")

        target_dir = paths.ready_version_dir(version)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(work_dir, target_dir)

        ready = discovered.replace(
            state=ReleaseState.READY,
            artifact=ArtifactInfo.from_dict(artifact_data),
            manifest=normalized,
            updated_at=_now(),
        )
        store.save(ready)
        log.info("release_sync_completed version=%s sha256=%s size=%s state=READY", version, artifact_data["sha256"], actual_size)
        audit_service.record_event(
            event_type=AuditEventType.RELEASE_VALIDATED, component=Component.UPDATE_SERVER, result=EventResult.SUCCEEDED,
            actor_type=ActorType.ADMIN_API, release_id=version, version=version, correlation_id=version,
            message=f"Release {version} validada e publicada (READY).",
            metadata={"sha256": artifact_data["sha256"], "size_bytes": actual_size},
        )
        return ready
    except ReleaseValidationError:
        raise
    finally:
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)


def _canonical_manifest_json(data: dict) -> str:
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def authorize_release(version: str) -> ReleaseRecord:
    try:
        with _lock():
            return _authorize_release_locked(version)
    except BackupLockError as exc:
        raise ReleaseSyncInProgressError(str(exc)) from exc


def _authorize_release_locked(version: str) -> ReleaseRecord:
    store = _state_store()
    record = store.load(version)
    if record is None:
        raise ReleaseNotFoundError(f"Release {version} nao encontrada.")
    if record.state == ReleaseState.AUTHORIZED:
        return record
    if record.state != ReleaseState.READY:
        raise ReleaseInvalidStateError(f"Release {version} esta em estado {record.state.value}; precisa estar READY para ser autorizada.")

    server_version = get_server_version()
    if not is_version_at_least(server_version, record.minimum_server_version):
        raise ReleaseValidationError(
            f"Release {version} exige minimum_server_version={record.minimum_server_version}, "
            f"servidor atual e {server_version}."
        )
    if record.api_contract_version != get_api_contract_version():
        raise ReleaseValidationError(
            f"Release {version} foi publicada para api_contract_version={record.api_contract_version}, "
            f"servidor atual expoe {get_api_contract_version()}."
        )

    updated = record.replace(state=ReleaseState.AUTHORIZED, authorized_at=_now(), updated_at=_now())
    store.save(updated)
    log.info("release_authorized version=%s", version)
    audit_service.record_event(
        event_type=AuditEventType.RELEASE_AUTHORIZED, component=Component.UPDATE_SERVER, result=EventResult.SUCCEEDED,
        actor_type=ActorType.ADMIN_API, release_id=version, version=version, correlation_id=version,
        message=f"Release {version} autorizada para distribuicao.",
    )
    return updated


def revoke_release(version: str, *, reason: str) -> ReleaseRecord:
    try:
        with _lock():
            return _revoke_release_locked(version, reason=reason)
    except BackupLockError as exc:
        raise ReleaseSyncInProgressError(str(exc)) from exc


def _revoke_release_locked(version: str, *, reason: str) -> ReleaseRecord:
    store = _state_store()
    record = store.load(version)
    if record is None:
        raise ReleaseNotFoundError(f"Release {version} nao encontrada.")
    if record.state == ReleaseState.REVOKED:
        return record
    if record.state != ReleaseState.AUTHORIZED:
        raise ReleaseInvalidStateError(f"Release {version} esta em estado {record.state.value}; so releases AUTHORIZED podem ser revogadas.")

    updated = record.replace(state=ReleaseState.REVOKED, revoked_at=_now(), revoked_reason=reason.strip() or "sem motivo informado", updated_at=_now())
    store.save(updated)
    log.info("release_revoked version=%s reason=%s", version, updated.revoked_reason)
    audit_service.record_event(
        event_type=AuditEventType.RELEASE_REVOKED, component=Component.UPDATE_SERVER, result=EventResult.REVOKED,
        actor_type=ActorType.ADMIN_API, release_id=version, version=version, correlation_id=version,
        message=f"Release {version} revogada: {updated.revoked_reason}",
    )
    return updated


def list_releases() -> list[ReleaseRecord]:
    return _state_store().list_all()


def get_release(version: str) -> ReleaseRecord | None:
    """Leitura publica de um unico registro (Fase 15: usado pelo servico de
    promocao de canal para validar elegibilidade/hash sem acessar o state
    store privado diretamente)."""
    return _state_store().load(version)


def get_discovery_info() -> dict:
    releases = [record for record in _state_store().list_all() if record.state == ReleaseState.AUTHORIZED]
    if not releases:
        return {"available": False}
    latest = max(releases, key=lambda record: parse_version(record.version).as_tuple())
    grant = mint_download_grant(latest.version)
    return {
        "available": True,
        "version": latest.version,
        "manifest_url": f"/api/v1/updates/desktop/{latest.version}/manifest?grant={grant}",
        "package_url": f"/api/v1/updates/desktop/{latest.version}/package?grant={grant}",
        "release_state": latest.state.value,
    }


def get_manifest_bytes(version: str) -> bytes:
    record = _state_store().load(version)
    if record is None or record.state != ReleaseState.AUTHORIZED:
        raise ReleaseNotAuthorizedError()
    manifest_path = paths.resolve_ready_manifest_path(version)
    try:
        return manifest_path.read_bytes()
    except OSError as exc:
        log.error("release_manifest_unreadable version=%s detalhe=%s", version, exc)
        raise ReleaseNotAuthorizedError() from exc


def resolve_package_for_download(version: str) -> tuple[Path, ReleaseRecord]:
    record = _state_store().load(version)
    if record is None or record.state != ReleaseState.AUTHORIZED or record.artifact is None:
        raise ReleaseNotAuthorizedError()
    package_path = paths.resolve_ready_package_path(version, record.artifact.filename)
    if not package_path.is_file():
        log.error("release_package_missing version=%s path=%s", version, package_path)
        raise ReleaseNotAuthorizedError()
    return package_path, record


def recover_incomplete_staging() -> list[str]:
    """Fase 12, Secao 9/28: em reinicio, staging incompleto deve ser
    detectado e limpo. Como sync_release roda inteiramente dentro do lock
    (nenhum estado parcial fica fora do lock em operacao normal), qualquer
    diretorio remanescente em staging/ so pode ser de um processo que morreu
    no meio -- seguro de remover (nunca aponta para nada publicado)."""
    paths.ensure_repository_dirs()
    removed = []
    for entry in paths.staging_dir().iterdir():
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
            removed.append(entry.name)
            log.info("release_staging_recovered removed=%s", entry.name)
    return removed
