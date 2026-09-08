from __future__ import annotations

import time

from api.app.core.versioning import get_api_contract_version, get_server_version
from api.app.health.models import HealthCheckResult, HealthStatus

VERSION_CHECK_NAME = "version"


def run_version_check() -> HealthCheckResult:
    """Confirma que a fonte central de versoes (Fase 01) esta carregada e valida.
    Sem I/O -- seguro para liveness. Nao critico: um problema aqui nunca deveria
    acontecer em producao (as constantes sao literais validadas em cada leitura),
    mas se acontecer nao derruba sozinho a readiness -- vira DEGRADED, nao UNHEALTHY."""
    started = time.monotonic()
    try:
        server_version = get_server_version()
        api_contract_version = get_api_contract_version()
    except ValueError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return HealthCheckResult(
            name=VERSION_CHECK_NAME, status=HealthStatus.WARN, critical=False,
            duration_ms=duration_ms, message=f"Configuracao de versao invalida: {exc}",
            error_code="VERSION_CONFIGURATION_INVALID",
        )
    duration_ms = int((time.monotonic() - started) * 1000)
    return HealthCheckResult(
        name=VERSION_CHECK_NAME, status=HealthStatus.PASS, critical=False,
        duration_ms=duration_ms,
        message=f"server_version={server_version} api_contract_version={api_contract_version}",
    )
