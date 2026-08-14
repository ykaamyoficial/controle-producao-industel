from __future__ import annotations

from fastapi import APIRouter, Query

from api.app.modules.system import service
from api.app.modules.system.schemas import HealthResponse, IdentityResponse, MaintenanceStateResponse, ReadyResponse, SystemCompatibilityResponse, VersionResponse


router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health():
    return service.health()


@router.get("/ready", response_model=ReadyResponse)
async def ready():
    return await service.readiness()


@router.get("/version", response_model=VersionResponse)
async def version():
    return await service.version()


@router.get(
    "/compatibility",
    response_model=SystemCompatibilityResponse,
    summary="Politica oficial de compatibilidade Desktop/API",
    description=(
        "Publica, de forma somente leitura, a versao efetiva do servidor, o contrato da API, "
        "a revisao real do banco e a politica de versao minima/recomendada do Desktop. "
        "Nao dispara download, instalacao ou qualquer acao no cliente. "
        "Quando `desktop_version` e informado (Fase 13), tambem calcula e retorna o "
        "desktop_state server-side (COMPATIBLE/UPDATE_AVAILABLE/UPDATE_RECOMMENDED/"
        "UPDATE_REQUIRED/INCOMPATIBLE), considerando enforcement e grace period."
    ),
)
async def compatibility(
    desktop_version: str | None = Query(default=None),
    installation_id: str | None = Query(default=None, max_length=36),
    machine_name: str | None = Query(default=None, max_length=255),
    os_version: str | None = Query(default=None, max_length=255),
):
    return await service.compatibility(
        desktop_version=desktop_version, installation_id=installation_id,
        machine_name=machine_name, os_version=os_version,
    )


@router.get("/identity", response_model=IdentityResponse)
async def identity():
    return await service.identity()


@router.get(
    "/maintenance",
    response_model=MaintenanceStateResponse,
    summary="Estado corrente do Maintenance Mode (Fase 14)",
    description=(
        "Publica o estado de manutencao persistido fora do PostgreSQL operacional. "
        "Permanece acessivel mesmo durante ACTIVE/RECOVERY -- nunca passa pelo "
        "bloqueio centralizado de operacoes de negocio."
    ),
)
async def maintenance():
    return service.maintenance()
