from __future__ import annotations

from dataclasses import dataclass

from app.integrations.api.exceptions import ApiClientError
from app.integrations.api.models import SystemCompatibilityDto
from app.integrations.api.system_client import SystemApiClient
from app.services.app_logging import get_logger
from app.services.installation_identity import get_or_create_installation_identity
from app.versioning.compatibility import evaluate_startup_compatibility
from app.versioning.models import CompatibilityStatus
from app.versioning.versions import get_desktop_version, get_minimum_api_version, get_supported_api_contract_version

log = get_logger("compatibility_check")


@dataclass(frozen=True)
class CompatibilityCheckResult:
    """Resultado da verificacao de compatibilidade de startup (Fase 03).

    dto e None quando a verificacao falhou antes de obter uma resposta valida da API
    (timeout, conexao recusada, 5xx, JSON invalido, campo obrigatorio ausente).
    """

    state: CompatibilityStatus
    local_desktop_version: str
    dto: SystemCompatibilityDto | None = None
    user_message: str | None = None
    request_id: str | None = None


def run_compatibility_check(
    system_client: SystemApiClient,
    *,
    desktop_version: str | None = None,
    identity_provider=get_or_create_installation_identity,
) -> CompatibilityCheckResult:
    """Consulta GET /system/compatibility e decide o estado de inicializacao do Desktop.

    Fail-closed: qualquer falha de transporte, resposta invalida ou politica inconsistente
    vira CHECK_FAILED. Nunca libera o sistema com um valor default/otimista quando a
    verificacao atual nao pode ser confirmada.

    Fase 15: sempre envia a identidade persistente da instalacao (Secao 6) -- e o que
    permite o servidor resolver o canal (Secao 7/8) e registrar o heartbeat (Secao 19).
    Falha ao resolver/persistir a identidade localmente nunca bloqueia o startup (fail-open
    aqui especificamente -- o servidor ja trata ausencia de installation_id como fallback
    PRODUCTION, Secao 8).
    """
    version = desktop_version or get_desktop_version()

    try:
        identity = identity_provider()
    except Exception:
        log.exception("Falha ao resolver a identidade persistente da instalacao -- prosseguindo sem ela")
        identity = None

    try:
        dto = system_client.compatibility(
            desktop_version=version,
            installation_id=identity.installation_id if identity else None,
            machine_name=identity.machine_name if identity else None,
            os_version=identity.os_version if identity else None,
        )
    except ApiClientError as exc:
        log.warning(
            "Verificacao de compatibilidade falhou | categoria=%s | status=%s | request_id=%s",
            exc.category, exc.status_code, exc.request_id,
        )
        return CompatibilityCheckResult(
            CompatibilityStatus.CHECK_FAILED,
            version,
            user_message=exc.user_message,
            request_id=exc.request_id,
        )

    try:
        state = evaluate_startup_compatibility(
            maintenance_mode=dto.maintenance_mode,
            api_contract_version=dto.api_contract_version,
            minimum_desktop_version=dto.minimum_desktop_version,
            recommended_desktop_version=dto.recommended_desktop_version,
            server_version=dto.server_version,
            database_schema_version=dto.database_revision,
            desktop_version=version,
            supported_api_contract_version=get_supported_api_contract_version(),
            minimum_api_version=get_minimum_api_version(),
            server_desktop_state=dto.desktop_state,
        )
    except ValueError as exc:
        log.warning("Politica de compatibilidade recebida do servidor e invalida | detalhe=%s", exc)
        return CompatibilityCheckResult(
            CompatibilityStatus.CHECK_FAILED,
            version,
            dto=dto,
            user_message="A politica de compatibilidade recebida do servidor e invalida.",
        )

    log.info(
        "Verificacao de compatibilidade concluida | local_desktop_version=%s | server_version=%s | "
        "api_contract=%s | minimum_desktop=%s | recommended_desktop=%s | compatibility_state=%s",
        version, dto.server_version, dto.api_contract_version,
        dto.minimum_desktop_version, dto.recommended_desktop_version, state.value,
    )
    return CompatibilityCheckResult(state, version, dto=dto)
