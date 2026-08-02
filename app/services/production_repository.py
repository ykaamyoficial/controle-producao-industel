from __future__ import annotations


class ProductionRepositoryArchivedError(RuntimeError):
    pass


def __getattr__(name: str):
    raise ProductionRepositoryArchivedError(
        "production_repository.py foi arquivado em tools.legacy_sqlite_runtime. "
        "O runtime oficial usa API/PostgreSQL pelo BackendService."
    )
