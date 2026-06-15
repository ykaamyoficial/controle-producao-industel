from __future__ import annotations


class ProcessController:
    def __init__(self, service):
        self.service = service

    def filters(self, search: str = "", cliente: str = "", status: str = "", prazo: str = "") -> dict[str, str]:
        return {
            "text": search.strip(),
            "cliente": cliente.strip(),
            "status": status.strip(),
            "prazo": prazo.strip(),
        }

    def rows_for(self, area: str | None, filters: dict[str, str] | None = None):
        return self.service.process_rows(area, filters or {})

    def update_status(self, process_id: int, area: str, status: str, observation: str):
        self.service.update_status(process_id, area, status, observation)
