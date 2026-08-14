from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MaintenanceStateName(str, Enum):
    """Estados do Maintenance Mode (Fase 14, Secao 3).

    Transicoes validas -- ver api.app.maintenance.transitions:
      OFF -> SCHEDULED | DRAINING | ACTIVE
      SCHEDULED -> DRAINING | ACTIVE | OFF (cancelamento)
      DRAINING -> ACTIVE | OFF (cancelamento seguro)
      ACTIVE -> RECOVERY
      RECOVERY -> OFF
    """

    OFF = "OFF"
    SCHEDULED = "SCHEDULED"
    DRAINING = "DRAINING"
    ACTIVE = "ACTIVE"
    RECOVERY = "RECOVERY"


class MaintenanceReasonCode(str, Enum):
    """Motivo tipado (Secao 7). Somente apresentacao/auditoria -- nunca usado
    pela logica de bloqueio (isso e decidido por state + allowlist)."""

    DEPLOYMENT = "DEPLOYMENT"
    DATABASE_MIGRATION = "DATABASE_MIGRATION"
    EMERGENCY_MAINTENANCE = "EMERGENCY_MAINTENANCE"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    SECURITY = "SECURITY"
    DATA_RECOVERY = "DATA_RECOVERY"
    MANUAL_ADMIN = "MANUAL_ADMIN"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_iso(value: Any) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass(frozen=True)
class MaintenanceState:
    """Registro tipado e imutavel do estado corrente de manutencao (Secao 6).

    Sempre timezone-aware. `message` e somente apresentacao -- nunca controla
    decisao de bloqueio. So existe UM registro corrente por vez (ao contrario
    do historico completo de DeploymentState): cada transicao produz uma nova
    instancia imutavel que substitui a anterior no arquivo persistido, mas o
    `policy_revision` cresce monotonicamente para permitir detectar update
    perdido (Secao 27) mesmo sem guardar o historico completo.
    """

    state: MaintenanceStateName
    maintenance_id: str
    reason_code: MaintenanceReasonCode
    message: str
    policy_revision: int
    updated_at: datetime
    scheduled_start_at: datetime | None = None
    started_at: datetime | None = None
    expected_end_at: datetime | None = None
    activated_by: str | None = None

    def replace(self, **changes: Any) -> "MaintenanceState":
        return dataclasses.replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "maintenance_id": self.maintenance_id,
            "reason_code": self.reason_code.value,
            "message": self.message,
            "policy_revision": self.policy_revision,
            "updated_at": _iso(self.updated_at),
            "scheduled_start_at": _iso(self.scheduled_start_at),
            "started_at": _iso(self.started_at),
            "expected_end_at": _iso(self.expected_end_at),
            "activated_by": self.activated_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MaintenanceState":
        return cls(
            state=MaintenanceStateName(data["state"]),
            maintenance_id=str(data["maintenance_id"]),
            reason_code=MaintenanceReasonCode(data["reason_code"]),
            message=str(data.get("message") or ""),
            policy_revision=int(data["policy_revision"]),
            updated_at=_parse_iso(data["updated_at"]) or datetime.now(timezone.utc),
            scheduled_start_at=_parse_iso(data.get("scheduled_start_at")),
            started_at=_parse_iso(data.get("started_at")),
            expected_end_at=_parse_iso(data.get("expected_end_at")),
            activated_by=data.get("activated_by"),
        )

    @property
    def is_blocking(self) -> bool:
        """ACTIVE/RECOVERY: nenhuma operacao normal (Secao 3). DRAINING e
        deliberadamente PARCIAL e por isso nao entra aqui -- ver
        api.app.maintenance.middleware, que trata DRAINING a parte."""
        return self.state in (MaintenanceStateName.ACTIVE, MaintenanceStateName.RECOVERY)

    @classmethod
    def initial_off(cls, *, now: datetime | None = None) -> "MaintenanceState":
        """Estado assumido quando nao ha nenhum maintenance.json ainda
        (instalacao nova, Secao 9) -- nunca usado para mascarar um arquivo
        corrompido, que tem seu proprio fallback (ver MaintenanceService)."""
        moment = now or datetime.now(timezone.utc)
        return cls(
            state=MaintenanceStateName.OFF,
            maintenance_id="mnt-none",
            reason_code=MaintenanceReasonCode.MANUAL_ADMIN,
            message="Nenhuma manutencao ativa.",
            policy_revision=0,
            updated_at=moment,
        )


def retry_after_seconds_for(state: MaintenanceState, *, default_seconds: int) -> int | None:
    """Retry-After sugerido ao cliente (Secao 10/17). Nao se aplica a
    OFF/SCHEDULED (nada esta sendo bloqueado ainda)."""
    if state.state in (MaintenanceStateName.DRAINING, MaintenanceStateName.ACTIVE, MaintenanceStateName.RECOVERY):
        return default_seconds
    return None
