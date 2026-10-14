from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.integrations.api.client import DesktopApiClient


class NotifierApiClient:
    """Cliente das rotas do agente de avisos do Windows (`--notifier`).

    O agente nao usa a sessao do app principal: troca a credencial do
    computador (`device_token`, gravada no ultimo login) por um token curto
    que so le notificacoes (`/api/v1/notifier/*`)."""

    def __init__(self, client: DesktopApiClient):
        self.client = client

    def register_device(
        self, access_token: str, *, installation_id: str, os_user: str, device_name: str | None
    ) -> dict[str, Any]:
        return self.client.post(
            "/api/v1/notifications/devices",
            json_payload={"installation_id": installation_id, "os_user": os_user, "device_name": device_name},
            access_token=access_token,
        ).data

    def exchange_token(self, device_token: str) -> dict[str, Any]:
        return self.client.post("/api/v1/notifications/devices/token", json_payload={"device_token": device_token}).data

    def unread_summary(self, access_token: str) -> dict[str, Any]:
        return self.client.get("/api/v1/notifier/unread-summary", access_token=access_token).data

    def catch_up(self, access_token: str, *, since_id: int = 0, limit: int = 50) -> dict[str, Any]:
        query = urlencode({"since_id": int(since_id), "limit": int(limit)})
        return self.client.get(f"/api/v1/notifier/catch-up?{query}", access_token=access_token).data
