"""PRECHECK do deployment de producao (Fase 09, Secao 15).

Roda no runner de producao, ANTES de qualquer alteracao no container ativo.
Qualquer falha aqui aborta o pipeline sem tocar a versao em producao. A
propria chamada a DeploymentOrchestrator.begin_deployment (Fase 08) cumpre
"adquirir deployment lock" e "confirmar estado atual" (rejeita um novo
deployment se ja houver um em andamento nao-terminal).
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.app.audit import service as audit_service  # noqa: E402
from api.app.audit.correlation import new_correlation_id  # noqa: E402
from api.app.audit.models import ActorType, AuditEventType, Component, EventResult  # noqa: E402
from api.app.core.config import API_CONTRACT_VERSION, API_VERSION, EXPECTED_DATABASE_REVISION, get_settings  # noqa: E402
from api.app.database.health import database_check  # noqa: E402
from api.app.database.session import dispose_engine  # noqa: E402
from api.app.deployment import docker_control  # noqa: E402
from api.app.deployment.exceptions import DeploymentError  # noqa: E402
from api.app.deployment.service import build_default_orchestrator  # noqa: E402
from api.app.maintenance.models import MaintenanceReasonCode  # noqa: E402
from api.app.maintenance.service import MaintenanceService, build_default_service  # noqa: E402
from scripts.deployment.metadata import DeploymentMetadata  # noqa: E402


class PrecheckFailedError(RuntimeError):
    """Qualquer condicao do PRECHECK (Secao 15) nao satisfeita."""


def _fail(reason: str, *, correlation_id: str, target_version: str) -> None:
    audit_service.record_event(
        event_type=AuditEventType.PRECHECK_FAILED, component=Component.DEPLOYMENT, result=EventResult.FAILED,
        actor_type=ActorType.DEPLOY_RUNNER, version=target_version, correlation_id=correlation_id, message=reason,
    )
    raise PrecheckFailedError(reason)


def _resolve_database_state():
    async def _inner():
        try:
            return await database_check()
        finally:
            await dispose_engine()

    return asyncio.run(_inner())


def run_precheck(
    *,
    target_version: str,
    image_repository: str,
    image_tag: str,
    image_digest: str | None,
    git_commit_sha: str,
    workflow_run_id: str | None = None,
    min_free_space_mb: int = 500,
    docker=docker_control,
    database_state_fn=_resolve_database_state,
    disk_usage_fn=shutil.disk_usage,
    orchestrator=None,
    maintenance_service: MaintenanceService | None = None,
    draining_window_seconds: float = 10.0,
    sleep_fn=time.sleep,
    correlation_id: str | None = None,
) -> DeploymentMetadata:
    correlation_id = correlation_id or new_correlation_id()

    if target_version != API_VERSION:
        _fail(
            f"Versao alvo '{target_version}' diverge de API_VERSION='{API_VERSION}' (fonte central, Fase 01).",
            correlation_id=correlation_id, target_version=target_version,
        )

    if not docker.docker_available():
        _fail("Docker indisponivel no runner de producao.", correlation_id=correlation_id, target_version=target_version)

    db_check = database_state_fn()
    if db_check.status != "connected":
        _fail(f"PostgreSQL indisponivel para o precheck (status={db_check.status}).", correlation_id=correlation_id, target_version=target_version)

    settings = get_settings()
    state_dir = Path(settings.deployment_state_dir)
    if not state_dir.is_absolute():
        state_dir = ROOT / state_dir
    probe_dir = state_dir if state_dir.exists() else ROOT
    try:
        usage = disk_usage_fn(probe_dir)
    except OSError as exc:
        _fail(f"Nao foi possivel medir espaco livre em '{probe_dir}': {exc}", correlation_id=correlation_id, target_version=target_version)
    free_mb = usage.free / (1024 * 1024)
    if free_mb < min_free_space_mb:
        _fail(
            f"Espaco livre insuficiente em '{probe_dir}': {free_mb:.0f}MB disponiveis, minimo {min_free_space_mb}MB.",
            correlation_id=correlation_id, target_version=target_version,
        )

    orchestrator = orchestrator or build_default_orchestrator(settings=settings)
    try:
        state = orchestrator.begin_deployment(
            target_version=target_version,
            target_image_ref=f"{image_repository}:{image_tag}",
            target_image_digest=image_digest,
            database_revision_before=db_check.revision,
            source="github-actions",
        )
    except DeploymentError as exc:
        _fail(str(exc), correlation_id=correlation_id, target_version=target_version)

    # Maintenance Mode (Fase 14, Secao 19, passos 2-4): DRAINING -> janela
    # curta/configuravel -> ACTIVE, ANTES de qualquer alteracao no container
    # ativo. Se a ativacao falhar, o PRECHECK inteiro falha (nunca prossegue
    # para backup/migration com o sistema fora de manutencao).
    maintenance_service = maintenance_service or build_default_service(settings=settings)
    message = f"Deploy da versao {target_version} em andamento."
    draining = maintenance_service.begin_draining(
        reason_code=MaintenanceReasonCode.DEPLOYMENT, message=message,
        expected_end_at=None, activated_by="deploy-pipeline", correlation_id=correlation_id,
    )
    if draining_window_seconds > 0:
        sleep_fn(draining_window_seconds)
    maintenance_state = maintenance_service.activate_maintenance(
        reason_code=MaintenanceReasonCode.DEPLOYMENT, message=message,
        expected_end_at=None, activated_by="deploy-pipeline", correlation_id=correlation_id,
    )

    audit_service.record_event(
        event_type=AuditEventType.PRECHECK_SUCCEEDED, component=Component.DEPLOYMENT, result=EventResult.SUCCEEDED,
        actor_type=ActorType.DEPLOY_RUNNER, deployment_id=state.deployment_id, release_id=target_version,
        version=target_version, maintenance_id=maintenance_state.maintenance_id, correlation_id=correlation_id,
        message=f"Precheck aprovado para {target_version}.",
    )

    return DeploymentMetadata(
        deployment_id=state.deployment_id,
        release_version=target_version,
        git_commit_sha=git_commit_sha,
        image_repository=image_repository,
        image_tag=image_tag,
        image_digest=image_digest,
        api_contract_version=API_CONTRACT_VERSION,
        expected_database_schema=EXPECTED_DATABASE_REVISION,
        workflow_run_id=workflow_run_id,
        maintenance_id=maintenance_state.maintenance_id,
        correlation_id=correlation_id,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PRECHECK do deployment de producao (Fase 09).")
    parser.add_argument("--target-version", required=True)
    parser.add_argument("--image-repository", required=True)
    parser.add_argument("--image-tag", required=True)
    parser.add_argument("--image-digest", default=None)
    parser.add_argument("--git-commit-sha", required=True)
    parser.add_argument("--workflow-run-id", default=None)
    parser.add_argument("--min-free-space-mb", type=int, default=500)
    parser.add_argument("--draining-window-seconds", type=float, default=10.0, help="Janela DRAINING antes de ativar ACTIVE (Fase 14, Secao 14).")
    parser.add_argument("--output", required=True, help="Caminho do JSON de DeploymentMetadata a ser produzido.")
    args = parser.parse_args(argv)

    try:
        metadata = run_precheck(
            target_version=args.target_version,
            image_repository=args.image_repository,
            image_tag=args.image_tag,
            image_digest=args.image_digest,
            git_commit_sha=args.git_commit_sha,
            workflow_run_id=args.workflow_run_id,
            min_free_space_mb=args.min_free_space_mb,
            draining_window_seconds=args.draining_window_seconds,
        )
    except PrecheckFailedError as exc:
        print(f"PRECHECK FALHOU: {exc}")
        return 1

    metadata.save(Path(args.output))
    print(f"deployment_id={metadata.deployment_id}")
    print(f"PRECHECK OK: {metadata.to_dict()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
