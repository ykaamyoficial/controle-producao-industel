"""Orquestracao de deployment/rollback do servidor (Fase 08).

Servico independente de UI/HTTP (mesmo padrao de api/app/backup/service.py):
chamavel manualmente hoje (scripts/run_rollback.py) e por um pipeline de
deploy futuro, nunca acoplado a PySide nem a nenhum endpoint.

Design geral:
  - DeploymentState (Fase 08, Secao 7) e sempre imutavel: todo avanco de
    estado grava um NOVO registro (DeploymentStateStore.save), nunca reescreve
    um registro anterior in-place -- o historico completo e a fonte de
    verdade para "qual foi a ultima release saudavel" (Secao 8).
  - Rollback NUNCA restaura o PostgreSQL (Secao 6): so reativa a imagem
    Docker anterior. A unica pergunta de seguranca e "o codigo antigo opera
    bem sobre o schema atual, que nao vai ser revertido?" -- respondida por
    schema_compatibility.evaluate_rollback_schema_compatibility usando o
    registro de risco classificado manualmente na Fase 04.
  - Um unico lock de arquivo (reaproveita api.app.backup.lock.BackupLock,
    generico o suficiente para nao duplicar a mesma logica de exclusao mutua
    -- Secao 17) protege TODA leitura+escrita do estado, incluindo a
    reativacao do container: dois deploys/rollbacks nunca correm em paralelo.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, NoReturn

from api.app.audit import service as audit_service
from api.app.audit.models import ActorType, AuditEventType, Component, EventResult
from api.app.backup.lock import BackupLock, BackupLockError
from api.app.core.config import Settings, get_settings
from api.app.deployment import docker_control
from api.app.deployment.exceptions import (
    ConcurrentDeploymentOperationError,
    DeploymentError,
    InvalidDeploymentTransitionError,
    RollbackFailedError,
    RollbackNotAllowedError,
)
from api.app.deployment.models import DeploymentState, DeploymentStatus
from api.app.deployment.naming import build_deployment_id
from api.app.deployment.schema_compatibility import evaluate_rollback_schema_compatibility
from api.app.deployment.state_store import DeploymentStateStore
from api.app.health.smoke import SmokeTestRunner

log = logging.getLogger("api.deployment")

ROOT_DIR = Path(__file__).resolve().parents[3]

_ALLOWED_TRANSITIONS: dict[DeploymentStatus, frozenset[DeploymentStatus]] = {
    DeploymentStatus.PREPARING: frozenset({DeploymentStatus.DEPLOYING, DeploymentStatus.FAILED}),
    DeploymentStatus.DEPLOYING: frozenset({DeploymentStatus.VALIDATING, DeploymentStatus.FAILED}),
    DeploymentStatus.VALIDATING: frozenset({DeploymentStatus.HEALTHY, DeploymentStatus.FAILED}),
    DeploymentStatus.FAILED: frozenset({DeploymentStatus.ROLLING_BACK, DeploymentStatus.MANUAL_INTERVENTION_REQUIRED}),
    DeploymentStatus.ROLLING_BACK: frozenset({DeploymentStatus.ROLLED_BACK, DeploymentStatus.ROLLBACK_FAILED}),
    DeploymentStatus.ROLLBACK_FAILED: frozenset({DeploymentStatus.MANUAL_INTERVENTION_REQUIRED}),
    DeploymentStatus.HEALTHY: frozenset(),
    DeploymentStatus.ROLLED_BACK: frozenset(),
    DeploymentStatus.MANUAL_INTERVENTION_REQUIRED: frozenset(),
}


class DeploymentOrchestrator:
    def __init__(
        self,
        *,
        state_store: DeploymentStateStore,
        lock_path: Path,
        lock_timeout_seconds: int,
        container_name: str,
        network: str,
        health_base_url: str,
        validation_timeout_seconds: float = 60.0,
        smoke_runner_factory: Callable[[str, str | None], SmokeTestRunner] | None = None,
        docker=docker_control,
        clock: Callable[[], datetime] | None = None,
    ):
        self._state_store = state_store
        self._lock_path = lock_path
        self._lock_timeout_seconds = lock_timeout_seconds
        self._container_name = container_name
        self._network = network
        self._health_base_url = health_base_url
        self._validation_timeout_seconds = validation_timeout_seconds
        self._smoke_runner_factory = smoke_runner_factory or (
            lambda base_url, expected_version: SmokeTestRunner(base_url=base_url, expected_server_version=expected_version)
        )
        self._docker = docker
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # -- ciclo de vida de um deploy direto ---------------------------------

    def begin_deployment(
        self,
        *,
        target_version: str,
        target_image_ref: str,
        target_image_digest: str | None = None,
        database_revision_before: str | None,
        source: str = "manual",
    ) -> DeploymentState:
        with self._locked():
            latest = self._state_store.latest()
            if latest is not None and not latest.is_terminal:
                raise ConcurrentDeploymentOperationError(
                    f"Deployment '{latest.deployment_id}' ainda em status={latest.status.value} (nao terminal). "
                    "Execute recover_incomplete_deployment_state() antes de iniciar um novo deployment."
                )
            previous = self._state_store.last_healthy()
            state = DeploymentState(
                deployment_id=build_deployment_id(kind="deploy", version=target_version, now=self._clock()),
                started_at_utc=self._clock(),
                target_version=target_version,
                target_image_ref=target_image_ref,
                target_image_digest=target_image_digest,
                database_revision_before=database_revision_before,
                status=DeploymentStatus.PREPARING,
                source=source,
                previous_version=previous.target_version if previous else None,
                previous_image_ref=previous.target_image_ref if previous else None,
                previous_image_digest=previous.target_image_digest if previous else None,
            )
            self._state_store.save(state)
            log.info(
                "DEPLOYMENT_PREPARING | deployment_id=%s | target_version=%s | previous_version=%s",
                state.deployment_id, target_version, state.previous_version,
            )
            audit_service.record_event(
                event_type=AuditEventType.DEPLOYMENT_STARTED, component=Component.DEPLOYMENT, result=EventResult.STARTED,
                actor_type=ActorType.DEPLOY_RUNNER, deployment_id=state.deployment_id, release_id=target_version,
                version=target_version, correlation_id=state.deployment_id,
                message=f"Deployment {state.deployment_id} iniciado para {target_version}.",
                metadata={"previous_version": state.previous_version, "source": source},
            )
            return state

    def mark_deploying(self, deployment_id: str, *, backup_id: str | None = None) -> DeploymentState:
        return self._locked_transition(deployment_id, DeploymentStatus.DEPLOYING, backup_id=backup_id)

    def mark_validating(self, deployment_id: str) -> DeploymentState:
        return self._locked_transition(deployment_id, DeploymentStatus.VALIDATING)

    def mark_healthy(self, deployment_id: str, *, database_revision_after: str | None) -> DeploymentState:
        state = self._locked_transition(
            deployment_id, DeploymentStatus.HEALTHY,
            finished_at_utc=self._clock(), database_revision_after=database_revision_after,
        )
        audit_service.record_event(
            event_type=AuditEventType.DEPLOYMENT_SUCCEEDED, component=Component.DEPLOYMENT, result=EventResult.SUCCEEDED,
            actor_type=ActorType.DEPLOY_RUNNER, deployment_id=deployment_id, release_id=state.target_version,
            version=state.target_version, correlation_id=deployment_id,
            message=f"Deployment {deployment_id} concluido com sucesso (HEALTHY).",
        )
        return state

    def mark_failed(self, deployment_id: str, *, reason: str, failed_stage: str | None = None) -> DeploymentState:
        state = self._locked_transition(
            deployment_id, DeploymentStatus.FAILED,
            finished_at_utc=self._clock(), error_message=reason, failed_stage=failed_stage,
        )
        audit_service.record_event(
            event_type=AuditEventType.DEPLOYMENT_FAILED, component=Component.DEPLOYMENT, result=EventResult.FAILED,
            actor_type=ActorType.DEPLOY_RUNNER, deployment_id=deployment_id, release_id=state.target_version,
            version=state.target_version, correlation_id=deployment_id,
            message=f"Deployment {deployment_id} falhou em {failed_stage or 'estagio desconhecido'}: {reason}",
            metadata={"failed_stage": failed_stage},
        )
        return state

    # -- rollback ------------------------------------------------------------

    def rollback_to_previous_healthy_release(
        self,
        *,
        current_database_revision: str | None,
        reason: str,
        failed_deployment_id: str | None = None,
        container_env: dict[str, str] | None = None,
        source: str = "manual",
    ) -> DeploymentState:
        """Fluxo completo de rollback (Secao 10). Sincrono de proposito: quem
        chama resolve `current_database_revision` de antemao (mesmo padrao de
        PreDeploymentBackupService.run(database_revision=...) na Fase 05), para
        este metodo nunca precisar de um event loop."""
        with self._locked():
            failed_state = self._load_failed_deployment(failed_deployment_id)
            audit_service.record_event(
                event_type=AuditEventType.ROLLBACK_REQUESTED, component=Component.ROLLBACK, result=EventResult.STARTED,
                actor_type=ActorType.SYSTEM if source != "manual-cli" else ActorType.USER,
                deployment_id=failed_deployment_id, correlation_id=failed_deployment_id,
                message=f"Rollback solicitado: {reason}", metadata={"reason": reason, "source": source},
            )

            previous = self._state_store.last_healthy()
            if previous is None:
                message = "Nenhuma release HEALTHY anterior registrada -- rollback automatico impossivel."
                self._deny_rollback(failed_state, message)
                raise RollbackNotAllowedError(message)

            from_revision = previous.database_revision_after or previous.database_revision_before
            compatibility = evaluate_rollback_schema_compatibility(from_revision=from_revision, to_revision=current_database_revision)
            audit_service.record_event(
                event_type=AuditEventType.ROLLBACK_COMPATIBILITY_CHECKED, component=Component.ROLLBACK,
                result=EventResult.SUCCEEDED if compatibility.compatible else EventResult.BLOCKED,
                actor_type=ActorType.SYSTEM, deployment_id=failed_deployment_id, correlation_id=failed_deployment_id,
                version=previous.target_version, message=compatibility.reason,
                metadata={"from_revision": from_revision, "to_revision": current_database_revision},
            )
            if not compatibility.compatible:
                self._deny_rollback(failed_state, compatibility.reason)
                audit_service.record_event(
                    event_type=AuditEventType.ROLLBACK_BLOCKED_UNSAFE_SCHEMA, component=Component.ROLLBACK, result=EventResult.BLOCKED,
                    actor_type=ActorType.SYSTEM, deployment_id=failed_deployment_id, correlation_id=failed_deployment_id,
                    message=compatibility.reason,
                )
                raise RollbackNotAllowedError(compatibility.reason)

            if failed_state is not None:
                self._state_store.save(failed_state.replace(rollback_allowed=True, rollback_reason=compatibility.reason))

            rollback_state = DeploymentState(
                deployment_id=build_deployment_id(kind="rollback", version=previous.target_version, now=self._clock()),
                started_at_utc=self._clock(),
                target_version=previous.target_version,
                target_image_ref=previous.target_image_ref,
                target_image_digest=previous.target_image_digest,
                database_revision_before=current_database_revision,
                status=DeploymentStatus.ROLLING_BACK,
                source=source,
                previous_version=failed_state.target_version if failed_state else None,
                previous_image_ref=failed_state.target_image_ref if failed_state else None,
                previous_image_digest=failed_state.target_image_digest if failed_state else None,
                rollback_allowed=True,
                rollback_reason=compatibility.reason,
            )
            self._state_store.save(rollback_state)
            log.info(
                "ROLLBACK_STARTED | deployment_id=%s | target_version=%s | reason=%s",
                rollback_state.deployment_id, previous.target_version, reason,
            )
            audit_service.record_event(
                event_type=AuditEventType.ROLLBACK_STARTED, component=Component.ROLLBACK, result=EventResult.STARTED,
                actor_type=ActorType.SYSTEM, deployment_id=rollback_state.deployment_id, release_id=previous.target_version,
                version=previous.target_version, correlation_id=failed_deployment_id or rollback_state.deployment_id,
                message=f"Rollback {rollback_state.deployment_id} iniciado para {previous.target_version}.",
            )

            return self._execute_rollback(rollback_state, previous_target_image_ref=previous.target_image_ref, container_env=container_env or {})

    def _execute_rollback(self, rollback_state: DeploymentState, *, previous_target_image_ref: str, container_env: dict[str, str]) -> DeploymentState:
        already_active = self._docker.current_image_ref(self._container_name) == previous_target_image_ref
        if already_active:
            log.info("ROLLBACK_IDEMPOTENT_NOOP | deployment_id=%s | container ja executa a imagem alvo", rollback_state.deployment_id)
        else:
            self._docker.stop_and_remove_container(self._container_name)
            try:
                self._docker.run_container(
                    name=self._container_name, image_ref=previous_target_image_ref,
                    network=self._network, env=container_env, port=8000,
                )
            except RuntimeError as exc:
                self._fail_rollback(rollback_state, str(exc))

        if not self._docker.wait_for_healthy(self._container_name, timeout_seconds=self._validation_timeout_seconds):
            logs = self._safe_recent_logs()
            self._fail_rollback(rollback_state, f"Container nao ficou 'healthy' apos rollback dentro do timeout. Ultimos logs: {logs[-500:]}")

        runner = self._smoke_runner_factory(self._health_base_url, rollback_state.target_version)
        report = runner.run()
        if report.status.value != "PASS":
            failing = [step.to_dict() for step in report.steps if step.status.value == "FAIL"]
            self._fail_rollback(rollback_state, f"Smoke test pos-rollback falhou: {failing}")

        final = self._apply_transition(
            rollback_state, DeploymentStatus.ROLLED_BACK,
            finished_at_utc=self._clock(), database_revision_after=rollback_state.database_revision_before,
        )
        log.info("ROLLBACK_SUCCEEDED | deployment_id=%s | target_version=%s", final.deployment_id, final.target_version)
        audit_service.record_event(
            event_type=AuditEventType.ROLLBACK_SUCCEEDED, component=Component.ROLLBACK, result=EventResult.ROLLED_BACK,
            actor_type=ActorType.SYSTEM, deployment_id=final.deployment_id, release_id=final.target_version,
            version=final.target_version, correlation_id=final.deployment_id,
            message=f"Rollback {final.deployment_id} concluido para {final.target_version}.",
        )
        return final

    def _fail_rollback(self, rollback_state: DeploymentState, error_message: str) -> NoReturn:
        failed = self._apply_transition(rollback_state, DeploymentStatus.ROLLBACK_FAILED, finished_at_utc=self._clock(), error_message=error_message)
        audit_service.record_event(
            event_type=AuditEventType.ROLLBACK_FAILED, component=Component.ROLLBACK, result=EventResult.FAILED,
            actor_type=ActorType.SYSTEM, deployment_id=rollback_state.deployment_id, version=rollback_state.target_version,
            correlation_id=rollback_state.deployment_id, message=error_message,
        )
        self._apply_transition(failed, DeploymentStatus.MANUAL_INTERVENTION_REQUIRED)
        log.error("ROLLBACK_FAILED | deployment_id=%s | error=%s", rollback_state.deployment_id, error_message)
        audit_service.record_event(
            event_type=AuditEventType.MANUAL_INTERVENTION_REQUIRED, component=Component.ROLLBACK, result=EventResult.REQUIRES_MANUAL_INTERVENTION,
            actor_type=ActorType.SYSTEM, deployment_id=rollback_state.deployment_id, correlation_id=rollback_state.deployment_id,
            message=f"Rollback de {rollback_state.deployment_id} falhou -- intervencao manual necessaria.",
        )
        raise RollbackFailedError(error_message)

    # -- recuperacao apos reinicio (Secao 24) --------------------------------

    def recover_incomplete_deployment_state(
        self,
        *,
        running_container_image: str | None,
        running_container_healthy: bool | None,
    ) -> DeploymentState | None:
        """Chamada no startup, ANTES de qualquer novo begin_deployment/rollback.
        Nunca confia cegamente no ultimo status persistido: so reafirma sucesso
        se o estado REAL observado do container confirmar a imagem alvo e
        saudavel; qualquer ambiguidade escala para MANUAL_INTERVENTION_REQUIRED
        em vez de assumir."""
        with self._locked():
            latest = self._state_store.latest()
            if latest is None or latest.is_terminal:
                return latest

            log.warning("DEPLOYMENT_RECOVERY_STARTED | deployment_id=%s | stuck_status=%s", latest.deployment_id, latest.status.value)

            if running_container_image == latest.target_image_ref and running_container_healthy:
                final_status = DeploymentStatus.ROLLED_BACK if latest.status == DeploymentStatus.ROLLING_BACK else DeploymentStatus.HEALTHY
                recovered = latest.replace(
                    status=final_status,
                    finished_at_utc=self._clock(),
                    database_revision_after=latest.database_revision_before,
                    error_message=(
                        "Recuperado apos reinicio: o processo anterior morreu antes de persistir o "
                        "estado final, mas o container ativo confirma a imagem alvo e saudavel."
                    ),
                )
                self._state_store.save(recovered)
                log.warning("DEPLOYMENT_RECOVERY_RESOLVED | deployment_id=%s | resolved_status=%s", recovered.deployment_id, final_status.value)
                return recovered

            recovered = latest.replace(
                status=DeploymentStatus.MANUAL_INTERVENTION_REQUIRED,
                finished_at_utc=self._clock(),
                error_message=(
                    f"Processo anterior interrompido em status={latest.status.value} sem confirmar a transicao final. "
                    f"Imagem ativa observada={running_container_image!r}, saudavel={running_container_healthy!r}. "
                    "Requer investigacao/confirmacao manual antes de qualquer novo deploy/rollback."
                ),
            )
            self._state_store.save(recovered)
            log.warning("DEPLOYMENT_RECOVERY_ESCALATED | deployment_id=%s", recovered.deployment_id)
            return recovered

    # -- internos --------------------------------------------------------

    @contextmanager
    def _locked(self) -> Iterator[None]:
        try:
            with BackupLock(self._lock_path, timeout_seconds=self._lock_timeout_seconds, owner="deployment-orchestrator"):
                yield
        except BackupLockError as exc:
            raise ConcurrentDeploymentOperationError(str(exc)) from exc

    def _locked_transition(self, deployment_id: str, new_status: DeploymentStatus, **changes) -> DeploymentState:
        with self._locked():
            state = self._state_store.load(deployment_id)
            if state is None:
                raise DeploymentError(f"Deployment '{deployment_id}' nao encontrado.")
            return self._apply_transition(state, new_status, **changes)

    def _apply_transition(self, state: DeploymentState, new_status: DeploymentStatus, **changes) -> DeploymentState:
        allowed = _ALLOWED_TRANSITIONS.get(state.status, frozenset())
        if new_status not in allowed:
            raise InvalidDeploymentTransitionError(
                f"Transicao invalida: {state.status.value} -> {new_status.value} (deployment_id={state.deployment_id})."
            )
        next_state = state.replace(status=new_status, **changes)
        self._state_store.save(next_state)
        log.info("DEPLOYMENT_TRANSITION | deployment_id=%s | %s -> %s", state.deployment_id, state.status.value, new_status.value)
        return next_state

    def _load_failed_deployment(self, deployment_id: str | None) -> DeploymentState | None:
        if deployment_id is None:
            return None
        state = self._state_store.load(deployment_id)
        if state is None:
            raise DeploymentError(f"Deployment '{deployment_id}' nao encontrado.")
        if state.status != DeploymentStatus.FAILED:
            raise InvalidDeploymentTransitionError(
                f"Rollback so pode ser vinculado a um deployment em status=FAILED (atual={state.status.value})."
            )
        return state

    def _deny_rollback(self, failed_state: DeploymentState | None, reason: str) -> None:
        if failed_state is None:
            return
        self._apply_transition(failed_state, DeploymentStatus.MANUAL_INTERVENTION_REQUIRED, rollback_allowed=False, rollback_reason=reason)

    def _safe_recent_logs(self) -> str:
        try:
            return self._docker.recent_logs(self._container_name)
        except Exception:
            return "(logs indisponiveis)"


def build_default_orchestrator(*, settings: Settings | None = None) -> DeploymentOrchestrator:
    settings = settings or get_settings()
    configured_dir = Path(settings.deployment_state_dir)
    state_dir = configured_dir if configured_dir.is_absolute() else ROOT_DIR / configured_dir
    return DeploymentOrchestrator(
        state_store=DeploymentStateStore(state_dir),
        lock_path=state_dir / ".deployment.lock",
        lock_timeout_seconds=settings.deployment_lock_timeout_seconds,
        container_name=settings.deployment_container_name,
        network=settings.deployment_docker_network,
        health_base_url=settings.deployment_health_base_url,
        validation_timeout_seconds=settings.deployment_validation_timeout_seconds,
    )
