from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.app.health.models import HealthReport, OverallStatus
from api.app.health.service import HealthService
from api.app.modules.health.schemas import HealthReportResponse, LivenessResponse

router = APIRouter(prefix="/health", tags=["health"])
log = logging.getLogger("api.health")

_service = HealthService()

# Guarda o ultimo overall_status conhecido apenas para logar TRANSICOES de estado
# (Secao 25), nunca para decidir o resultado retornado -- cada chamada a
# /health/ready sempre reavalia de verdade (Secao 17: sem cache mascarando falha).
_last_overall_status: OverallStatus | None = None


def _report_to_response(report: HealthReport) -> HealthReportResponse:
    return HealthReportResponse(
        overall_status=report.overall_status.value,
        checked_at_utc=report.checked_at_utc.isoformat(),
        server_version=report.server_version,
        api_contract_version=report.api_contract_version,
        database_revision=report.database_revision,
        commit_sha=report.commit_sha,
        build_time_utc=report.build_time_utc,
        maintenance_state=report.maintenance_state,
        checks=[
            {
                "name": check.name,
                "status": check.status.value,
                "critical": check.critical,
                "duration_ms": check.duration_ms,
                "message": check.message,
                "error_code": check.error_code,
            }
            for check in report.checks
        ],
    )


def _log_transition(report: HealthReport) -> None:
    global _last_overall_status
    if _last_overall_status is not None and _last_overall_status != report.overall_status:
        failed = [check.name for check in report.checks if check.critical and check.status.value == "FAIL"]
        log.warning(
            "HEALTH_STATE_TRANSITION | from=%s | to=%s | failed_checks=%s | server_version=%s | database_revision=%s",
            _last_overall_status.value, report.overall_status.value, ",".join(failed) or "-",
            report.server_version, report.database_revision,
        )
    _last_overall_status = report.overall_status


@router.get(
    "/live",
    response_model=LivenessResponse,
    summary="Liveness -- o processo esta vivo?",
    description="Nunca consulta o banco nem chama dependencias externas. Responde rapido; falha somente quando a propria aplicacao nao consegue responder.",
)
async def live():
    report = await _service.liveness()
    return LivenessResponse(status="alive", server_version=report.server_version)


@router.get(
    "/ready",
    response_model=HealthReportResponse,
    summary="Readiness -- pode receber trafego?",
    description="Avalia PostgreSQL, revisao/schema esperado e a fonte central de versoes. 200 quando HEALTHY/DEGRADED, 503 quando UNHEALTHY.",
)
async def ready():
    report = await _service.readiness()
    _log_transition(report)
    payload = _report_to_response(report).model_dump()
    status_code = 200 if report.is_ready else 503
    return JSONResponse(status_code=status_code, content=payload)
