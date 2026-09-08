from __future__ import annotations

from app.versioning.models import CompatibilityPolicy, CompatibilityStatus
from app.versioning.parser import compare_versions


def evaluate_desktop(policy: CompatibilityPolicy, current_version: str) -> CompatibilityStatus:
    """Avalia a versao atual do Desktop contra a politica de compatibilidade do servidor.

    Regra: minimum_desktop_version <= current_version <= maximum_desktop_version (quando definido).
    Abaixo do minimo -> UPDATE_REQUIRED. Acima do maximo -> INCOMPATIBLE.
    Entre o minimo e o recomendado (exclusive) -> UPDATE_AVAILABLE. Caso contrario -> COMPATIBLE.
    """
    if compare_versions(current_version, policy.minimum_desktop_version) < 0:
        return CompatibilityStatus.UPDATE_REQUIRED
    if policy.maximum_desktop_version and compare_versions(current_version, policy.maximum_desktop_version) > 0:
        return CompatibilityStatus.INCOMPATIBLE
    if compare_versions(current_version, policy.recommended_desktop_version) < 0:
        return CompatibilityStatus.UPDATE_AVAILABLE
    return CompatibilityStatus.COMPATIBLE


_SERVER_DRIVEN_STATES = {
    CompatibilityStatus.COMPATIBLE.value,
    CompatibilityStatus.UPDATE_AVAILABLE.value,
    CompatibilityStatus.UPDATE_RECOMMENDED.value,
    CompatibilityStatus.UPDATE_REQUIRED.value,
    CompatibilityStatus.INCOMPATIBLE.value,
}


def evaluate_startup_compatibility(
    *,
    maintenance_mode: bool,
    api_contract_version: str,
    minimum_desktop_version: str,
    recommended_desktop_version: str,
    server_version: str,
    database_schema_version: str,
    desktop_version: str,
    supported_api_contract_version: str,
    minimum_api_version: str | None = None,
    server_desktop_state: str | None = None,
) -> CompatibilityStatus:
    """Regra pura de compatibilidade de startup (Fase 03, estendida nas Fases 06/13):
    decide se o Desktop pode operar.

    Ordem de prioridade deterministica (validacao de formato/campos e responsabilidade do
    chamador, que deve tratar ValueError como falha de verificacao/CHECK_FAILED):
      1. maintenance_mode == True -> MAINTENANCE
      2. api_contract_version nao suportado localmente -> INCOMPATIBLE
      3. server_version abaixo de `minimum_api_version` (Fase 06, Secao 6/7) ->
         SERVER_UPDATE_REQUIRED. Verificado ANTES de consultar `server_desktop_state`
         porque um servidor antigo demais nao e uma fonte confiavel para julgar se
         um Desktop mais novo pode operar com ele.
      4. `server_desktop_state` (Fase 13, GET /system/compatibility?desktop_version=...)
         quando presente e reconhecido -> usa DIRETAMENTE (o servidor ja considerou
         enforcement/grace period/authorized_update_version -- Secao 4, "a
         obrigatoriedade pertence ao servidor", o Desktop nao reproduz essa conta).
      5. Sem `server_desktop_state` (servidor anterior a Fase 13, ou desktop_version
         nao enviado) -> delega para evaluate_desktop (minimo/recomendado), igual
         ao comportamento anterior a Fase 13 -- nunca UPDATE_RECOMMENDED aqui,
         porque a comparacao pura nao conhece enforcement.

    database_schema_version e apenas diagnostico nesta fase: nunca influencia o resultado,
    mas ainda precisa ser um valor nao vazio (validado por CompatibilityPolicy).
    server_version nunca substitui api_contract_version na decisao de contrato.
    """
    if maintenance_mode:
        return CompatibilityStatus.MAINTENANCE
    if api_contract_version != supported_api_contract_version:
        return CompatibilityStatus.INCOMPATIBLE
    if minimum_api_version and compare_versions(server_version, minimum_api_version) < 0:
        return CompatibilityStatus.SERVER_UPDATE_REQUIRED
    if server_desktop_state in _SERVER_DRIVEN_STATES:
        return CompatibilityStatus(server_desktop_state)
    policy = CompatibilityPolicy(
        minimum_desktop_version=minimum_desktop_version,
        recommended_desktop_version=recommended_desktop_version,
        server_version=server_version,
        api_contract_version=api_contract_version,
        database_schema_version=database_schema_version,
    )
    return evaluate_desktop(policy, desktop_version)
