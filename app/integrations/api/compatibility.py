from __future__ import annotations

from dataclasses import dataclass

from app.integrations.api.exceptions import ApiCompatibilityError
from app.integrations.api.models import SystemIdentity, SystemVersion
from app.version import APP_VERSION
from app.versioning.parser import compare_versions


REQUIRED_FEATURES = {"auth", "auth_me", "permissions_read", "refresh", "logout"}


@dataclass(frozen=True)
class CompatibilityResult:
    compatible: bool
    status: str
    message: str
    missing_features: list[str]


def validate_api_compatibility(version: SystemVersion, *, desktop_version: str = APP_VERSION) -> CompatibilityResult:
    if version.database_status != "compatible":
        raise ApiCompatibilityError("A revisao do banco da API nao e compativel.")
    if version.minimum_desktop_version and compare_versions(desktop_version, version.minimum_desktop_version) < 0:
        raise ApiCompatibilityError("A versao do aplicativo e antiga para esta API.")
    if version.maximum_desktop_version and compare_versions(desktop_version, version.maximum_desktop_version) > 0:
        raise ApiCompatibilityError("A versao do aplicativo e nova demais para esta API.")
    missing = sorted(REQUIRED_FEATURES - set(version.supported_features))
    if missing:
        raise ApiCompatibilityError(f"A API nao informa recursos obrigatorios: {', '.join(missing)}.")
    return CompatibilityResult(True, "compatible", "API disponivel e compativel.", [])


def validate_company_identity(
    identity: SystemIdentity,
    *,
    expected_company_code: str,
    expected_environment_type: str,
    expected_instance_id: str | None = None,
    desktop_version: str = APP_VERSION,
) -> CompatibilityResult:
    validate_api_compatibility(identity, desktop_version=desktop_version)
    actual_company = identity.company_code.strip().lower()
    expected_company = expected_company_code.strip().lower()
    if actual_company != expected_company:
        raise ApiCompatibilityError(
            "A instalacao encontrada pertence a outra empresa. O acesso foi bloqueado para proteger os dados."
        )
    actual_environment = identity.environment_type.strip().lower()
    expected_environment = expected_environment_type.strip().lower()
    if actual_environment != expected_environment:
        raise ApiCompatibilityError(
            "A instalacao encontrada pertence a outro ambiente. Verifique se voce selecionou Producao, Homologacao ou Dev corretamente."
        )
    expected_instance = (expected_instance_id or "").strip()
    if expected_instance and identity.instance_id.strip() != expected_instance:
        raise ApiCompatibilityError(
            "A instancia operacional mudou desde a ultima configuracao. O acesso foi bloqueado para evitar uso do servidor errado."
        )
    return CompatibilityResult(True, "compatible", "Empresa validada e API operacional compativel.", [])


def compatibility_report(version: SystemVersion, *, desktop_version: str = APP_VERSION) -> CompatibilityResult:
    try:
        return validate_api_compatibility(version, desktop_version=desktop_version)
    except ApiCompatibilityError as exc:
        missing = sorted(REQUIRED_FEATURES - set(version.supported_features))
        return CompatibilityResult(False, exc.category, exc.user_message, missing)
