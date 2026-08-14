"""Orquestracao do Maintenance Mode (Fase 14).

Mesmo padrao arquitetural de api/app/deployment/service.py: servico
independente de HTTP/PySide, chamavel tanto pelos routers da API quanto
diretamente pelos scripts do pipeline de deploy (Fase 09) ou por um CLI
administrativo futuro. Um unico lock de arquivo (reaproveita
api.app.backup.lock.BackupLock) protege toda leitura+escrita do estado,
para dois comandos administrativos concorrentes nunca corromperem o
maintenance.json nem se sobrescreverem silenciosamente (Secao 27).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from api.app.audit import service as audit_service
from api.app.audit.models import ActorType, AuditEventType, Component, EventResult, EventSeverity
from api.app.backup.lock import BackupLock, BackupLockError
from api.app.core.config import Settings, get_settings
from api.app.maintenance.exceptions import (
    ConcurrentMaintenanceOperationError,
    InvalidMaintenanceTransitionError,
    MaintenanceStateCorruptedError,
)
from api.app.maintenance.models import MaintenanceReasonCode, MaintenanceState, MaintenanceStateName
from api.app.maintenance.naming import build_maintenance_id
from api.app.maintenance.store import MaintenanceStateStore
from api.app.maintenance.transitions import is_transition_allowed

log = logging.getLogger("api.maintenance")

ROOT_DIR = Path(__file__).resolve().parents[3]

# maintenance_id sintetico usado somente no fallback conservador de arquivo
# corrompido (Secao 26) -- nunca gravado no disco, apenas devolvido em
# memoria ate um administrador agir.
CORRUPTED_STATE_MAINTENANCE_ID = "mnt-corrupted-state"


class MaintenanceService:
    def __init__(
        self,
        *,
        store: MaintenanceStateStore,
        lock_path: Path,
        lock_timeout_seconds: int,
        clock: Callable[[], datetime] | None = None,
    ):
        self._store = store
        self._lock_path = lock_path
        self._lock_timeout_seconds = lock_timeout_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # -- leitura --------------------------------------------------------

    def get_state(self) -> MaintenanceState:
        """Leitura publica (Secao 10/25): sempre le do disco -- nunca guarda
        cache em memoria entre chamadas, para enxergar imediatamente uma
        mudanca feita por outro processo (ex.: o pipeline de deploy rodando
        como processo separado). os.replace() garante que isso nunca ve um
        arquivo parcialmente escrito, entao ler sem lock aqui e seguro."""
        return self._load_current()

    def _load_current(self) -> MaintenanceState:
        try:
            state = self._store.load()
        except MaintenanceStateCorruptedError:
            log.critical("MAINTENANCE_STATE_LOAD_FAILED path=%s", self._store.path, exc_info=True)
            audit_service.record_event(
                event_type=AuditEventType.MAINTENANCE_STATE_LOAD_FAILED, component=Component.MAINTENANCE,
                result=EventResult.FAILED, severity=EventSeverity.CRITICAL, actor_type=ActorType.SERVER,
                message=f"Estado de manutencao ilegivel em {self._store.path}.",
            )
            return self._corrupted_fallback_state()
        return state if state is not None else MaintenanceState.initial_off(now=self._clock())

    def _corrupted_fallback_state(self) -> MaintenanceState:
        """Comportamento conservador (Secao 9/26): arquivo ilegivel nunca
        libera operacao silenciosamente -- assume ACTIVE ate um
        administrador confirmar e agir explicitamente. Nao reescreve o
        arquivo corrompido (preservado para investigacao); a proxima escrita
        administrativa valida substitui o conteudo normalmente."""
        return MaintenanceState(
            state=MaintenanceStateName.ACTIVE,
            maintenance_id=CORRUPTED_STATE_MAINTENANCE_ID,
            reason_code=MaintenanceReasonCode.INFRASTRUCTURE,
            message="Estado de manutencao ilegivel no servidor. Operacao bloqueada por seguranca ate intervencao manual.",
            policy_revision=0,
            updated_at=self._clock(),
        )

    # -- operacoes administrativas (Secao 12) ----------------------------

    def schedule_maintenance(
        self,
        *,
        reason_code: MaintenanceReasonCode,
        message: str,
        scheduled_start_at: datetime,
        expected_end_at: datetime | None,
        activated_by: str,
        maintenance_id: str | None = None,
        correlation_id: str | None = None,
    ) -> MaintenanceState:
        return self._transition(
            MaintenanceStateName.SCHEDULED,
            event="MAINTENANCE_SCHEDULED",
            allowed_sources=(MaintenanceStateName.OFF, MaintenanceStateName.SCHEDULED),
            reason_code=reason_code,
            message=message,
            scheduled_start_at=scheduled_start_at,
            expected_end_at=expected_end_at,
            activated_by=activated_by,
            maintenance_id=maintenance_id,
            correlation_id=correlation_id,
        )

    def begin_draining(
        self,
        *,
        reason_code: MaintenanceReasonCode,
        message: str,
        expected_end_at: datetime | None,
        activated_by: str,
        maintenance_id: str | None = None,
        correlation_id: str | None = None,
    ) -> MaintenanceState:
        return self._transition(
            MaintenanceStateName.DRAINING,
            event="MAINTENANCE_DRAINING",
            allowed_sources=(MaintenanceStateName.OFF, MaintenanceStateName.SCHEDULED, MaintenanceStateName.DRAINING),
            reason_code=reason_code,
            message=message,
            expected_end_at=expected_end_at,
            activated_by=activated_by,
            maintenance_id=maintenance_id,
            correlation_id=correlation_id,
        )

    def activate_maintenance(
        self,
        *,
        reason_code: MaintenanceReasonCode,
        message: str,
        expected_end_at: datetime | None,
        activated_by: str,
        maintenance_id: str | None = None,
        correlation_id: str | None = None,
    ) -> MaintenanceState:
        return self._transition(
            MaintenanceStateName.ACTIVE,
            event="MAINTENANCE_ACTIVATED",
            allowed_sources=(MaintenanceStateName.OFF, MaintenanceStateName.SCHEDULED, MaintenanceStateName.DRAINING, MaintenanceStateName.ACTIVE),
            reason_code=reason_code,
            message=message,
            expected_end_at=expected_end_at,
            activated_by=activated_by,
            maintenance_id=maintenance_id,
            stamp_started=True,
            correlation_id=correlation_id,
        )

    def begin_recovery(self, *, activated_by: str, message: str | None = None, correlation_id: str | None = None) -> MaintenanceState:
        return self._transition(
            MaintenanceStateName.RECOVERY,
            event="MAINTENANCE_RECOVERY_STARTED",
            allowed_sources=(MaintenanceStateName.ACTIVE, MaintenanceStateName.RECOVERY),
            message=message,
            activated_by=activated_by,
            correlation_id=correlation_id,
        )

    def finish_maintenance(self, *, activated_by: str, correlation_id: str | None = None) -> MaintenanceState:
        return self._transition(
            MaintenanceStateName.OFF,
            event="MAINTENANCE_FINISHED",
            allowed_sources=(MaintenanceStateName.RECOVERY, MaintenanceStateName.OFF),
            activated_by=activated_by,
            reset=True,
            correlation_id=correlation_id,
        )

    def cancel_scheduled_maintenance(self, *, activated_by: str, correlation_id: str | None = None) -> MaintenanceState:
        return self._transition(
            MaintenanceStateName.OFF,
            event="MAINTENANCE_CANCELLED",
            allowed_sources=(MaintenanceStateName.SCHEDULED, MaintenanceStateName.DRAINING, MaintenanceStateName.OFF),
            activated_by=activated_by,
            reset=True,
            correlation_id=correlation_id,
        )

    # -- internos ---------------------------------------------------------

    def _transition(
        self,
        target: MaintenanceStateName,
        *,
        event: str,
        allowed_sources: tuple[MaintenanceStateName, ...],
        activated_by: str,
        reason_code: MaintenanceReasonCode | None = None,
        message: str | None = None,
        scheduled_start_at: datetime | None = None,
        expected_end_at: datetime | None = None,
        maintenance_id: str | None = None,
        stamp_started: bool = False,
        reset: bool = False,
        correlation_id: str | None = None,
    ) -> MaintenanceState:
        with self._locked():
            current = self._load_current()

            if current.state not in allowed_sources:
                raise InvalidMaintenanceTransitionError(
                    f"Operacao '{event}' nao permitida a partir do estado atual={current.state.value} "
                    f"(maintenance_id={current.maintenance_id})."
                )

            # Idempotencia (Secao 27): repetir a MESMA operacao com o MESMO
            # maintenance_id nao corrompe o estado -- devolve o registro
            # corrente sem gravar nada novo. Um maintenance_id DIFERENTE
            # enquanto ja se esta no estado alvo e rejeitado explicitamente
            # (nunca sobrescreve silenciosamente uma janela em andamento).
            if current.state == target:
                if maintenance_id and maintenance_id != current.maintenance_id:
                    raise InvalidMaintenanceTransitionError(
                        f"Ja existe uma manutencao em {target.value} com maintenance_id="
                        f"'{current.maintenance_id}'. Finalize/cancele a atual antes de iniciar outra "
                        f"com maintenance_id='{maintenance_id}'."
                    )
                log.info(
                    "MAINTENANCE_IDEMPOTENT_NOOP | event=%s | state=%s | maintenance_id=%s | actor=%s",
                    event, target.value, current.maintenance_id, activated_by,
                )
                return current

            if not is_transition_allowed(current.state, target):
                raise InvalidMaintenanceTransitionError(
                    f"Transicao invalida: {current.state.value} -> {target.value} (maintenance_id={current.maintenance_id})."
                )

            now = self._clock()

            if reset:
                next_state = MaintenanceState.initial_off(now=now).replace(
                    policy_revision=current.policy_revision + 1,
                    activated_by=activated_by,
                )
            else:
                if maintenance_id:
                    resolved_id = maintenance_id
                elif current.state != MaintenanceStateName.OFF:
                    resolved_id = current.maintenance_id
                else:
                    resolved_id = build_maintenance_id(now=now)

                next_state = current.replace(
                    state=target,
                    maintenance_id=resolved_id,
                    reason_code=reason_code if reason_code is not None else current.reason_code,
                    message=message if message is not None else current.message,
                    scheduled_start_at=scheduled_start_at if scheduled_start_at is not None else current.scheduled_start_at,
                    expected_end_at=expected_end_at if expected_end_at is not None else current.expected_end_at,
                    started_at=now if stamp_started else current.started_at,
                    activated_by=activated_by,
                    policy_revision=current.policy_revision + 1,
                    updated_at=now,
                )

            self._store.save(next_state)
            log.info(
                "%s | maintenance_id=%s | %s -> %s | reason=%s | actor=%s | policy_revision=%s",
                event, next_state.maintenance_id, current.state.value, target.value,
                next_state.reason_code.value, activated_by, next_state.policy_revision,
            )
            audit_result = EventResult.CANCELLED if event == "MAINTENANCE_CANCELLED" else EventResult.SUCCEEDED
            audit_service.record_event(
                event_type=AuditEventType(event), component=Component.MAINTENANCE, result=audit_result,
                actor_type=ActorType.ADMIN_API, actor_id=activated_by,
                maintenance_id=next_state.maintenance_id, correlation_id=correlation_id or next_state.maintenance_id,
                message=f"{event}: {current.state.value} -> {target.value}",
                metadata={"reason_code": next_state.reason_code.value, "policy_revision": next_state.policy_revision},
            )
            return next_state

    @contextmanager
    def _locked(self) -> Iterator[None]:
        try:
            with BackupLock(self._lock_path, timeout_seconds=self._lock_timeout_seconds, owner="maintenance-mode"):
                yield
        except BackupLockError as exc:
            raise ConcurrentMaintenanceOperationError(str(exc)) from exc


def build_default_service(*, settings: Settings | None = None) -> MaintenanceService:
    settings = settings or get_settings()
    configured_dir = Path(settings.maintenance_state_dir)
    state_dir = configured_dir if configured_dir.is_absolute() else ROOT_DIR / configured_dir
    return MaintenanceService(
        store=MaintenanceStateStore(state_dir / "maintenance.json"),
        lock_path=state_dir / ".maintenance.lock",
        lock_timeout_seconds=settings.maintenance_lock_timeout_seconds,
    )
