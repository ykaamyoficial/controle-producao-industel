from __future__ import annotations


class ExecutiveDashboardArchivedError(RuntimeError):
    pass


def __getattr__(name: str):
    raise ExecutiveDashboardArchivedError(
        "executive_dashboard.py foi arquivado em tools.legacy_sqlite_runtime. "
        "Dashboard oficial usa API/PostgreSQL por app.services.api_reports."
    )
