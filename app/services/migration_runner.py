from __future__ import annotations


class MigrationRunnerArchivedError(RuntimeError):
    pass


def __getattr__(name: str):
    raise MigrationRunnerArchivedError(
        "migration_runner.py foi arquivado em tools.legacy_sqlite_runtime. "
        "O runtime oficial usa migrations PostgreSQL/Alembic pela API."
    )
