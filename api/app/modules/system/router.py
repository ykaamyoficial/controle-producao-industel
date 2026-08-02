from __future__ import annotations

from fastapi import APIRouter

from api.app.modules.system import service
from api.app.modules.system.schemas import HealthResponse, IdentityResponse, ReadyResponse, VersionResponse


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


@router.get("/identity", response_model=IdentityResponse)
async def identity():
    return await service.identity()
