from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.integrations.api.client import DesktopApiClient


class ProposalsApiClient:
    def __init__(self, client: DesktopApiClient):
        self.client = client

    def list_proposals(self, access_token: str, **filters) -> dict[str, Any]:
        params = urlencode({key: value for key, value in filters.items() if value not in (None, "")})
        path = "/api/v1/proposals" + (f"?{params}" if params else "")
        return self.client.get(path, access_token=access_token).data

    def get_proposal(self, access_token: str, proposal_id: int) -> dict[str, Any]:
        return self.client.get(f"/api/v1/proposals/{proposal_id}", access_token=access_token).data

    def proposal_history(self, access_token: str, proposal_id: int, *, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        return self.client.get(f"/api/v1/proposals/{proposal_id}/history?limit={int(limit)}&offset={int(offset)}", access_token=access_token).data

    def proposal_history_rows(self, access_token: str, *, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        return self.client.get(f"/api/v1/proposals/history?limit={int(limit)}&offset={int(offset)}", access_token=access_token).data

    def list_items(self, access_token: str, proposal_id: int) -> list[dict[str, Any]]:
        data = self.client.get(f"/api/v1/proposals/{proposal_id}/items", access_token=access_token).data
        return data if isinstance(data, list) else []

    def create_proposal(self, access_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post("/api/v1/proposals", json_payload=payload, access_token=access_token).data

    def update_proposal(self, access_token: str, proposal_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.patch(f"/api/v1/proposals/{proposal_id}", json_payload=payload, access_token=access_token).data

    def cancel_proposal(self, access_token: str, proposal_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/proposals/{proposal_id}/cancel", json_payload=payload, access_token=access_token).data

    def change_status(self, access_token: str, proposal_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/proposals/{proposal_id}/status", json_payload=payload, access_token=access_token).data

    def administrative_correction(self, access_token: str, proposal_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/proposals/{proposal_id}/administrative-correction", json_payload=payload, access_token=access_token).data

    def administrative_correction_options(self, access_token: str, proposal_id: int) -> dict[str, Any]:
        return self.client.get(
            f"/api/v1/proposals/{proposal_id}/administrative-corrections/options",
            access_token=access_token,
        ).data

    def preview_administrative_correction(self, access_token: str, proposal_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(
            f"/api/v1/proposals/{proposal_id}/administrative-corrections/preview",
            json_payload=payload,
            access_token=access_token,
        ).data

    def list_production_proposals(self, access_token: str, **filters) -> dict[str, Any]:
        params = urlencode({key: value for key, value in filters.items() if value not in (None, "")})
        path = "/api/v1/production/proposals" + (f"?{params}" if params else "")
        return self.client.get(path, access_token=access_token).data

    def list_production_items(self, access_token: str, **filters) -> dict[str, Any]:
        params = urlencode({key: value for key, value in filters.items() if value not in (None, "")})
        path = "/api/v1/production/items" + (f"?{params}" if params else "")
        return self.client.get(path, access_token=access_token).data

    def list_partial_proposals(self, access_token: str, **filters) -> dict[str, Any]:
        params = urlencode({key: value for key, value in filters.items() if value not in (None, "")})
        path = "/api/v1/partials/proposals" + (f"?{params}" if params else "")
        return self.client.get(path, access_token=access_token).data

    def list_warehouse_proposals(self, access_token: str, **filters) -> dict[str, Any]:
        params = urlencode({key: value for key, value in filters.items() if value not in (None, "")})
        path = "/api/v1/warehouse/proposals" + (f"?{params}" if params else "")
        return self.client.get(path, access_token=access_token).data

    def update_warehouse_status(self, access_token: str, proposal_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/warehouse/proposals/{proposal_id}/status", json_payload=payload, access_token=access_token).data

    def get_production_detail(self, access_token: str, proposal_id: int) -> dict[str, Any]:
        return self.client.get(f"/api/v1/production/proposals/{proposal_id}", access_token=access_token).data

    def start_production(self, access_token: str, proposal_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/production/proposals/{proposal_id}/start", json_payload=payload, access_token=access_token).data

    def pause_production(self, access_token: str, proposal_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/production/proposals/{proposal_id}/pause", json_payload=payload, access_token=access_token).data

    def resume_production(self, access_token: str, proposal_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/production/proposals/{proposal_id}/resume", json_payload=payload, access_token=access_token).data

    def update_production_item_flow(self, access_token: str, proposal_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.patch(f"/api/v1/production/proposals/{proposal_id}/item-flow", json_payload=payload, access_token=access_token).data

    def update_production_item_weights(self, access_token: str, proposal_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.patch(f"/api/v1/production/proposals/{proposal_id}/item-weights", json_payload=payload, access_token=access_token).data

    def complete_production_items(self, access_token: str, proposal_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/production/proposals/{proposal_id}/complete-items", json_payload=payload, access_token=access_token).data

    def list_galvanization_candidates(self, access_token: str, **filters) -> dict[str, Any]:
        params = urlencode({key: value for key, value in filters.items() if value not in (None, "")})
        path = "/api/v1/galvanization/candidates" + (f"?{params}" if params else "")
        return self.client.get(path, access_token=access_token).data

    def list_galvanization_loads(self, access_token: str, **filters) -> dict[str, Any]:
        params = urlencode({key: value for key, value in filters.items() if value not in (None, "")})
        path = "/api/v1/galvanization/loads" + (f"?{params}" if params else "")
        return self.client.get(path, access_token=access_token).data

    def get_galvanization_load(self, access_token: str, load_id: int) -> dict[str, Any]:
        return self.client.get(f"/api/v1/galvanization/loads/{load_id}", access_token=access_token).data

    def create_galvanization_load(self, access_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post("/api/v1/galvanization/loads", json_payload=payload, access_token=access_token).data

    def update_galvanization_load(self, access_token: str, load_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.patch(f"/api/v1/galvanization/loads/{load_id}", json_payload=payload, access_token=access_token).data

    def release_galvanization_load(self, access_token: str, load_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/galvanization/loads/{load_id}/release", json_payload=payload, access_token=access_token).data

    def register_galvanization_return(self, access_token: str, load_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/galvanization/loads/{load_id}/returns", json_payload=payload, access_token=access_token).data

    def close_galvanization_load(self, access_token: str, load_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/galvanization/loads/{load_id}/close", json_payload=payload, access_token=access_token).data

    def list_expedition_proposals(self, access_token: str, **filters) -> dict[str, Any]:
        params = urlencode({key: value for key, value in filters.items() if value not in (None, "")})
        path = "/api/v1/shipping/proposals" + (f"?{params}" if params else "")
        return self.client.get(path, access_token=access_token).data

    def get_expedition_detail(self, access_token: str, proposal_id: int) -> dict[str, Any]:
        return self.client.get(f"/api/v1/shipping/proposals/{proposal_id}", access_token=access_token).data

    def start_expedition_separation(self, access_token: str, proposal_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/shipping/proposals/{proposal_id}/start-separation", json_payload=payload, access_token=access_token).data

    def separate_expedition_items(self, access_token: str, proposal_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/shipping/proposals/{proposal_id}/separate-items", json_payload=payload, access_token=access_token).data

    def deliver_expedition_items(self, access_token: str, proposal_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/shipping/proposals/{proposal_id}/deliver-items", json_payload=payload, access_token=access_token).data

    def remanage_expedition_items(self, access_token: str, proposal_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/shipping/proposals/{proposal_id}/return-to-production", json_payload=payload, access_token=access_token).data

    def compatible_remanagement_items(self, access_token: str, source_proposal_id: int, destination_proposal_id: int) -> list[dict[str, Any]]:
        params = urlencode({"source_proposal_id": source_proposal_id, "destination_proposal_id": destination_proposal_id})
        data = self.client.get(f"/api/v1/shipping/remanagements/compatible-items?{params}", access_token=access_token).data
        return data if isinstance(data, list) else []

    def preview_remanagement(self, access_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post("/api/v1/shipping/remanagements/preview", json_payload=payload, access_token=access_token).data

    def create_remanagement(self, access_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post("/api/v1/shipping/remanagements", json_payload=payload, access_token=access_token).data

    def list_remanagements(self, access_token: str, **filters) -> dict[str, Any]:
        params = urlencode({key: value for key, value in filters.items() if value not in (None, "")})
        path = "/api/v1/shipping/remanagements" + (f"?{params}" if params else "")
        return self.client.get(path, access_token=access_token).data

    def deliver_by_remanagement(self, access_token: str, proposal_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/shipping/proposals/{proposal_id}/deliver-by-remanagement", json_payload=payload, access_token=access_token).data

    def list_fiscal_records(self, access_token: str, **filters) -> dict[str, Any]:
        params = urlencode({key: value for key, value in filters.items() if value not in (None, "")})
        path = "/api/v1/fiscal/records" + (f"?{params}" if params else "")
        return self.client.get(path, access_token=access_token).data

    def get_fiscal_record(self, access_token: str, fiscal_record_id: int) -> dict[str, Any]:
        return self.client.get(f"/api/v1/fiscal/records/{fiscal_record_id}", access_token=access_token).data

    def fiscal_indicators(self, access_token: str) -> dict[str, Any]:
        return self.client.get("/api/v1/fiscal/indicators", access_token=access_token).data

    def fiscal_indicator_rows(self, access_token: str, indicator: str) -> list[dict[str, Any]]:
        data = self.client.get(f"/api/v1/fiscal/indicator-rows/{indicator}", access_token=access_token).data
        return data if isinstance(data, list) else []

    def register_fiscal_invoice(self, access_token: str, fiscal_record_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/fiscal/records/{fiscal_record_id}/invoices", json_payload=payload, access_token=access_token).data

    def register_fiscal_batch(self, access_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post("/api/v1/fiscal/emissions/batch", json_payload=payload, access_token=access_token).data

    def cancel_fiscal_invoice_item(self, access_token: str, invoice_item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/fiscal/invoice-items/{invoice_item_id}/cancel", json_payload=payload, access_token=access_token).data

    def mark_fiscal_invoice_withdrawn(self, access_token: str, fiscal_record_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/fiscal/records/{fiscal_record_id}/withdrawal", json_payload=payload, access_token=access_token).data

    def create_item(self, access_token: str, proposal_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.post(f"/api/v1/proposals/{proposal_id}/items", json_payload=payload, access_token=access_token).data

    def update_item(self, access_token: str, item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.patch(f"/api/v1/proposal-items/{item_id}", json_payload=payload, access_token=access_token).data

    def delete_item(self, access_token: str, item_id: int):
        return self.client.delete(f"/api/v1/proposal-items/{item_id}", access_token=access_token)
