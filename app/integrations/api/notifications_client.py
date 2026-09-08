from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.integrations.api.client import DesktopApiClient


class NotificationsApiClient:
    """Cliente da camada generica de notificacoes (`/api/v1/notifications`).

    Usada tanto pelo app principal (sino/Central) quanto pelo agente de
    bandeja (`notifier_agent`)."""

    def __init__(self, client: DesktopApiClient):
        self.client = client

    def _get(self, path: str, access_token: str, **params: Any) -> dict[str, Any]:
        query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
        return self.client.get(path + (f"?{query}" if query else ""), access_token=access_token).data

    def list(self, access_token: str, *, status: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return self._get("/api/v1/notifications", access_token, status=status, limit=limit, offset=offset)

    def unread_summary(self, access_token: str) -> dict[str, Any]:
        return self._get("/api/v1/notifications/unread-summary", access_token)

    def catch_up(self, access_token: str, *, since_id: int = 0, limit: int = 50) -> dict[str, Any]:
        return self._get("/api/v1/notifications/catch-up", access_token, since_id=since_id, limit=limit)

    def mark_read(self, access_token: str, notification_id: int) -> None:
        self.client.post(f"/api/v1/notifications/{notification_id}/read", access_token=access_token)

    def mark_all_read(self, access_token: str) -> None:
        self.client.post("/api/v1/notifications/mark-all-read", access_token=access_token)

    def get_preferences(self, access_token: str) -> Any:
        return self.client.get("/api/v1/notifications/preferences", access_token=access_token).data

    def put_preferences(self, access_token: str, items: list[dict[str, Any]]) -> Any:
        return self.client.put("/api/v1/notifications/preferences", json_payload={"items": items}, access_token=access_token).data

    def get_settings(self, access_token: str) -> dict[str, Any]:
        return self.client.get("/api/v1/notifications/settings", access_token=access_token).data

    def put_settings(self, access_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.put("/api/v1/notifications/settings", json_payload=payload, access_token=access_token).data
