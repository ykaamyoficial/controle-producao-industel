"""Cadastro de instalacoes do Desktop e relatorios de piloto (Fase 15,
Secao 6/7/18) -- unica fonte de verdade server-side do canal de cada
instalacao. Ao contrario do estado de promocao (arquivo, ver service.py),
isto e um cadastro administrativo comum: nao precisa sobreviver a uma
indisponibilidade do Postgres (o cliente simplesmente cai no fallback
PRODUCTION -- ver resolve_channel -- ate o banco voltar).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.audit import service as audit_service
from api.app.audit.models import ActorType, AuditEventType, Component, EventResult
from api.app.channels.db_models import ClientInstallation, PilotClientReport
from api.app.channels.models import Channel, DEFAULT_CHANNEL, ReportSignal


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _get(session: AsyncSession, installation_id: str) -> ClientInstallation | None:
    result = await session.execute(select(ClientInstallation).where(ClientInstallation.installation_id == installation_id))
    return result.scalar_one_or_none()


async def resolve_channel(session: AsyncSession, installation_id: str | None) -> Channel:
    """Secao 8: fallback seguro -- sem installation_id, ou instalacao
    desconhecida/sem atribuicao valida, cai SEMPRE em PRODUCTION."""
    if not installation_id:
        return DEFAULT_CHANNEL
    row = await _get(session, installation_id)
    if row is None:
        return DEFAULT_CHANNEL
    try:
        return Channel(row.channel)
    except ValueError:
        return DEFAULT_CHANNEL


async def upsert_heartbeat(
    session: AsyncSession,
    *,
    installation_id: str,
    machine_name: str | None,
    os_version: str | None,
    current_desktop_version: str | None,
) -> ClientInstallation:
    """Secao 19: atualiza current_desktop_version/last_seen_at a cada
    consulta normal de compatibilidade -- cria o cadastro automaticamente
    (sempre em PRODUCTION, Secao 8) na primeira vez que uma instalacao e
    vista; um administrador precisa agir explicitamente para move-la."""
    row = await _get(session, installation_id)
    now = _now()
    if row is None:
        row = ClientInstallation(
            installation_id=installation_id, machine_name=machine_name, os_version=os_version,
            channel=DEFAULT_CHANNEL.value, current_desktop_version=current_desktop_version, last_seen_at=now,
        )
        session.add(row)
    else:
        row.last_seen_at = now
        if current_desktop_version:
            row.current_desktop_version = current_desktop_version
        if machine_name:
            row.machine_name = machine_name
        if os_version:
            row.os_version = os_version
    await session.commit()
    await session.refresh(row)
    return row


async def list_installations(session: AsyncSession, *, channel: Channel | None = None) -> list[ClientInstallation]:
    stmt = select(ClientInstallation).order_by(ClientInstallation.installation_id)
    if channel is not None:
        stmt = stmt.where(ClientInstallation.channel == channel.value)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def assign_channel(session: AsyncSession, installation_id: str, *, channel: Channel, actor: str) -> ClientInstallation:
    row = await _get(session, installation_id)
    now = _now()
    if row is None:
        row = ClientInstallation(
            installation_id=installation_id, channel=channel.value,
            assigned_by=actor, assigned_at=now,
        )
        session.add(row)
    else:
        row.channel = channel.value
        row.assigned_by = actor
        row.assigned_at = now
    await session.commit()
    await session.refresh(row)
    audit_service.record_event(
        event_type=AuditEventType.CLIENT_CHANNEL_ASSIGNED, component=Component.RELEASE_CHANNEL,
        result=EventResult.SUCCEEDED, actor_type=ActorType.ADMIN_API, actor_id=actor,
        installation_id=installation_id, channel=channel.value, correlation_id=installation_id,
        message=f"Instalacao {installation_id} atribuida ao canal {channel.value}.",
    )
    return row


async def remove_channel_assignment(session: AsyncSession, installation_id: str, *, actor: str) -> ClientInstallation | None:
    """Remove a atribuicao explicita -- a instalacao volta ao fallback
    PRODUCTION (Secao 8), nunca fica "sem canal"."""
    row = await _get(session, installation_id)
    if row is None:
        return None
    row.channel = DEFAULT_CHANNEL.value
    row.assigned_by = actor
    row.assigned_at = _now()
    await session.commit()
    await session.refresh(row)
    audit_service.record_event(
        event_type=AuditEventType.CLIENT_CHANNEL_REMOVED, component=Component.RELEASE_CHANNEL,
        result=EventResult.SUCCEEDED, actor_type=ActorType.ADMIN_API, actor_id=actor,
        installation_id=installation_id, channel=DEFAULT_CHANNEL.value, correlation_id=installation_id,
        message=f"Atribuicao de canal removida para {installation_id} (volta a {DEFAULT_CHANNEL.value}).",
    )
    return row


async def count_pilot_clients(session: AsyncSession) -> int:
    rows = await list_installations(session, channel=Channel.PILOT)
    return len(rows)


async def submit_pilot_report(
    session: AsyncSession,
    *,
    installation_id: str,
    release_version: str,
    update_result: str,
    app_start_result: str,
    compatibility_result: str,
    error_code: str | None,
) -> PilotClientReport:
    report = PilotClientReport(
        installation_id=installation_id, release_version=release_version,
        update_result=update_result, app_start_result=app_start_result,
        compatibility_result=compatibility_result, error_code=error_code,
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    audit_service.record_event(
        event_type=AuditEventType.PILOT_CLIENT_UPDATE_REPORTED, component=Component.RELEASE_CHANNEL,
        result=EventResult.FAILED if update_result == "FAILED" else EventResult.SUCCEEDED,
        actor_type=ActorType.DESKTOP, actor_id=installation_id,
        installation_id=installation_id, version=release_version, release_id=release_version,
        correlation_id=release_version,
        message=f"Relatorio de piloto: update={update_result} start={app_start_result} compat={compatibility_result}.",
        metadata={"update_result": update_result, "app_start_result": app_start_result, "compatibility_result": compatibility_result, "error_code": error_code},
    )
    return report


async def list_reports_for_version(session: AsyncSession, release_version: str) -> list[PilotClientReport]:
    result = await session.execute(
        select(PilotClientReport).where(PilotClientReport.release_version == release_version).order_by(PilotClientReport.reported_at)
    )
    return list(result.scalars().all())


async def report_signals_for_version(session: AsyncSession, release_version: str) -> list[ReportSignal]:
    reports = await list_reports_for_version(session, release_version)
    return [
        ReportSignal(
            installation_id=report.installation_id, release_version=report.release_version,
            update_result=report.update_result, app_start_result=report.app_start_result,
            compatibility_result=report.compatibility_result,
        )
        for report in reports
    ]
