from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.integrations.api.client import DesktopApiClient

_BASE = "/api/v1/inspections"


class InspectionsApiClient:
    """Cliente de `/api/v1/inspections` (Inspecao/NQT por PD principal)."""

    def __init__(self, client: DesktopApiClient):
        self.client = client

    def list(
        self, access_token: str, *, stage: str | None = None, search: str | None = None, limit: int = 100, offset: int = 0
    ) -> dict[str, Any]:
        params = {"stage": stage, "search": (search or "").strip() or None, "limit": limit, "offset": offset}
        query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
        return self.client.get(f"{_BASE}?{query}", access_token=access_token).data

    def finished(self, access_token: str, *, pd_code: str | None = None) -> dict[str, Any]:
        query = urlencode({"pd_code": pd_code}) if pd_code else ""
        return self.client.get(f"{_BASE}/finished" + (f"?{query}" if query else ""), access_token=access_token).data

    def get(self, access_token: str, inspection_id: int) -> dict[str, Any]:
        return self.client.get(f"{_BASE}/{int(inspection_id)}", access_token=access_token).data

    def create(self, access_token: str, *, pd_code: str) -> dict[str, Any]:
        payload = {"pd_code": pd_code}
        return self.client.post(_BASE, json_payload=payload, access_token=access_token).data

    def pd_suggestion(self, access_token: str, proposal_id: int) -> dict[str, Any]:
        return self.client.get(f"{_BASE}/proposals/{int(proposal_id)}/pd-suggestion", access_token=access_token).data

    def from_proposal(
        self, access_token: str, *, proposal_id: int, pd_code: str, confirm_customer_conflict: bool = False
    ) -> dict[str, Any]:
        payload = {
            "proposal_id": int(proposal_id),
            "pd_code": pd_code,
            "confirm_customer_conflict": bool(confirm_customer_conflict),
        }
        return self.client.post(f"{_BASE}/from-proposal", json_payload=payload, access_token=access_token).data

    def action(self, access_token: str, inspection_id: int, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """`action`: request, register-pd, nqt, decision, pit, approve, reject ou doc."""
        return self.client.post(f"{_BASE}/{int(inspection_id)}/{action}", json_payload=payload or {}, access_token=access_token).data
