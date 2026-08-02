from __future__ import annotations


class SQLiteSafetyArchivedError(RuntimeError):
    pass


def __getattr__(name: str):
    raise SQLiteSafetyArchivedError(
        "sqlite_safety.py foi arquivado em tools.legacy_sqlite_runtime. "
        "O runtime oficial usa PostgreSQL pelo servidor e nao manipula arquivo de banco local."
    )
