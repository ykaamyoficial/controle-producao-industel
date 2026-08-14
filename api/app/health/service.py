from __future__ import annotations

import logging
from datetime import datetime, timezone

from api.app.core.config import get_settings
from api.app.core.versioning import get_api_contract_version, get_server_version
from api.app.health.checks.database import run_database_and_schema_checks
from api.app.health.checks.version import run_version_check
from api.app.health.models import HealthCheckResult, HealthReport, HealthStatus, OverallStatus
from api.app.maintenance.service import build_default_service as build_default_maintenance_service

log = logging.getLogger("api.health")


class HealthService:
    """Camada de avaliacao de saude (Secao 6): coleta os HealthCheckResult e decide
    o overall_status. Independente de FastAPI/HTTP -- o router so serializa o que
    esta classe produz. Liveness nunca toca banco; readiness sempre avalia
    PostgreSQL + schema/revisao (checks criticos) e a versao (nao critico).
    """

    async def liveness(self) -> HealthReport:
        checks = [run_version_check()]
        return self._build_report(checks, database_revision=None)

    async def readiness(self) -> HealthReport:
        database_result, schema_result, raw_check = await run_database_and_schema_checks()
        checks = [run_version_check(), database_result, schema_result]
        return self._build_report(checks, database_revision=raw_check.revision, maintenance_state=_current_maintenance_state())

    def _build_report(self, checks: list[HealthCheckResult], *, database_revision: str | None, maintenance_state: str | None = None) -> HealthReport:
        try:
            server_version = get_server_version()
            api_contract_version = get_api_contract_version()
        except ValueError:
            server_version = "unknown"
            api_contract_version = "unknown"
        # Identidade de build (Fase 07): vem exclusivamente do ENV preenchido pelo
        # Dockerfile a partir do build da imagem -- nenhuma segunda fonte de verdade.
        settings = get_settings()
        return HealthReport(
            overall_status=_overall_status(checks),
            checked_at_utc=datetime.now(timezone.utc),
            server_version=server_version,
            api_contract_version=api_contract_version,
            database_revision=database_revision,
            checks=checks,
            commit_sha=settings.build_commit_sha,
            build_time_utc=settings.build_time_utc or None,
            maintenance_state=maintenance_state,
        )


def _current_maintenance_state() -> str | None:
    """Leitura best-effort (Fase 14, Secao 18): puramente informativa, nunca
    deve derrubar /health/ready -- uma falha aqui vira None, nunca excecao."""
    try:
        return build_default_maintenance_service().get_state().state.value
    except Exception:
        log.warning("MAINTENANCE_STATE_UNAVAILABLE_FOR_READINESS", exc_info=True)
        return None


def _overall_status(checks: list[HealthCheckResult]) -> OverallStatus:
    """HEALTHY apenas se todo check critico esta PASS (Secao 14). Qualquer check
    critico em FAIL -> UNHEALTHY, sem excecao. Um check nao-critico em WARN/FAIL
    nunca sozinho vira UNHEALTHY -- apenas DEGRADED (a aplicacao ainda pode operar)."""
    if any(check.critical and check.status == HealthStatus.FAIL for check in checks):
        return OverallStatus.UNHEALTHY
    if any(check.status in (HealthStatus.FAIL, HealthStatus.WARN) for check in checks):
        return OverallStatus.DEGRADED
    return OverallStatus.HEALTHY
