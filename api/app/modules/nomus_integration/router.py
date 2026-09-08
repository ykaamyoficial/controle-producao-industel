from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.database.session import get_db_session
from api.app.modules.auth.dependencies import require_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import SYSTEM_ADMIN
from api.app.modules.nomus_integration import service
from api.app.modules.nomus_integration.schemas import (
    NomusApiKeyIn,
    NomusConnectionTestOut,
    NomusSettingsOut,
    NomusSettingsUpdate,
)

router = APIRouter(prefix="/nomus", tags=["nomus_integration"])


@router.get("/settings", response_model=NomusSettingsOut)
async def get_nomus_settings(
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(SYSTEM_ADMIN)),
):
    return await service.load_settings(session)


@router.put("/settings", response_model=NomusSettingsOut)
async def update_nomus_settings(
    payload: NomusSettingsUpdate,
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(SYSTEM_ADMIN)),
):
    return await service.save_settings(session, enabled=payload.enabled, base_url=payload.base_url)


@router.put("/settings/api-key", response_model=NomusSettingsOut)
async def save_nomus_api_key(
    payload: NomusApiKeyIn,
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(SYSTEM_ADMIN)),
):
    return await service.save_api_key(session, payload.api_key)


@router.delete("/settings/api-key", response_model=NomusSettingsOut)
async def delete_nomus_api_key(
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(SYSTEM_ADMIN)),
):
    return await service.delete_api_key(session)


@router.post("/settings/test-connection", response_model=NomusConnectionTestOut)
async def test_nomus_connection(
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(SYSTEM_ADMIN)),
):
    return await service.test_connection(session)
