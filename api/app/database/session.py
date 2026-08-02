from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from api.app.core.config import Settings, get_settings


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
    return create_async_engine(settings.database_url, **engine_options)


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
