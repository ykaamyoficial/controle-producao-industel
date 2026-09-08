from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

SEMVER_PATTERN = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _require_semver_format(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not SEMVER_PATTERN.match(value.strip()):
        raise ValueError(f"'{field_name}' deve seguir o formato MAJOR.MINOR.PATCH: '{value}'")


def _require_non_empty(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{field_name}' nao pode ser vazio.")


@dataclass(frozen=True)
class SemVer:
    """Representacao tipada de uma versao MAJOR.MINOR.PATCH."""

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
    """Estados possiveis ao avaliar o Desktop contra a politica de compatibilidade do servidor.

    COMPATIBLE/UPDATE_AVAILABLE/UPDATE_RECOMMENDED/UPDATE_REQUIRED/INCOMPATIBLE sao o
    resultado da comparacao de versao + enforcement server-side (Fase 13,
    api.app.updates.policy.evaluate_for_desktop -- espelha
    api.app.core.versioning.CompatibilityStatus). CHECKING/MAINTENANCE/CHECK_FAILED
    sao estados de transporte/orquestracao acrescentados na Fase 03 pelo
    coordenador de startup (ver app.services.compatibility_check) e nunca sao
    retornados pelo servidor.
    """

    CHECKING = "CHECKING"
    COMPATIBLE = "COMPATIBLE"
    UPDATE_AVAILABLE = "UPDATE_AVAILABLE"
    UPDATE_RECOMMENDED = "UPDATE_RECOMMENDED"
    UPDATE_REQUIRED = "UPDATE_REQUIRED"
    INCOMPATIBLE = "INCOMPATIBLE"
    MAINTENANCE = "MAINTENANCE"
    CHECK_FAILED = "CHECK_FAILED"
    # Fase 6 - Compatibilidade de Versoes (Secao 7): decidido inteiramente pelo
    # Desktop (server_version < MINIMUM_API_VERSION deste build) -- nunca
    # retornado pelo servidor, pelo mesmo motivo que CHECK_FAILED/MAINTENANCE
    # nao sao: um servidor antigo nao sabe que esta desatualizado.
    SERVER_UPDATE_REQUIRED = "SERVER_UPDATE_REQUIRED"


@dataclass(frozen=True)
class SystemVersionInfo:
    """Fonte unica das quatro dimensoes de versao do sistema."""

    desktop_version: str
    server_version: str
    api_contract_version: str
    database_schema_version: str

    def __post_init__(self) -> None:
        _require_semver_format("desktop_version", self.desktop_version)
        _require_semver_format("server_version", self.server_version)
        _require_non_empty("api_contract_version", self.api_contract_version)
        _require_non_empty("database_schema_version", self.database_schema_version)

    def to_dict(self) -> dict[str, str]:
        return {
            "desktop_version": self.desktop_version,
            "server_version": self.server_version,
            "api_contract_version": self.api_contract_version,
            "database_schema_version": self.database_schema_version,
        }


@dataclass(frozen=True)
class CompatibilityPolicy:
    """Politica de compatibilidade publicada pelo servidor para o Desktop se avaliar."""

    minimum_desktop_version: str
    recommended_desktop_version: str
    server_version: str
    api_contract_version: str
    database_schema_version: str
    maximum_desktop_version: str | None = None

    def __post_init__(self) -> None:
        _require_semver_format("minimum_desktop_version", self.minimum_desktop_version)
        _require_semver_format("recommended_desktop_version", self.recommended_desktop_version)
        _require_semver_format("server_version", self.server_version)
        _require_non_empty("api_contract_version", self.api_contract_version)
        _require_non_empty("database_schema_version", self.database_schema_version)
        if self.maximum_desktop_version is not None:
            _require_semver_format("maximum_desktop_version", self.maximum_desktop_version)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "minimum_desktop_version": self.minimum_desktop_version,
            "recommended_desktop_version": self.recommended_desktop_version,
            "server_version": self.server_version,
            "api_contract_version": self.api_contract_version,
            "database_schema_version": self.database_schema_version,
            "maximum_desktop_version": self.maximum_desktop_version,
        }
