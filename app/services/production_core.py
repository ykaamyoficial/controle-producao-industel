from __future__ import annotations


class ProductionCoreArchivedError(RuntimeError):
    pass


def __getattr__(name: str):
    raise ProductionCoreArchivedError(
        "production_core.py foi arquivado em tools.legacy_sqlite_runtime. "
        "O runtime oficial usa API/PostgreSQL pelo BackendService."
    )
