from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class HealthStatus(str, Enum):
    """Estado individual de um check. Nunca use strings soltas -- Secao 10."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class OverallStatus(str, Enum):
    """HEALTHY: todos os checks criticos PASS. DEGRADED: opera, mas ha check nao
    critico em WARN/FAIL. UNHEALTHY: qualquer check critico FAIL (Secao 14)."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


@dataclass(frozen=True)
class HealthCheckResult:
    name: str
    status: HealthStatus
    critical: bool
    duration_ms: int
    message: str
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "critical": self.critical,
            "duration_ms": self.duration_ms,
            "message": self.message,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class HealthReport:
    overall_status: OverallStatus
    checked_at_utc: datetime
    server_version: str
    api_contract_version: str
    database_revision: str | None
    checks: list[HealthCheckResult] = field(default_factory=list)
    commit_sha: str | None = None
    build_time_utc: str | None = None
    # Fase 14, Secao 18: somente informativo -- readiness continua decidida
    # exclusivamente pelos checks de infraestrutura acima (PostgreSQL/schema),
    # nunca pelo estado de manutencao, para o pipeline conseguir confirmar
    # readiness tecnica durante RECOVERY sem criar um deadlock com
    # finish_maintenance (que so roda depois de readiness aprovada).
    maintenance_state: str | None = None

    @property
    def is_ready(self) -> bool:
        """Unica condicao que autoriza o codigo HTTP 200 em /health/ready (Secao 14/15):
        HEALTHY ou DEGRADED sao "estado aceito como pronto"; UNHEALTHY nunca e."""
        return self.overall_status in (OverallStatus.HEALTHY, OverallStatus.DEGRADED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status.value,
            "checked_at_utc": self.checked_at_utc.isoformat(),
            "server_version": self.server_version,
            "api_contract_version": self.api_contract_version,
            "database_revision": self.database_revision,
            "commit_sha": self.commit_sha,
            "build_time_utc": self.build_time_utc,
            "checks": [check.to_dict() for check in self.checks],
            "maintenance_state": self.maintenance_state,
        }


class SmokeStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class SmokeStepResult:
    name: str
    status: SmokeStatus
    duration_ms: int
    http_status: int | None = None
    error_code: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "http_status": self.http_status,
            "error_code": self.error_code,
            "message": self.message,
        }


@dataclass(frozen=True)
class SmokeTestReport:
    status: SmokeStatus
    started_at_utc: datetime
    completed_at_utc: datetime
    target_base_url: str
    actual_server_version: str | None
    expected_server_version: str | None = None
    steps: list[SmokeStepResult] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        """Contrato do runner CLI (Secao 21/22): 0 somente em PASS."""
        return 0 if self.status == SmokeStatus.PASS else 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "started_at_utc": self.started_at_utc.isoformat(),
            "completed_at_utc": self.completed_at_utc.isoformat(),
            "target_base_url": self.target_base_url,
            "expected_server_version": self.expected_server_version,
            "actual_server_version": self.actual_server_version,
            "steps": [step.to_dict() for step in self.steps],
        }
