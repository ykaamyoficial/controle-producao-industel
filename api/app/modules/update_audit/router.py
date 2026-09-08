from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.audit import service as audit_service
from api.app.core import error_codes
from api.app.core.exceptions import ApiError
from api.app.database.session import get_db_session
from api.app.modules.auth.dependencies import require_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import AUDIT_VIEW
from api.app.modules.update_audit.schemas import InstallationUpdateStatusOut, UpdateAuditEventList, UpdateAuditEventOut

log = logging.getLogger("api.update_audit")

router = APIRouter(prefix="/admin/update-audit", tags=["update-audit"])


async def _best_effort_drain() -> None:
    """Consultar auditoria nunca falha por causa da drenagem (Secao 25: os
    endpoints sao read-only) -- so tenta deixar os dados o mais frescos
    possivel antes de responder (Secao 18: drenagem perto de tempo real)."""
    try:
        await audit_service.drain_spool_to_database()
    except Exception:
        log.warning("AUDIT_PRE_QUERY_DRAIN_FAILED", exc_info=True)


def _event_out(row) -> UpdateAuditEventOut:
    return UpdateAuditEventOut(
        event_id=row.event_id,
        event_type=row.event_type,
        occurred_at=row.occurred_at.isoformat(),
        severity=row.severity,
        actor_type=row.actor_type,
        actor_id=row.actor_id,
        component=row.component,
        result=row.result,
        correlation_id=row.correlation_id,
        release_id=row.release_id,
        deployment_id=row.deployment_id,
        maintenance_id=row.maintenance_id,
        installation_id=row.installation_id,
        version=row.version,
        channel=row.channel,
        message=row.message,
        metadata=row.event_metadata or {},
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


@router.get("/events", response_model=UpdateAuditEventList, summary="Lista eventos de auditoria de atualizacoes (admin, somente leitura)")
async def list_events(
    event_type: str | None = Query(default=None, max_length=64),
    result: str | None = Query(default=None, max_length=32),
    channel: str | None = Query(default=None, max_length=20),
    version: str | None = Query(default=None, max_length=32),
    installation_id: str | None = Query(default=None, max_length=36),
    correlation_id: str | None = Query(default=None, max_length=120),
    release_id: str | None = Query(default=None, max_length=64),
    deployment_id: str | None = Query(default=None, max_length=120),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(AUDIT_VIEW)),
) -> UpdateAuditEventList:
    await _best_effort_drain()
    page = await audit_service.list_events(
        session, event_type=event_type, result=result, channel=channel, version=version,
        installation_id=installation_id, correlation_id=correlation_id, release_id=release_id,
        deployment_id=deployment_id, date_from=date_from, date_to=date_to, limit=limit, offset=offset,
    )
    return UpdateAuditEventList(items=[_event_out(row) for row in page.items], total=page.total, limit=limit, offset=offset)


@router.get("/events/{event_id}", response_model=UpdateAuditEventOut, summary="Detalhe de um evento de auditoria (admin, somente leitura)")
async def get_event(
    event_id: str,
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(AUDIT_VIEW)),
) -> UpdateAuditEventOut:
    await _best_effort_drain()
    row = await audit_service.get_event(session, event_id)
    if row is None:
        raise ApiError(error_codes.NOT_FOUND, "Evento de auditoria nao encontrado.", status_code=404)
    return _event_out(row)


@router.get("/timeline/{correlation_id}", response_model=UpdateAuditEventList, summary="Linha do tempo de um fluxo (admin, somente leitura)")
async def get_timeline(
    correlation_id: str,
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(AUDIT_VIEW)),
) -> UpdateAuditEventList:
    await _best_effort_drain()
    rows = await audit_service.build_timeline(session, correlation_id)
    return UpdateAuditEventList(items=[_event_out(row) for row in rows], total=len(rows), limit=len(rows), offset=0)


@router.get("/installations/{installation_id}", response_model=InstallationUpdateStatusOut, summary="Estado atual derivado de uma instalacao (admin, somente leitura)")
async def get_installation_status(
    installation_id: str,
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(AUDIT_VIEW)),
) -> InstallationUpdateStatusOut:
    await _best_effort_drain()
    status = await audit_service.get_installation_status(session, installation_id)
    if status is None:
        raise ApiError(error_codes.NOT_FOUND, "Instalacao nao encontrada.", status_code=404)
    return InstallationUpdateStatusOut(**status.to_dict())


@router.get("/releases/{version}", response_model=UpdateAuditEventList, summary="Eventos de uma release (admin, somente leitura)")
async def get_release_events(
    version: str,
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(AUDIT_VIEW)),
) -> UpdateAuditEventList:
    await _best_effort_drain()
    rows = await audit_service.list_events_for_release(session, version)
    return UpdateAuditEventList(items=[_event_out(row) for row in rows], total=len(rows), limit=len(rows), offset=0)
