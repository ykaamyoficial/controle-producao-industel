from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache
from hashlib import sha1
from time import perf_counter
import logging

from sqlalchemy import event
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from api.app.core.config import Settings, get_settings


log = logging.getLogger("api.database.performance")
SLOW_QUERY_MS = 300.0


def _install_query_timing(engine: AsyncEngine) -> None:
    sync_engine = engine.sync_engine

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("_query_timings", []).append(perf_counter())

    @event.listens_for(sync_engine, "after_cursor_execute")
    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        starts = conn.info.get("_query_timings") or []
        started = starts.pop() if starts else perf_counter()
        duration_ms = (perf_counter() - started) * 1000
        if duration_ms < SLOW_QUERY_MS:
            return
        fingerprint = sha1(" ".join(str(statement).split()).encode("utf-8")).hexdigest()[:12]
        log.warning(
            "slow_sql duration_ms=%.1f fingerprint=%s executemany=%s",
            duration_ms, fingerprint, bool(executemany),
        )


@lru_cache
def get_engine() -> AsyncEngine | None:
    settings = get_settings()
    return create_engine_from_settings(settings)


def create_engine_from_settings(settings: Settings) -> AsyncEngine | None:
    if not settings.database_url.strip():
        return None
    connect_args = {"timeout": settings.database_connect_timeout}
    engine_options = {
        "connect_args": connect_args,
        "pool_pre_ping": True,
        "echo": settings.database_echo,
    }
    if settings.app_env == "test":
        engine_options["poolclass"] = NullPool
    else:
        engine_options.update(
            {
                "pool_size": settings.database_pool_size,
                "max_overflow": settings.database_max_overflow,
                "pool_timeout": settings.database_pool_timeout,
                "pool_recycle": settings.database_pool_recycle,
            }
        )
    engine = create_async_engine(settings.database_url, **engine_options)
    _install_query_timing(engine)
    return engine


def get_sessionmaker() -> async_sessionmaker | None:
    engine = get_engine()
    if engine is None:
        return None
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    session_factory = get_sessionmaker()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL nao configurada.")
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def dispose_engine() -> None:
    engine = get_engine()
    if engine is not None:
        await engine.dispose()
    get_engine.cache_clear()
