from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from api.app.core.config import (
    API_CONTRACT_VERSION,
    API_VERSION,
    EXPECTED_DATABASE_REVISION,
    MAXIMUM_DESKTOP_VERSION,
    MINIMUM_DESKTOP_VERSION,
    RECOMMENDED_DESKTOP_VERSION,
)

# Nota de arquitetura (ver docs/versioning.md): Desktop (app/versioning) e API (este modulo)
# sao empacotados e distribuidos separadamente (PyInstaller x Docker), portanto cada lado
# mantem sua propria implementacao pequena e auto-contida de parsing/comparacao SemVer.
# O contrato entre os dois e o JSON trafegado pela API, nao codigo Python compartilhado.

SEMVER_PATTERN = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int

    def __post_init__(self) -> None:
        for name, value in (("major", self.major), ("minor", self.minor), ("patch", self.patch)):
            if value < 0:
                raise ValueError(f"Componente '{name}' do SemVer nao pode ser negativo: {value}")

    def as_tuple(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


class CompatibilityStatus(str, Enum):
    COMPATIBLE = "COMPATIBLE"
    UPDATE_AVAILABLE = "UPDATE_AVAILABLE"
    UPDATE_RECOMMENDED = "UPDATE_RECOMMENDED"
    UPDATE_REQUIRED = "UPDATE_REQUIRED"
    INCOMPATIBLE = "INCOMPATIBLE"


def parse_version(value: str) -> SemVer:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Versao nao pode ser vazia.")
    candidate = value.strip()
    match = SEMVER_PATTERN.match(candidate)
    if not match:
        raise ValueError(f"Versao invalida (esperado MAJOR.MINOR.PATCH): '{value}'")
    major, minor, patch = (int(part) for part in match.groups())
    return SemVer(major, minor, patch)


def compare_versions(a: str | SemVer, b: str | SemVer) -> int:
    left = a if isinstance(a, SemVer) else parse_version(a)
    right = b if isinstance(b, SemVer) else parse_version(b)
    if left.as_tuple() < right.as_tuple():
        return -1
    if left.as_tuple() > right.as_tuple():
        return 1
    return 0


def is_version_at_least(current: str | SemVer, minimum: str | SemVer) -> bool:
    return compare_versions(current, minimum) >= 0


def is_version_newer(candidate: str | SemVer, current: str | SemVer) -> bool:
    return compare_versions(candidate, current) > 0


def get_server_version() -> str:
    parse_version(API_VERSION)
    return API_VERSION


def get_api_contract_version() -> str:
    if not API_CONTRACT_VERSION or not API_CONTRACT_VERSION.strip():
        raise ValueError("API_CONTRACT_VERSION nao pode ser vazio.")
    return API_CONTRACT_VERSION


def get_database_schema_version() -> str:
    """Retorna a revisao Alembic esperada (fonte de verdade estatica).

    Para a revisao efetivamente aplicada no banco, use api.app.database.health.database_check(),
    que le a tabela alembic_version sem executar migrations.
    """
    if not EXPECTED_DATABASE_REVISION or not EXPECTED_DATABASE_REVISION.strip():
        raise ValueError("EXPECTED_DATABASE_REVISION nao pode ser vazio.")
    return EXPECTED_DATABASE_REVISION


@dataclass(frozen=True)
class CompatibilityPolicy:
    """Estrutura preparada para o endpoint /system/compatibility da Fase 02."""

    minimum_desktop_version: str
    recommended_desktop_version: str
    server_version: str
    api_contract_version: str
    database_schema_version: str
    maximum_desktop_version: str | None = None

    def __post_init__(self) -> None:
        parse_version(self.minimum_desktop_version)
        parse_version(self.recommended_desktop_version)
        parse_version(self.server_version)
        if not self.api_contract_version.strip():
            raise ValueError("api_contract_version nao pode ser vazio.")
        if not self.database_schema_version.strip():
            raise ValueError("database_schema_version nao pode ser vazio.")
        if self.maximum_desktop_version is not None:
            parse_version(self.maximum_desktop_version)
        if compare_versions(self.recommended_desktop_version, self.minimum_desktop_version) < 0:
            raise ValueError("recommended_desktop_version nao pode ser menor que minimum_desktop_version.")


def get_compatibility_policy() -> CompatibilityPolicy:
    return CompatibilityPolicy(
        minimum_desktop_version=MINIMUM_DESKTOP_VERSION,
        recommended_desktop_version=RECOMMENDED_DESKTOP_VERSION,
        server_version=get_server_version(),
        api_contract_version=get_api_contract_version(),
        database_schema_version=get_database_schema_version(),
        maximum_desktop_version=MAXIMUM_DESKTOP_VERSION,
    )


def evaluate_desktop(policy: CompatibilityPolicy, current_version: str) -> CompatibilityStatus:
    if compare_versions(current_version, policy.minimum_desktop_version) < 0:
        return CompatibilityStatus.UPDATE_REQUIRED
    if policy.maximum_desktop_version and compare_versions(current_version, policy.maximum_desktop_version) > 0:
        return CompatibilityStatus.INCOMPATIBLE
    if compare_versions(current_version, policy.recommended_desktop_version) < 0:
        return CompatibilityStatus.UPDATE_AVAILABLE
    return CompatibilityStatus.COMPATIBLE


class EnforcementMode(str, Enum):
    """Grau de obrigatoriedade de uma release, definido pelo administrador
    (Fase 13, Secao 7) -- nunca hardcoded para uma versao especifica no
    Desktop. Camada independente de CompatibilityStatus: o mesmo par
    minimo/recomendado pode produzir estados diferentes dependendo do
    enforcement configurado (ver evaluate_desktop_with_enforcement)."""

    NONE = "NONE"
    OPTIONAL = "OPTIONAL"
    RECOMMENDED = "RECOMMENDED"
    REQUIRED = "REQUIRED"
    BLOCKED = "BLOCKED"


def evaluate_desktop_with_enforcement(
    policy: CompatibilityPolicy,
    current_version: str,
    *,
    enforcement: EnforcementMode,
    authorized_update_version: str | None,
    grace_until: datetime | None,
    now: datetime,
) -> CompatibilityStatus:
    """Fase 13, Secoes 7-8-12: combina a comparacao pura de versao
    (evaluate_desktop) com o enforcement administrativo e o grace period.

    `authorized_update_version` precisa ja ter sido validado como uma
    release AUTHORIZED da Fase 12 por quem chama (ver
    api.app.updates.policy.resolve_effective_policy) -- esta funcao apenas
    faz a matematica de versao, nunca consulta o repositorio de releases.

    Regras, em ordem:
    1. Acima do maximo ou enforcement=BLOCKED -> INCOMPATIBLE (nunca oferece
       continuidade -- BLOCKED sempre vence, mesmo que a versao atenda o
       minimo/recomendado).
    2. Abaixo do minimo -> UPDATE_REQUIRED (piso rigido, enforcement nunca
       amacia isso -- so BLOCKED consegue ser mais severo).
    3. Enforcement=REQUIRED com a versao atual desatualizada em relacao a
       authorized_update_version (ou, na ausencia dela, recommended) ->
       UPDATE_REQUIRED, exceto durante o grace period (antes de grace_until
       -> UPDATE_RECOMMENDED, aviso mais forte mas ainda permite operar).
    4. Abaixo do recomendado -> UPDATE_RECOMMENDED quando enforcement=RECOMMENDED,
       senao UPDATE_AVAILABLE.
    5. Caso contrario -> COMPATIBLE.
    """
    base = evaluate_desktop(policy, current_version)
    if base == CompatibilityStatus.INCOMPATIBLE or enforcement == EnforcementMode.BLOCKED:
        return CompatibilityStatus.INCOMPATIBLE
    if base == CompatibilityStatus.UPDATE_REQUIRED:
        return CompatibilityStatus.UPDATE_REQUIRED

    target_version = authorized_update_version or policy.recommended_desktop_version
    is_outdated_vs_target = compare_versions(current_version, target_version) < 0

    if enforcement == EnforcementMode.REQUIRED and is_outdated_vs_target:
        if grace_until is not None and now < grace_until:
            return CompatibilityStatus.UPDATE_RECOMMENDED
        return CompatibilityStatus.UPDATE_REQUIRED

    if base == CompatibilityStatus.UPDATE_AVAILABLE:
        if enforcement == EnforcementMode.RECOMMENDED:
            return CompatibilityStatus.UPDATE_RECOMMENDED
        return CompatibilityStatus.UPDATE_AVAILABLE

    return CompatibilityStatus.COMPATIBLE
