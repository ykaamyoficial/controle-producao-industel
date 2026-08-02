from __future__ import annotations


class OperationalReportsArchivedError(RuntimeError):
    pass


def __getattr__(name: str):
    raise OperationalReportsArchivedError(
        "operational_reports.py foi arquivado em tools.legacy_sqlite_runtime. "
        "Relatorios oficiais usam API/PostgreSQL por app.services.api_reports."
    )
