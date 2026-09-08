"""Servico central de auditoria de atualizacoes (Fase 16).

`record_event` e o UNICO ponto de entrada usado por todo o resto do sistema
(maintenance, channels, updates, deployment, pipeline, compatibility) --
sempre sincrono, sempre grava no spool local primeiro (Secao 18/19), nunca
levanta excecao para quem chama. A drenagem para o Postgres e assincrona e
roda perto de tempo real (startup, timer periodico, antes de toda consulta
administrativa) -- ver api.app.main e api.app.modules.update_audit.router.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.audit.db_models import UpdateAuditEventRow
from api.app.audit.models import (
    ActorType,
    AuditEventType,
    Component,
    EventResult,
    EventSeverity,
    InstallationUpdateStatus,
    UpdateAuditEvent,
)
from api.app.audit.paths import ensure_spool_dirs, failed_dir, pending_dir, processed_dir
from api.app.audit.sanitizer import sanitize_audit_metadata
from api.app.audit.spool import AuditSpool
from api.app.channels.db_models import ClientInstallation
from api.app.database.session import get_sessionmaker

log = logging.getLogger("api.audit")

_INSTALL_RESULT_EVENT_TYPES = (
    AuditEventType.UPDATE_INSTALL_SUCCEEDED.value,
    AuditEventType.UPDATE_INSTALL_FAILED.value,
    AuditEventType.PILOT_CLIENT_UPDATE_REPORTED.value,
)


def build_default_spool() -> AuditSpool:
    ensure_spool_dirs()
    return AuditSpool(pending_dir=pending_dir(), processed_dir=processed_dir(), failed_dir=failed_dir())


def record_event(
    *,
    event_type: AuditEventType,
    component: Component,
    result: EventResult,
    message: str,
    actor_type: ActorType = ActorType.SYSTEM,
    actor_id: str | None = None,
    severity: EventSeverity = EventSeverity.INFO,
    correlation_id: str | None = None,
    release_id: str | None = None,
    deployment_id: str | None = None,
    maintenance_id: str | None = None,
    installation_id: str | None = None,
    version: str | None = None,
    channel: str | None = None,
    metadata: dict[str, Any] | None = None,
    spool: AuditSpool | None = None,
) -> UpdateAuditEvent:
    """Registra um fato auditavel (Secao 4/7). Nunca altera o resultado da
    operacao que o disparou -- uma falha aqui (ex.: disco cheio) so vira log
    tecnico CRITICAL, nunca uma excecao propagada para quem chama."""
    event = UpdateAuditEvent(
        event_type=event_type, severity=severity, actor_type=actor_type, actor_id=actor_id,
        component=component, result=result, message=message,
        correlation_id=correlation_id, release_id=release_id, deployment_id=deployment_id,
        maintenance_id=maintenance_id, installation_id=installation_id, version=version, channel=channel,
        metadata=sanitize_audit_metadata(metadata),
    )
    try:
        (spool or build_default_spool()).write_pending(event)
    except Exception:
        log.critical(
            "AUDIT_EVENT_SPOOL_WRITE_FAILED | event_type=%s | event_id=%s", event_type.value, event.event_id, exc_info=True,
        )
    return event


def _row_values(event: UpdateAuditEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "occurred_at": event.occurred_at,
        "severity": event.severity.value,
        "actor_type": event.actor_type.value,
        "actor_id": event.actor_id,
        "component": event.component.value,
        "result": event.result.value,
        "correlation_id": event.correlation_id,
        "release_id": event.release_id,
        "deployment_id": event.deployment_id,
        "maintenance_id": event.maintenance_id,
        "installation_id": event.installation_id,
        "version": event.version,
        "channel": event.channel,
        "message": event.message,
        "metadata": event.metadata,
    }


async def drain_spool_to_database(*, spool: AuditSpool | None = None, sessionmaker=None) -> int:
    """Drena pending/ para update_audit_events, idempotente por event_id
    (INSERT ... ON CONFLICT DO NOTHING -- Secao 19). Uma falha ao inserir UM
    evento nunca apaga o arquivo pendente nem interrompe a drenagem dos
    demais. Devolve quantos eventos foram confirmados nesta chamada."""
    spool = spool or build_default_spool()
    sessionmaker = sessionmaker or get_sessionmaker()
    if sessionmaker is None:
        return 0

    pending = spool.list_pending()
    if not pending:
        return 0

    drained = 0
    async with sessionmaker() as session:
        for event in pending:
            try:
                stmt = (
                    pg_insert(UpdateAuditEventRow.__table__)
                    .values(**_row_values(event))
                    .on_conflict_do_nothing(index_elements=["event_id"])
                )
                await session.execute(stmt)
                await session.commit()
            except Exception:
                await session.rollback()
                log.error("AUDIT_EVENT_DRAIN_FAILED | event_id=%s -- permanece pendente", event.event_id, exc_info=True)
                continue
            spool.mark_processed(event.event_id)
            drained += 1
    return drained


@dataclass(frozen=True)
class EventPage:
    items: list[UpdateAuditEventRow]
    total: int


def _apply_filters(
    stmt: Select,
    *,
    event_type: str | None,
    result: str | None,
    channel: str | None,
    version: str | None,
    installation_id: str | None,
    correlation_id: str | None,
    release_id: str | None,
    deployment_id: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> Select:
    if event_type:
        stmt = stmt.where(UpdateAuditEventRow.event_type == event_type)
    if result:
        stmt = stmt.where(UpdateAuditEventRow.result == result)
    if channel:
        stmt = stmt.where(UpdateAuditEventRow.channel == channel)
    if version:
        stmt = stmt.where(UpdateAuditEventRow.version == version)
    if installation_id:
        stmt = stmt.where(UpdateAuditEventRow.installation_id == installation_id)
    if correlation_id:
        stmt = stmt.where(UpdateAuditEventRow.correlation_id == correlation_id)
    if release_id:
        stmt = stmt.where(UpdateAuditEventRow.release_id == release_id)
    if deployment_id:
        stmt = stmt.where(UpdateAuditEventRow.deployment_id == deployment_id)
    if date_from is not None:
        stmt = stmt.where(UpdateAuditEventRow.occurred_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(UpdateAuditEventRow.occurred_at <= date_to)
    return stmt


_MAX_PAGE_SIZE = 200


async def list_events(
    session: AsyncSession,
    *,
    event_type: str | None = None,
    result: str | None = None,
    channel: str | None = None,
    version: str | None = None,
    installation_id: str | None = None,
    correlation_id: str | None = None,
    release_id: str | None = None,
    deployment_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> EventPage:
    """Secao 25: paginado, nunca sem limite (Secao 25: "nao permitir filtros
    que gerem queries sem limite")."""
    limit = max(1, min(limit, _MAX_PAGE_SIZE))
    offset = max(0, offset)

    base = _apply_filters(
        select(UpdateAuditEventRow),
        event_type=event_type, result=result, channel=channel, version=version,
        installation_id=installation_id, correlation_id=correlation_id,
        release_id=release_id, deployment_id=deployment_id, date_from=date_from, date_to=date_to,
    )
    total = int((await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
    rows = (
        await session.execute(base.order_by(UpdateAuditEventRow.occurred_at.desc()).limit(limit).offset(offset))
    ).scalars().all()
    return EventPage(items=list(rows), total=total)


async def get_event(session: AsyncSession, event_id: str) -> UpdateAuditEventRow | None:
    result = await session.execute(select(UpdateAuditEventRow).where(UpdateAuditEventRow.event_id == event_id))
    return result.scalar_one_or_none()


async def build_timeline(session: AsyncSession, correlation_id: str) -> list[UpdateAuditEventRow]:
    """Secao 26: ordenada server-side, cronologica (mais antigo primeiro)."""
    result = await session.execute(
        select(UpdateAuditEventRow)
        .where(UpdateAuditEventRow.correlation_id == correlation_id)
        .order_by(UpdateAuditEventRow.occurred_at.asc())
    )
    return list(result.scalars().all())


async def list_events_for_release(session: AsyncSession, version: str) -> list[UpdateAuditEventRow]:
    result = await session.execute(
        select(UpdateAuditEventRow)
        .where(UpdateAuditEventRow.version == version)
        .order_by(UpdateAuditEventRow.occurred_at.asc())
    )
    return list(result.scalars().all())


async def get_installation_status(session: AsyncSession, installation_id: str) -> InstallationUpdateStatus | None:
    """Secao 28 -- snapshot derivado do cadastro de instalacoes (Fase 15) +
    do evento mais recente relevante; NUNCA a fonte oficial (essa continua
    sendo os proprios eventos)."""
    installation_result = await session.execute(
        select(ClientInstallation).where(ClientInstallation.installation_id == installation_id)
    )
    installation = installation_result.scalar_one_or_none()
    if installation is None:
        return None

    last_update_result = await session.execute(
        select(UpdateAuditEventRow)
        .where(UpdateAuditEventRow.installation_id == installation_id)
        .where(UpdateAuditEventRow.event_type.in_(_INSTALL_RESULT_EVENT_TYPES))
        .order_by(UpdateAuditEventRow.occurred_at.desc())
        .limit(1)
    )
    last_update_row = last_update_result.scalar_one_or_none()

    last_compat_result = await session.execute(
        select(UpdateAuditEventRow)
        .where(UpdateAuditEventRow.installation_id == installation_id)
        .where(UpdateAuditEventRow.event_type == AuditEventType.DESKTOP_COMPATIBILITY_CHECKED.value)
        .order_by(UpdateAuditEventRow.occurred_at.desc())
        .limit(1)
    )
    last_compat_row = last_compat_result.scalar_one_or_none()
    compatibility_state = None
    if last_compat_row is not None and isinstance(last_compat_row.event_metadata, dict):
        compatibility_state = last_compat_row.event_metadata.get("desktop_state")

    return InstallationUpdateStatus(
        installation_id=installation.installation_id,
        machine_name=installation.machine_name,
        channel=installation.channel,
        current_version=installation.current_desktop_version,
        last_seen_at=installation.last_seen_at,
        last_update_version=last_update_row.version if last_update_row else None,
        last_update_result=last_update_row.result if last_update_row else None,
        last_update_at=last_update_row.occurred_at if last_update_row else None,
        compatibility_state=compatibility_state,
    )
