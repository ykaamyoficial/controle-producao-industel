from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core import error_codes
from api.app.core.config import get_settings
from api.app.core.exceptions import ApiError
from api.app.database.session import get_db_session
from api.app.modules.provisioning.schemas import InitialAdminCreate, InitialAdminResponse
from api.app.modules.provisioning.service import provision_initial_admin


router = APIRouter(prefix="/provisioning", tags=["provisioning"])


@router.post("/initial-admin", response_model=InitialAdminResponse, status_code=201)
async def create_initial_admin(
    payload: InitialAdminCreate,
    request: Request,
    x_provisioning_secret: str | None = Header(default=None, alias="X-Provisioning-Secret"),
    session: AsyncSession = Depends(get_db_session),
) -> InitialAdminResponse:
    settings = get_settings()
    if not settings.provisioning_secret or x_provisioning_secret != settings.provisioning_secret:
        raise ApiError(error_codes.PERMISSION_DENIED, "Provisionamento operacional nao autorizado.", status_code=403)
    return await provision_initial_admin(session, payload, getattr(request.state, "request_id", None))
