"""Cliente Desktop somente leitura para o historico de auditoria de
atualizacoes (Fase 16). Nenhum metodo aqui escreve nada -- espelha
api.app.modules.update_audit.router (GET .../admin/update-audit/...)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.integrations.api.client import DesktopApiClient


class UpdateAuditApiClient:
    def __init__(self, client: DesktopApiClient):
        self.client = client

    def list_events(
        self,
        token: str,
        *,
        event_type: str | None = None,
        result: str | None = None,
        channel: str | None = None,
        version: str | None = None,
        installation_id: str | None = None,
        correlation_id: str | None = None,
        release_id: str | None = None,
        deployment_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        params = {
            key: value
            for key, value in (
                ("event_type", event_type), ("result", result), ("channel", channel), ("version", version),
                ("installation_id", installation_id), ("correlation_id", correlation_id),
                ("release_id", release_id), ("deployment_id", deployment_id),
                ("date_from", date_from), ("date_to", date_to),
                ("limit", limit), ("offset", offset),
            )
            if value not in (None, "")
        }
        path = f"/api/v1/admin/update-audit/events?{urlencode(params)}"
        return self.client.get(path, access_token=token).data

    def get_event(self, token: str, event_id: str) -> dict[str, Any]:
        return self.client.get(f"/api/v1/admin/update-audit/events/{event_id}", access_token=token).data

    def get_timeline(self, token: str, correlation_id: str) -> dict[str, Any]:
        return self.client.get(f"/api/v1/admin/update-audit/timeline/{correlation_id}", access_token=token).data

    def get_installation_status(self, token: str, installation_id: str) -> dict[str, Any]:
        return self.client.get(f"/api/v1/admin/update-audit/installations/{installation_id}", access_token=token).data

    def get_release_events(self, token: str, version: str) -> dict[str, Any]:
        return self.client.get(f"/api/v1/admin/update-audit/releases/{version}", access_token=token).data
