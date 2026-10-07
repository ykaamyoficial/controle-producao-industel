"""Retencao dos dados de autenticacao que so crescem.

Em producao `auth_sessions` e `security_events` acumulavam sem expurgo
(87 mil eventos e 15,8 mil sessoes para 8 usuarios, 96% deles ruido de
token). Esta rotina apaga APENAS:

* sessoes de login ja EXPIRADAS e cuja ultima atividade (revogacao ou
  expiracao) passou do prazo -- um token expirado e recusado de qualquer
  jeito, entao a linha so serve para auditoria, que o prazo preserva;
* eventos de token (`TOKEN_REFRESHED`, `TOKEN_REUSE_DETECTED`) acima do prazo.

Nunca apaga login, logout, troca de senha, nem as acoes de negocio que a
tabela de eventos tambem guarda (producao, galvanizacao, expedicao...).

Apaga em lotes, cada um com seu commit, para nao segurar lock longo em
tabelas que outras requisicoes usam.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core.config import get_settings
from api.app.database.session import get_sessionmaker
from api.app.modules.auth.models import AuthSession, SecurityEvent

log = logging.getLogger("api.retention")

# Unicos tipos de evento que a retencao pode apagar.
TOKEN_NOISE_EVENT_TYPES = ("TOKEN_REFRESHED", "TOKEN_REUSE_DETECTED")
BATCH_SIZE = 1000
# Primeira passada so depois do startup assentar (backfill, caches, conexoes).
STARTUP_DELAY_SECONDS = 300


@dataclass(frozen=True)
class RetentionResult:
    sessions: int
    token_events: int
    dry_run: bool


def _session_condition(now: datetime, cutoff: datetime):
    # Expirada E sem atividade desde o corte: coalesce(revogada_em, expira_em).
    return (AuthSession.expires_at < now) & (func.coalesce(AuthSession.revoked_at, AuthSession.expires_at) < cutoff)


def _event_condition(cutoff: datetime):
    return SecurityEvent.event_type.in_(TOKEN_NOISE_EVENT_TYPES) & (SecurityEvent.created_at < cutoff)


async def _count(session: AsyncSession, model, condition) -> int:
    return int((await session.execute(select(func.count()).select_from(model).where(condition))).scalar_one())


async def _delete_in_batches(session: AsyncSession, model, condition, batch_size: int) -> int:
    total = 0
    while True:
        ids = select(model.id).where(condition).order_by(model.id).limit(batch_size)
        deleted = (await session.execute(delete(model).where(model.id.in_(ids)))).rowcount or 0
        await session.commit()
        total += deleted
        if deleted < batch_size:
            return total
        await asyncio.sleep(0)  # cede o event loop entre lotes


async def purge_auth_data(
    *,
    session_days: int | None = None,
    token_event_days: int | None = None,
    batch_size: int = BATCH_SIZE,
    dry_run: bool = False,
    now: datetime | None = None,
) -> RetentionResult:
    """Apaga (ou, com `dry_run`, so conta) o que passou do prazo."""
    settings = get_settings()
    now = now or datetime.now(UTC)
    session_cutoff = now - timedelta(days=session_days if session_days is not None else settings.auth_session_retention_days)
    event_cutoff = now - timedelta(days=token_event_days if token_event_days is not None else settings.security_token_event_retention_days)
    session_condition = _session_condition(now, session_cutoff)
    event_condition = _event_condition(event_cutoff)
    factory = get_sessionmaker()
    if factory is None:
        return RetentionResult(0, 0, dry_run)
    async with factory() as session:
        if dry_run:
            return RetentionResult(await _count(session, AuthSession, session_condition), await _count(session, SecurityEvent, event_condition), True)
        sessions = await _delete_in_batches(session, AuthSession, session_condition, batch_size)
        events = await _delete_in_batches(session, SecurityEvent, event_condition, batch_size)
    return RetentionResult(sessions, events, False)


async def run_retention_loop() -> None:
    """Uma passada por dia (`AUTH_RETENTION_INTERVAL_HOURS`); falha de uma passada nao derruba a API."""
    settings = get_settings()
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        try:
            result = await purge_auth_data()
            log.info("auth_retention_concluida | sessoes_apagadas=%s | eventos_de_token_apagados=%s", result.sessions, result.token_events)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("auth_retention_falhou")
        await asyncio.sleep(settings.auth_retention_interval_hours * 3600)
