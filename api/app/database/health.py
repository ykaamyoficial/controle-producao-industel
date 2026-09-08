from __future__ import annotations

import logging
import asyncio
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from api.app.core.config import EXPECTED_DATABASE_REVISION, get_settings
from api.app.database.session import get_engine

log = logging.getLogger("api.database")


@dataclass(frozen=True)
class DatabaseCheck:
    status: str
    revision: str | None
    revision_status: str


async def database_status() -> str:
    check = await database_check()
    if check.status == "connected":
        return "available"
    return check.status


async def current_database_revision() -> str | None:
    engine = get_engine()
    if engine is None:
        return None
    async with engine.connect() as conn:
        try:
            result = await conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
            return result.scalar_one_or_none()
        except ProgrammingError:
            return None


def revision_status(revision: str | None) -> str:
    if revision is None:
        return "unversioned"
    if revision == EXPECTED_DATABASE_REVISION:
        return "compatible"
    return "incompatible"


async def database_check() -> DatabaseCheck:
    try:
        return await asyncio.wait_for(_database_check(), timeout=get_settings().database_connect_timeout)
    except TimeoutError:
        log.warning("database_health_timeout")
        return DatabaseCheck(status="unavailable", revision=None, revision_status="unavailable")


async def _database_check() -> DatabaseCheck:
    engine = get_engine()
    if engine is None:
        return DatabaseCheck(status="not_configured", revision=None, revision_status="not_configured")
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            try:
                result = await conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
                revision = result.scalar_one_or_none()
            except ProgrammingError:
                revision = None
        return DatabaseCheck(status="connected", revision=revision, revision_status=revision_status(revision))
    except Exception:
        log.warning("database_unavailable")
        return DatabaseCheck(status="unavailable", revision=None, revision_status="unavailable")
