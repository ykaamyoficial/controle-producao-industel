from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from api.app.core.config import get_settings
from api.app.database.base import Base
from api.app.audit import db_models as audit_db_models  # noqa: F401
from api.app.channels import db_models as channels_db_models  # noqa: F401
from api.app.modules.auth import models as auth_models  # noqa: F401
from api.app.modules.product_catalog import models as product_catalog_models  # noqa: F401
from api.app.modules.notifications import models as notifications_models  # noqa: F401
from api.app.modules.proposal_attachments import models as proposal_attachment_models  # noqa: F401
from api.app.modules.proposals import models as proposal_models  # noqa: F401
from api.app.modules.system import models as system_models  # noqa: F401


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL nao configurada para executar migrations.")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL nao configurada para executar migrations.")
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = url
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
