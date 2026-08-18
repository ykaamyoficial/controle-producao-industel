from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.integrations.api.client import DesktopApiClient


class PlannedLoadsApiClient:
    """Cliente HTTP do modulo `/api/v1/planned-loads` (FASE_PL5 - CRUD basico
    de Carga Planejada). Mesmo padrao de `ProposalsApiClient`: metodos finos
    que so montam path/payload e devolvem `.data` -- toda regra de negocio
    (permissao, versionamento otimista, disponibilidade real) fica na API."""

    def __init__(self, client: DesktopApiClient):
        self.client = client

    def list_planned_loads(self, access_token: str, **filters) -> dict[str, Any]:
        params = urlencode({key: value for key, value in filters.items() if value not in (None, "")})
        path = "/api/v1/planned-loads" + (f"?{params}" if params else "")
        return self.client.get(path, access_token=access_token).data

    def get_planned_load(self, access_token: str, planned_load_id: int) -> dict[str, Any]:
        return self.client.get(f"/api/v1/planned-loads/{planned_load_id}", access_token=access_token).data

    def create_planned_load(self, access_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post("/api/v1/planned-loads", json_payload=payload, access_token=access_token).data

    def update_planned_load(self, access_token: str, planned_load_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.patch(f"/api/v1/planned-loads/{planned_load_id}", json_payload=payload, access_token=access_token).data

    def add_planned_load_items(self, access_token: str, planned_load_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/planned-loads/{planned_load_id}/items", json_payload=payload, access_token=access_token).data

    def update_planned_load_item(self, access_token: str, planned_load_id: int, item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.patch(
            f"/api/v1/planned-loads/{planned_load_id}/items/{item_id}", json_payload=payload, access_token=access_token
        ).data

    def delete_planned_load_item(self, access_token: str, planned_load_id: int, item_id: int, version: int) -> dict[str, Any]:
        # Decisao deliberada do contrato: a versao vai na query string do
        # DELETE (nao no corpo) -- corpo em DELETE e fragil contra proxies.
        query = urlencode({"version": int(version)})
        return self.client.delete(f"/api/v1/planned-loads/{planned_load_id}/items/{item_id}?{query}", access_token=access_token).data

    # -- conversao/cancelamento (FASE_PL7) --------------------------------

    def cancel_planned_load(self, access_token: str, planned_load_id: int, version: int) -> dict[str, Any]:
        payload = {"version": int(version)}
        return self.client.post(f"/api/v1/planned-loads/{planned_load_id}/cancel", json_payload=payload, access_token=access_token).data

    def build_planned_load(self, access_token: str, planned_load_id: int) -> dict[str, Any]:
        # Sem body -- POST /build so avalia disponibilidade real, nao muda
        # estado nem cria a carga real (isso e responsabilidade do
        # `mark_planned_load_converted` depois que a carga real e salva).
        return self.client.post(f"/api/v1/planned-loads/{planned_load_id}/build", access_token=access_token).data

    def mark_planned_load_converted(
        self, access_token: str, planned_load_id: int, version: int, real_load_id: int
    ) -> dict[str, Any]:
        payload = {"version": int(version), "real_load_id": int(real_load_id)}
        return self.client.post(
            f"/api/v1/planned-loads/{planned_load_id}/mark-converted", json_payload=payload, access_token=access_token
        ).data
