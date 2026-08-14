from __future__ import annotations

from app.version import APP_API_CONTRACT_VERSION, APP_VERSION, MINIMUM_API_VERSION
from app.versioning.models import SystemVersionInfo
from app.versioning.parser import parse_version


def get_desktop_version() -> str:
    """Le a versao do Desktop a partir da fonte central (app.version.APP_VERSION).

    Valida o formato SemVer na leitura; levanta ValueError se estiver invalido.
    """
    parse_version(APP_VERSION)
    return APP_VERSION


def get_supported_api_contract_version() -> str:
    """Contrato de API que este build do Desktop suporta (app.version.APP_API_CONTRACT_VERSION)."""
    if not APP_API_CONTRACT_VERSION or not APP_API_CONTRACT_VERSION.strip():
        raise ValueError("APP_API_CONTRACT_VERSION nao pode ser vazio.")
    return APP_API_CONTRACT_VERSION


def get_minimum_api_version() -> str:
    """Menor versao semantica da API que este build do Desktop sabe operar
    (Fase 6 - Compatibilidade de Versoes, Secao 3)."""
    parse_version(MINIMUM_API_VERSION)
    return MINIMUM_API_VERSION


def build_system_version_info(
    *,
    server_version: str,
    api_contract_version: str,
    database_schema_version: str,
    desktop_version: str | None = None,
) -> SystemVersionInfo:
    """Monta o retrato completo das quatro dimensoes de versao do sistema.

    O Desktop conhece a propria versao localmente; server_version, api_contract_version
    e database_schema_version chegam da resposta da API (ver app.integrations.api.models.SystemVersion).
    """
    return SystemVersionInfo(
        desktop_version=desktop_version or get_desktop_version(),
        server_version=server_version,
        api_contract_version=api_contract_version,
        database_schema_version=database_schema_version,
    )
