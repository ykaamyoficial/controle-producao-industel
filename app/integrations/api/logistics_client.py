from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.integrations.api.client import DesktopApiClient

_BASE = "/api/v1/logistics"


def _query(**params: Any) -> str:
    return urlencode({k: v for k, v in params.items() if v not in (None, "")})


class LogisticsApiClient:
    """Cliente de `/api/v1/logistics` (LOGs de entrega e cargas de entrega)."""

    def __init__(self, client: DesktopApiClient):
        self.client = client

    # ---- LOGs ------------------------------------------------------------
    def list_logs(
        self,
        access_token: str,
        *,
        stage: str | None = None,
        search: str | None = None,
        in_load: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        query = _query(
            stage=stage,
            search=(search or "").strip() or None,
            in_load=None if in_load is None else str(bool(in_load)).lower(),
            limit=limit,
            offset=offset,
        )
        return self.client.get(f"{_BASE}/logs?{query}", access_token=access_token).data

    def eligible_proposals(self, access_token: str, *, search: str | None = None, limit: int = 200, offset: int = 0) -> dict[str, Any]:
        query = _query(search=(search or "").strip() or None, limit=limit, offset=offset)
        return self.client.get(f"{_BASE}/eligible-proposals?{query}", access_token=access_token).data

    def get_log(self, access_token: str, log_id: int) -> dict[str, Any]:
        return self.client.get(f"{_BASE}/logs/{int(log_id)}", access_token=access_token).data

    def create_log(self, access_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"{_BASE}/logs", json_payload=payload, access_token=access_token).data

    def log_action(self, access_token: str, log_id: int, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """`action`: docs, approve, proposals, items/{id}/resolve ou items/{id}/remove."""
        return self.client.post(f"{_BASE}/logs/{int(log_id)}/{action}", json_payload=payload or {}, access_token=access_token).data

    # ---- cargas de entrega -----------------------------------------------
    def list_loads(self, access_token: str, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return self.client.get(f"{_BASE}/loads?{_query(limit=limit, offset=offset)}", access_token=access_token).data

    def get_load(self, access_token: str, load_id: int) -> dict[str, Any]:
        return self.client.get(f"{_BASE}/loads/{int(load_id)}", access_token=access_token).data

    def create_load(self, access_token: str, *, departure_date: str, log_ids: list[int]) -> dict[str, Any]:
        payload = {"departure_date": departure_date, "log_ids": [int(i) for i in log_ids]}
        return self.client.post(f"{_BASE}/loads", json_payload=payload, access_token=access_token).data

    def update_load(self, access_token: str, load_id: int, *, departure_date: str) -> dict[str, Any]:
        return self.client.patch(f"{_BASE}/loads/{int(load_id)}", json_payload={"departure_date": departure_date}, access_token=access_token).data

    def add_log_to_load(self, access_token: str, load_id: int, log_id: int) -> dict[str, Any]:
        return self.client.post(f"{_BASE}/loads/{int(load_id)}/logs", json_payload={"log_id": int(log_id)}, access_token=access_token).data

    def remove_log_from_load(self, access_token: str, load_id: int, log_id: int) -> dict[str, Any]:
        return self.client.delete(f"{_BASE}/loads/{int(load_id)}/logs/{int(log_id)}", access_token=access_token).data

    def delete_load(self, access_token: str, load_id: int) -> dict[str, Any]:
        return self.client.delete(f"{_BASE}/loads/{int(load_id)}", access_token=access_token).data
