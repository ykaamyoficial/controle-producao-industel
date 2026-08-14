"""VERIFY do deployment de producao (Fase 09, Secoes 20-21).

Readiness com retry/intervalo/timeout: reaproveita o HEALTHCHECK ja embutido
na propria imagem (Fase 07, chama /api/v1/health/ready da Fase 06) via
`docker_control.wait_for_healthy` -- nao reimplementa um novo loop de polling
HTTP paralelo. Depois disso, roda os smoke tests oficiais (Fase 06) uma unica
vez (a especificacao nao pede retry de smoke, so de readiness) e confirma que
a versao reportada e exatamente a release alvo antes de aprovar o deployment.
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
from api.app.database.health import current_database_revision  # noqa: E402
from api.app.database.session import dispose_engine  # noqa: E402
from api.app.deployment import docker_control  # noqa: E402
from api.app.deployment.service import DeploymentOrchestrator, build_default_orchestrator  # noqa: E402
from api.app.health.smoke import SmokeTestRunner  # noqa: E402
from api.app.maintenance.models import MaintenanceStateName  # noqa: E402
from api.app.maintenance.service import MaintenanceService, build_default_service  # noqa: E402
from scripts.deployment.metadata import DeploymentMetadata  # noqa: E402


class VerifyFailedError(RuntimeError):
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


def _release_maintenance_if_owned(maintenance_service: MaintenanceService, *, correlation_id: str) -> None:
    """So finaliza a manutencao se ela estiver de fato em RECOVERY (Fase 14,
    Secao 21) -- nunca chama finish_maintenance as cegas: um VERIFY rodado
    manualmente/fora do pipeline, sem Maintenance Mode envolvido, nao deve
    forcar uma transicao invalida."""
    if maintenance_service.get_state().state == MaintenanceStateName.RECOVERY:
        maintenance_service.finish_maintenance(activated_by="deploy-pipeline", correlation_id=correlation_id)


def run_verify(
    *,
    metadata: DeploymentMetadata,
    container_name: str,
    base_url: str,
    readiness_timeout_seconds: float = 90.0,
    readiness_poll_interval_seconds: float = 3.0,
    orchestrator: DeploymentOrchestrator | None = None,
    docker=docker_control,
    runner_factory=None,
    current_revision_fn=_current_revision,
    maintenance_service: MaintenanceService | None = None,
) -> None:
    orchestrator = orchestrator or build_default_orchestrator()
    runner_factory = runner_factory or (lambda url, version: SmokeTestRunner(base_url=url, expected_server_version=version))
    maintenance_service = maintenance_service or build_default_service()
    corr = metadata.correlation_id or metadata.deployment_id

    def _audit(event_type: AuditEventType, result: EventResult, message: str) -> None:
        audit_service.record_event(
            event_type=event_type, component=Component.DEPLOYMENT, result=result, actor_type=ActorType.DEPLOY_RUNNER,
            deployment_id=metadata.deployment_id, release_id=metadata.release_version, version=metadata.release_version,
            correlation_id=corr, message=message,
        )

    if not docker.wait_for_healthy(container_name, timeout_seconds=readiness_timeout_seconds, poll_interval_seconds=readiness_poll_interval_seconds):
        logs = docker.recent_logs(container_name)
        reason = f"readiness nao atingida dentro de {readiness_timeout_seconds}s. Ultimos logs: {logs[-500:]}"
        orchestrator.mark_failed(metadata.deployment_id, reason=reason, failed_stage="READINESS")
        _audit(AuditEventType.READINESS_FAILED, EventResult.FAILED, reason)
        # Maintenance permanece ACTIVE (Secao 20: "manter ACTIVE ou RECOVERY
        # conforme o ponto da falha") -- nunca chega a entrar em RECOVERY.
        raise VerifyFailedError(reason, failed_stage="READINESS")
    _audit(AuditEventType.READINESS_SUCCEEDED, EventResult.SUCCEEDED, f"Container {container_name} saudavel.")

    # Maintenance Mode (Fase 14, Secao 19, passos 8-9): liveness do container
    # confirmada -> RECOVERY, ANTES de rodar readiness tecnica/smoke tests.
    # So-ativo (guardado) para nao quebrar um VERIFY manual sem Maintenance
    # Mode em uso (ver _release_maintenance_if_owned).
    if maintenance_service.get_state().state == MaintenanceStateName.ACTIVE:
        maintenance_service.begin_recovery(activated_by="deploy-pipeline", correlation_id=corr)

    runner = runner_factory(base_url, metadata.release_version)
    report = runner.run()
    if report.status.value != "PASS":
        failing = [step.to_dict() for step in report.steps if step.status.value == "FAIL"]
        reason = f"smoke test falhou: {failing}"
        orchestrator.mark_failed(metadata.deployment_id, reason=reason, failed_stage="SMOKE")
        _audit(AuditEventType.SMOKE_TESTS_FAILED, EventResult.FAILED, reason)
        # Maintenance permanece RECOVERY (Secao 20) -- finish_maintenance so
        # roda apos smoke tests aprovados, nunca por pressao.
        raise VerifyFailedError(reason, failed_stage="SMOKE")

    if report.actual_server_version != metadata.release_version:
        reason = f"versao reportada ({report.actual_server_version!r}) diverge da release alvo ({metadata.release_version!r})."
        orchestrator.mark_failed(metadata.deployment_id, reason=reason, failed_stage="SMOKE")
        _audit(AuditEventType.SMOKE_TESTS_FAILED, EventResult.FAILED, reason)
        raise VerifyFailedError(reason, failed_stage="SMOKE")
    _audit(AuditEventType.SMOKE_TESTS_SUCCEEDED, EventResult.SUCCEEDED, f"Smoke tests aprovados para {metadata.release_version}.")

    revision_after = current_revision_fn()
    orchestrator.mark_healthy(metadata.deployment_id, database_revision_after=revision_after)
    # Maintenance Mode (Secao 19, passo 12): so agora, com readiness E smoke
    # tests aprovados, a manutencao pode ser encerrada.
    _release_maintenance_if_owned(maintenance_service, correlation_id=corr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verifica readiness + smoke tests pos-deploy (Fase 09).")
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--container-name", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--readiness-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--readiness-poll-interval-seconds", type=float, default=3.0)
    args = parser.parse_args(argv)

    metadata = DeploymentMetadata.load(Path(args.metadata))
    try:
        run_verify(
            metadata=metadata, container_name=args.container_name, base_url=args.base_url,
            readiness_timeout_seconds=args.readiness_timeout_seconds,
            readiness_poll_interval_seconds=args.readiness_poll_interval_seconds,
        )
    except VerifyFailedError as exc:
        print(f"VERIFY FALHOU [{exc.failed_stage}]: {exc}")
        return 1

    print(f"VERIFY OK: deployment_id={metadata.deployment_id} status=HEALTHY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
