"""DEPLOY de producao (Fase 09, Secoes 16-19): backup obrigatorio -> pull da
imagem aprovada + confirmacao de digest -> migration segura (mecanismo da
Fase 04, executado a partir da imagem ja pulled) -> troca do container.

Cada etapa so avanca se a anterior teve sucesso; qualquer falha marca o
deployment como FAILED com o stage exato (Secao 23: `failed_stage`) e
interrompe ANTES de tocar o container ativo, exceto na ultima etapa (troca da
aplicacao), que so acontece depois de backup e migration confirmados.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.app.audit import service as audit_service  # noqa: E402
from api.app.audit.models import ActorType, AuditEventType, Component, EventResult  # noqa: E402
from api.app.backup.service import PreDeploymentBackupService  # noqa: E402
from api.app.core.migration_state import build_migration_state  # noqa: E402
from api.app.database.health import current_database_revision  # noqa: E402
from api.app.database.session import dispose_engine  # noqa: E402
from api.app.deployment import docker_control  # noqa: E402
from api.app.deployment.service import DeploymentOrchestrator, build_default_orchestrator  # noqa: E402
from scripts.deployment.env_util import collect_prefixed_env  # noqa: E402
from scripts.deployment.metadata import DeploymentMetadata  # noqa: E402

CONTAINER_ENV_PREFIX = "DEPLOY_CONTAINER_ENV_"
MIGRATION_COMMAND = ["sh", "-c", "cd /app/api && python -m alembic upgrade head"]


class DeployFailedError(RuntimeError):
    def __init__(self, message: str, *, failed_stage: str):
        super().__init__(message)
        self.failed_stage = failed_stage


def _current_revision() -> str | None:
    async def _inner() -> str | None:
        try:
            return await current_database_revision()
        finally:
            await dispose_engine()

    return asyncio.run(_inner())


def run_deploy(
    *,
    metadata: DeploymentMetadata,
    container_name: str,
    network: str,
    container_env: dict[str, str],
    migration_timeout_seconds: float = 300.0,
    orchestrator: DeploymentOrchestrator | None = None,
    backup_service: PreDeploymentBackupService | None = None,
    docker=docker_control,
    current_revision_fn=_current_revision,
) -> None:
    orchestrator = orchestrator or build_default_orchestrator()
    backup_service = backup_service or PreDeploymentBackupService()
    corr = metadata.correlation_id or metadata.deployment_id

    def _audit(event_type: AuditEventType, result: EventResult, message: str, **extra) -> None:
        audit_service.record_event(
            event_type=event_type, component=Component.DEPLOYMENT, result=result, actor_type=ActorType.DEPLOY_RUNNER,
            deployment_id=metadata.deployment_id, release_id=metadata.release_version, version=metadata.release_version,
            correlation_id=corr, message=message, metadata=extra or None,
        )

    revision_before = current_revision_fn()

    # -- BACKUP (Secao 16) ------------------------------------------------
    _audit(AuditEventType.BACKUP_STARTED, EventResult.STARTED, f"Backup pre-deploy iniciado para {metadata.deployment_id}.")
    backup_result = backup_service.run(
        database_revision=revision_before,
        target_release_version=metadata.release_version,
        build_sha=metadata.git_commit_sha,
    )
    if not backup_result.is_usable_for_deployment:
        reason = (
            f"backup invalido: status={backup_result.status.value} "
            f"validation={backup_result.validation_status.value} error={backup_result.error_message}"
        )
        orchestrator.mark_failed(metadata.deployment_id, reason=reason, failed_stage="BACKUP")
        _audit(AuditEventType.BACKUP_FAILED, EventResult.FAILED, reason)
        raise DeployFailedError(reason, failed_stage="BACKUP")
    _audit(AuditEventType.BACKUP_SUCCEEDED, EventResult.SUCCEEDED, f"Backup {backup_result.backup_id} concluido.", backup_id=backup_result.backup_id)

    orchestrator.mark_deploying(metadata.deployment_id, backup_id=backup_result.backup_id)

    # -- PULL seguro da imagem alvo (Secao 17) -----------------------------
    try:
        docker.pull_image(metadata.image_ref_by_tag)
    except RuntimeError as exc:
        orchestrator.mark_failed(metadata.deployment_id, reason=str(exc), failed_stage="PULL")
        _audit(AuditEventType.IMAGE_PULL_FAILED, EventResult.FAILED, str(exc))
        raise DeployFailedError(str(exc), failed_stage="PULL") from exc

    if metadata.image_digest:
        pulled_digest = docker.image_digest(metadata.image_ref_by_tag)
        if pulled_digest != metadata.image_digest:
            reason = f"Digest divergente apos pull: aprovado={metadata.image_digest} baixado={pulled_digest}."
            orchestrator.mark_failed(metadata.deployment_id, reason=reason, failed_stage="PULL")
            _audit(AuditEventType.IMAGE_PULL_FAILED, EventResult.FAILED, reason)
            raise DeployFailedError(reason, failed_stage="PULL")
    _audit(AuditEventType.IMAGE_PULL_SUCCEEDED, EventResult.SUCCEEDED, f"Imagem {metadata.image_ref_by_tag} baixada.")

    # -- MIGRATION segura (Secao 18, mecanismo da Fase 04) ------------------
    _audit(AuditEventType.MIGRATION_STARTED, EventResult.STARTED, f"Migration iniciada a partir de {revision_before}.")
    preflight = build_migration_state(revision_before)
    if not preflight.migration_history_consistent:
        reason = f"Revisao atual do banco ({revision_before!r}) nao reconhecida no historico real de migrations -- preflight abortado."
        orchestrator.mark_failed(metadata.deployment_id, reason=reason, failed_stage="MIGRATION")
        _audit(AuditEventType.MIGRATION_FAILED, EventResult.FAILED, reason)
        raise DeployFailedError(reason, failed_stage="MIGRATION")

    migration_result = docker.run_ephemeral(
        image_ref=metadata.image_ref_by_tag, network=network, env=container_env,
        command=MIGRATION_COMMAND, timeout=migration_timeout_seconds,
    )
    if migration_result.returncode != 0:
        reason = f"Migration falhou (exit={migration_result.returncode}): {migration_result.stderr.strip()[:500]}"
        orchestrator.mark_failed(metadata.deployment_id, reason=reason, failed_stage="MIGRATION")
        _audit(AuditEventType.MIGRATION_FAILED, EventResult.FAILED, reason)
        raise DeployFailedError(reason, failed_stage="MIGRATION")

    revision_after = current_revision_fn()
    if revision_after != metadata.expected_database_schema:
        reason = f"Revisao pos-migration ({revision_after!r}) diverge da esperada pela release ({metadata.expected_database_schema!r})."
        orchestrator.mark_failed(metadata.deployment_id, reason=reason, failed_stage="MIGRATION")
        _audit(AuditEventType.MIGRATION_FAILED, EventResult.FAILED, reason)
        raise DeployFailedError(reason, failed_stage="MIGRATION")
    _audit(AuditEventType.MIGRATION_SUCCEEDED, EventResult.SUCCEEDED, f"Migration concluida em {revision_after}.")

    # -- TROCA DA APLICACAO (Secao 19) --------------------------------------
    docker.stop_and_remove_container(container_name)
    try:
        docker.run_container(name=container_name, image_ref=metadata.image_ref_by_tag, network=network, env=container_env, port=8000)
    except RuntimeError as exc:
        orchestrator.mark_failed(metadata.deployment_id, reason=str(exc), failed_stage="DEPLOY_SWAP")
        _audit(AuditEventType.DEPLOYMENT_SWITCH_FAILED, EventResult.FAILED, str(exc))
        raise DeployFailedError(str(exc), failed_stage="DEPLOY_SWAP") from exc
    _audit(AuditEventType.DEPLOYMENT_SWITCH_SUCCEEDED, EventResult.SUCCEEDED, f"Container {container_name} trocado para {metadata.image_ref_by_tag}.")

    orchestrator.mark_validating(metadata.deployment_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Executa backup + migration + troca de container (Fase 09).")
    parser.add_argument("--metadata", required=True, help="Caminho do JSON de DeploymentMetadata (produzido pelo precheck).")
    parser.add_argument("--container-name", required=True)
    parser.add_argument("--network", required=True)
    parser.add_argument("--migration-timeout-seconds", type=float, default=300.0)
    args = parser.parse_args(argv)

    metadata = DeploymentMetadata.load(Path(args.metadata))
    try:
        run_deploy(
            metadata=metadata, container_name=args.container_name, network=args.network,
            container_env=collect_prefixed_env(CONTAINER_ENV_PREFIX),
            migration_timeout_seconds=args.migration_timeout_seconds,
        )
    except DeployFailedError as exc:
        print(f"DEPLOY FALHOU [{exc.failed_stage}]: {exc}")
        return 1

    print(f"DEPLOY OK: deployment_id={metadata.deployment_id} (aguardando VERIFY)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
