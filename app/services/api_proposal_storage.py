from __future__ import annotations

import threading
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.integrations.api.auth_client import AuthApiClient
from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiConfigStore
from app.integrations.api.exceptions import (
    ApiAuthenticationError,
    ApiBusinessError,
    ApiClientError,
    ApiConnectionError,
    ApiPermissionError,
    ApiSessionExpiredError,
    ApiTimeoutError,
    ApiValidationError,
)
from app.integrations.api.chat_client import ChatApiClient
from app.integrations.api.proposals_client import ProposalsApiClient
from app.integrations.api.session import ExperimentalApiSession
from app.integrations.api.token_store import ApiTokenStore
from app.services.app_logging import get_logger

# Reaproveita os identificadores oficiais definidos no backend (unica fonte
# de verdade dos codigos de permissao) em vez de duplicar as strings aqui —
# api/app/modules/auth/permissions.py nao tem nenhuma dependencia pesada
# (FastAPI/SQLAlchemy/etc), entao e seguro de importar direto do cliente
# desktop sem puxar nada do servidor junto.
from api.app.modules.auth.permissions import (
    AUDIT_VIEW,
    CHAT_SEND,
    CHAT_VIEW,
    EXPEDITION_UPDATE,
    EXPEDITION_VIEW,
    FISCAL_CANCEL_LINK,
    FISCAL_REGISTER_EMISSION,
    FISCAL_VIEW,
    GALVANIZATION_UPDATE,
    GALVANIZATION_VIEW,
    PERMISSIONS_VIEW,
    PRODUCTION_UPDATE,
    PRODUCTION_VIEW,
    PROPOSAL_ITEMS_CREATE,
    PROPOSAL_ITEMS_DELETE,
    PROPOSAL_ITEMS_UPDATE,
    PROPOSAL_ITEMS_VIEW,
    PROPOSALS_CANCEL,
    PROPOSALS_CHANGE_STATUS,
    PROPOSALS_CREATE,
    PROPOSALS_UPDATE,
    PROPOSALS_VIEW,
    ROLES_VIEW,
    SYSTEM_ADMIN,
    USERS_CREATE,
    USERS_DISABLE,
    USERS_MANAGE_PERMISSIONS,
    USERS_UPDATE,
    USERS_VIEW,
)


log = get_logger("api_proposal_storage")

AREA_VIEW_PERMISSIONS = {
    "dashboard": {PROPOSALS_VIEW},
    "executive_dashboard": {PROPOSALS_VIEW},
    "control_general": {PROPOSALS_VIEW, PROPOSAL_ITEMS_VIEW},
    "production": {PRODUCTION_VIEW},
    "galvanization": {GALVANIZATION_VIEW},
    "expedition": {EXPEDITION_VIEW},
    "fiscal": {FISCAL_VIEW},
    "partials": {PROPOSALS_VIEW, PROPOSAL_ITEMS_VIEW},
    "warehouse": {PROPOSALS_VIEW, PROPOSAL_ITEMS_VIEW},
    "operational_reports": {PROPOSALS_VIEW, PROPOSAL_ITEMS_VIEW, FISCAL_VIEW},
    "history": {AUDIT_VIEW},
    "settings": set(),
    "users_permissions": {USERS_VIEW},
    "chats": {CHAT_VIEW},
}

AREA_EDIT_PERMISSIONS = {
    "dashboard": set(),
    "executive_dashboard": set(),
    "control_general": {
        PROPOSALS_CREATE,
        PROPOSALS_UPDATE,
        PROPOSALS_CANCEL,
        PROPOSALS_CHANGE_STATUS,
        PROPOSAL_ITEMS_CREATE,
        PROPOSAL_ITEMS_UPDATE,
        PROPOSAL_ITEMS_DELETE,
    },
    "production": {PRODUCTION_UPDATE},
    "galvanization": {GALVANIZATION_UPDATE},
    "expedition": {EXPEDITION_UPDATE},
    "fiscal": {FISCAL_REGISTER_EMISSION, FISCAL_CANCEL_LINK},
    "partials": {PROPOSALS_CHANGE_STATUS, PROPOSAL_ITEMS_UPDATE},
    "warehouse": {PROPOSALS_CHANGE_STATUS},
    "operational_reports": set(),
    "history": set(),
    "settings": {SYSTEM_ADMIN},
    "users_permissions": {USERS_CREATE, USERS_UPDATE, USERS_DISABLE, USERS_MANAGE_PERMISSIONS, ROLES_VIEW, PERMISSIONS_VIEW},
    "chats": {CHAT_SEND},
}

API_PERMISSION_TO_AREA = {
    PROPOSALS_VIEW: ("control_general", "VIEW"),
    PROPOSAL_ITEMS_VIEW: ("control_general", "VIEW"),
    PROPOSALS_CREATE: ("control_general", "EDIT"),
    PROPOSALS_UPDATE: ("control_general", "EDIT"),
    PROPOSALS_CANCEL: ("control_general", "EDIT"),
    PROPOSALS_CHANGE_STATUS: ("control_general", "EDIT"),
    PROPOSAL_ITEMS_CREATE: ("control_general", "EDIT"),
    PROPOSAL_ITEMS_UPDATE: ("control_general", "EDIT"),
    PROPOSAL_ITEMS_DELETE: ("control_general", "EDIT"),
    PRODUCTION_VIEW: ("production", "VIEW"),
    PRODUCTION_UPDATE: ("production", "EDIT"),
    GALVANIZATION_VIEW: ("galvanization", "VIEW"),
    GALVANIZATION_UPDATE: ("galvanization", "EDIT"),
    EXPEDITION_VIEW: ("expedition", "VIEW"),
    EXPEDITION_UPDATE: ("expedition", "EDIT"),
    FISCAL_VIEW: ("fiscal", "VIEW"),
    FISCAL_REGISTER_EMISSION: ("fiscal", "EDIT"),
    FISCAL_CANCEL_LINK: ("fiscal", "EDIT"),
    AUDIT_VIEW: ("history", "VIEW"),
    SYSTEM_ADMIN: ("settings", "EDIT"),
    USERS_VIEW: ("users_permissions", "VIEW"),
    USERS_CREATE: ("users_permissions", "EDIT"),
    USERS_UPDATE: ("users_permissions", "EDIT"),
    USERS_DISABLE: ("users_permissions", "EDIT"),
    USERS_MANAGE_PERMISSIONS: ("users_permissions", "EDIT"),
    CHAT_VIEW: ("chats", "VIEW"),
    CHAT_SEND: ("chats", "EDIT"),
}


class OfficialProposalStorageError(RuntimeError):
    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


class _BorrowedApiClient:
    """Client view used by operations without closing the persistent session."""

    def __init__(self, storage: "OfficialProposalApiStorage", client: DesktopApiClient):
        self._storage = storage
        self._client = client

    def close(self) -> None:
        return

    def get(self, path: str, *, access_token: str | None = None, retries: int = 1):
        return self.request("GET", path, access_token=access_token, retries=retries)

    def post(self, path: str, *, json_payload: dict[str, Any] | None = None, access_token: str | None = None):
        return self.request("POST", path, json_payload=json_payload, access_token=access_token, retries=0)

    def patch(self, path: str, *, json_payload: dict[str, Any] | None = None, access_token: str | None = None):
        return self.request("PATCH", path, json_payload=json_payload, access_token=access_token, retries=0)

    def delete(self, path: str, *, access_token: str | None = None):
        return self.request("DELETE", path, access_token=access_token, retries=0)

    def request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        access_token: str | None = None,
        retries: int = 0,
    ):
        token = access_token if access_token else None
        try:
            return self._client.request(method, path, json_payload=json_payload, access_token=token, retries=retries)
        except ApiSessionExpiredError:
            if not access_token:
                raise
            state = self._storage.refresh_session(force=True)
            if not state.access_token:
                raise
            return self._client.request(method, path, json_payload=json_payload, access_token=state.access_token, retries=retries)


class OfficialProposalApiStorage:
    def __init__(
        self,
        *,
        config_store: DesktopApiConfigStore | None = None,
        token_store: ApiTokenStore | None = None,
        client_factory=None,
    ):
        self.config_store = config_store or DesktopApiConfigStore()
        self.token_store = token_store or ApiTokenStore()
        self.client_factory = client_factory or (lambda settings: DesktopApiClient(settings))
        self._client_lock = threading.RLock()
        self._persistent_client: DesktopApiClient | None = None
        self._session: ExperimentalApiSession | None = None
        self._settings_key: tuple[Any, ...] | None = None
        self.refresh_count = 0

    def list_proposals(self, **filters) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            payload = proposals.list_proposals(token, **filters)
            return [_api_proposal_to_process(row) for row in payload.get("items", [])]
        finally:
            client.close()

    def list_production_proposals(self, **filters) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            payload = proposals.list_production_proposals(token, **filters)
            return [_api_production_to_process(row) for row in payload.get("items", [])]
        finally:
            client.close()

    def production_items_queue(self, **filters) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            payload = proposals.list_production_items(token, **filters)
            return [_api_production_item_row_to_process_item(row) for row in payload.get("items", [])]
        finally:
            client.close()

    def partial_rows(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        client, proposals, token = self._client()
        try:
            payload = proposals.list_partial_proposals(
                token,
                search=filters.get("text") or None,
                limit=200,
                offset=0,
            )
            return [_api_partial_to_process(row) for row in payload.get("items", [])]
        finally:
            client.close()

    def warehouse_rows(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        client, proposals, token = self._client()
        try:
            payload = proposals.list_warehouse_proposals(
                token,
                search=filters.get("text") or None,
                status=filters.get("status") or None,
                limit=200,
                offset=0,
            )
            return [_api_warehouse_to_process(row) for row in payload.get("items", [])]
        finally:
            client.close()

    def update_warehouse_status(self, proposal_id: int, version: int, status: str, observation: str = "") -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            return _api_warehouse_to_process(
                proposals.update_warehouse_status(
                    token,
                    proposal_id,
                    {"version": int(version), "status": status, "observation": observation or None},
                )
            )
        finally:
            client.close()

    def process_partials(self, proposal_id: int) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            detail = proposals.get_proposal(token, proposal_id)
            partials = proposals.list_partial_proposals(
                token,
                search=detail.get("proposal_number") or None,
                limit=20,
                offset=0,
            ).get("items", [])
            rows = [_api_partial_to_process(row) for row in partials if int(row.get("id") or 0) == int(proposal_id)]
            return rows or [_api_proposal_to_process(detail)]
        finally:
            client.close()

    def get_production_process(self, proposal_id: int) -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            return _api_production_to_process(proposals.get_production_detail(token, proposal_id))
        finally:
            client.close()

    def get_process(self, proposal_id: int) -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            return _api_proposal_to_process(proposals.get_proposal(token, proposal_id))
        finally:
            client.close()

    def proposal_items(self, proposal_id: int) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            return [_api_item_to_process_item(item) for item in proposals.list_items(token, proposal_id) if item.get("active", True)]
        finally:
            client.close()

    def production_items(self, proposal_id: int, *, pending_production: bool = False) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            detail = proposals.get_production_detail(token, proposal_id)
            items = [_api_item_to_process_item(item) for item in detail.get("items", []) if item.get("active", True)]
            if pending_production:
                return [item for item in items if not item.get("produzido") and item.get("produzir_internamente") != "nao"]
            return items
        finally:
            client.close()

    def flow_review_data(self, proposal_id: int) -> dict[str, Any]:
        """Single-call data source for the flow review screen: proposal header info plus
        every item (including flow_editable/flow_lock_reason), reusing the same production
        detail endpoint already used by get_production_process()/production_items()."""
        client, proposals, token = self._client()
        try:
            detail = proposals.get_production_detail(token, proposal_id)
            items = [_api_item_to_process_item(item) for item in detail.get("items", []) if item.get("active", True)]
            return {
                "proposal_id": detail.get("id"),
                "proposta": detail.get("proposal_number") or "",
                "cliente": detail.get("customer_name") or "",
                "version": detail.get("version"),
                "itens": items,
            }
        finally:
            client.close()

    def production_item_flow_summary(self, proposal_id: int) -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            detail = proposals.get_production_detail(token, proposal_id)
            progress = detail.get("progress") or {}
            return {
                "total": progress.get("total_items", 0),
                "undefined_count": progress.get("undefined_flow_items", 0),
                "needs_galvanization_count": progress.get("needs_galvanization_items", 0),
                "no_internal_production_count": progress.get("total_items", 0) - progress.get("internal_items", 0),
            }
        finally:
            client.close()

    def save_process(self, data: dict[str, Any], process_id: int | None = None, import_metadata: dict[str, Any] | None = None) -> int:
        client, proposals, token = self._client()
        try:
            if process_id:
                current = proposals.get_proposal(token, process_id)
                updated = proposals.update_proposal(token, process_id, _proposal_update_payload(data, current))
                self._sync_items(proposals, token, process_id, data.get("itens") or [], current.get("items") or [])
                return int(updated["id"])
            created = proposals.create_proposal(token, _proposal_create_payload(data, import_metadata))
            return int(created["id"])
        finally:
            client.close()

    def cancel_process(self, proposal_id: int, version: int, reason: str) -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            return _api_proposal_to_process(proposals.cancel_proposal(token, proposal_id, {"version": version, "reason": reason}))
        finally:
            client.close()

    def release_to_production(self, proposal_id: int, version: int) -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            return _api_proposal_to_process(
                proposals.change_status(
                    token,
                    proposal_id,
                    {"version": version, "to_area": "PRODUCAO", "to_status": "LIBERADO_PRODUCAO", "reason": "Liberacao pelo desktop"},
                )
            )
        finally:
            client.close()

    def administrative_correction_options(self, proposal_id: int) -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            return proposals.administrative_correction_options(token, proposal_id)
        finally:
            client.close()

    def preview_administrative_correction(
        self,
        proposal_id: int,
        expected_version: int,
        new_area: str,
        new_status: str,
    ) -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            return proposals.preview_administrative_correction(
                token,
                proposal_id,
                {
                    "expected_version": expected_version,
                    "correction_type": "STATE",
                    "to_area": str(new_area or "").replace(" ", "_"),
                    "to_status": new_status,
                },
            )
        finally:
            client.close()

    def administrative_correction(
        self,
        proposal_id: int,
        expected_version: int,
        new_area: str,
        new_status: str,
        reason: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            return _api_proposal_to_process(
                proposals.administrative_correction(
                    token,
                    proposal_id,
                    {
                        "expected_version": expected_version,
                        "correction_type": "STATE",
                        "to_area": str(new_area or "").replace(" ", "_"),
                        "to_status": new_status,
                        "reason": reason,
                        "idempotency_key": idempotency_key,
                    },
                )
            )
        finally:
            client.close()

    def start_production(self, proposal_id: int, version: int, observation: str = "") -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            return _api_production_to_process(proposals.start_production(token, proposal_id, {"version": version, "observation": observation or None}))
        finally:
            client.close()

    def pause_production(self, proposal_id: int, version: int, reason: str) -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            return _api_production_to_process(proposals.pause_production(token, proposal_id, {"version": version, "reason": reason}))
        finally:
            client.close()

    def resume_production(self, proposal_id: int, version: int, observation: str = "") -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            return _api_production_to_process(proposals.resume_production(token, proposal_id, {"version": version, "observation": observation or None}))
        finally:
            client.close()

    def update_production_item_flow(self, proposal_id: int, version: int, definitions: list[dict[str, Any]], origin: str = "Producao") -> int:
        client, proposals, token = self._client()
        try:
            items = [
                {
                    "item_id": int(item.get("api_id") or item.get("id")),
                    "version": int(item.get("api_version") or item.get("version") or 1),
                    "produce_internally": _flag_to_bool(item.get("produzir_internamente")),
                    "non_production_reason": _optional(item.get("motivo_nao_produzir")),
                    "requires_galvanization": _flag_to_bool(item.get("precisa_galvanizacao")),
                    "notes": _optional(item.get("observacao_fluxo_item")),
                }
                for item in definitions
            ]
            proposals.update_production_item_flow(token, proposal_id, {"version": version, "origin": origin, "items": items})
            return len(items)
        finally:
            client.close()

    def update_production_item_weights(self, proposal_id: int, version: int, weights: dict[int, float]) -> int:
        current = {int(item["id"]): item for item in self.production_items(proposal_id)}
        items = []
        for item_id, weight in weights.items():
            item = current.get(int(item_id))
            if not item:
                continue
            items.append({"item_id": int(item_id), "version": int(item.get("api_version") or 1), "unit_weight": str(weight)})
        if not items:
            return 0
        client, proposals, token = self._client()
        try:
            proposals.update_production_item_weights(token, proposal_id, {"version": version, "items": items})
            return len(items)
        finally:
            client.close()

    def complete_production_items(self, proposal_id: int, version: int, item_ids: list[int] | None = None, observation: str = "") -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            payload = {"version": version, "item_ids": item_ids or None, "observation": observation or None}
            return _api_production_to_process(proposals.complete_production_items(token, proposal_id, payload))
        finally:
            client.close()

    def galvanization_load_candidates(self, proposal: str = "", client_name: str = "") -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            search = " ".join(part for part in [proposal.strip(), client_name.strip()] if part)
            payload = proposals.list_galvanization_candidates(token, search=search)
            grouped: dict[int, dict[str, Any]] = {}
            for item in payload.get("items", []):
                proposal_id = int(item["proposal_id"])
                row = grouped.setdefault(
                    proposal_id,
                    {
                        "id": proposal_id,
                        "processo_id": proposal_id,
                        "proposta": item.get("proposal_number") or "",
                        "parent_proposal_id": item.get("parent_proposal_id"),
                        "partial_number": item.get("partial_number"),
                        "cliente": item.get("customer_name") or "",
                        "obra_site": item.get("project_name") or "",
                        "lote": item.get("lot") or "",
                        "status_galvanizacao": "AGUARDANDO_ENVIO",
                        "peso": "0",
                        "peso_sugerido": "0",
                        "peso_disponivel_envio": "0",
                        "_galvanization_items": [],
                    },
                )
                row["_galvanization_items"].append(item)
                row["peso"] = _decimal_text(_decimal(row["peso"], default="0") + _decimal(item.get("available_weight"), default="0"))
                row["peso_sugerido"] = row["peso"]
                row["peso_disponivel_envio"] = row["peso"]
            return list(grouped.values())
        finally:
            client.close()

    def galvanization_items_queue(self, **filters) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            payload = proposals.list_galvanization_candidates(token, **filters)
            return [_api_galvanization_item_row_to_process_item(row) for row in payload.get("items", [])]
        finally:
            client.close()

    def galvanization_loads(self) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            payload = proposals.list_galvanization_loads(token)
            return [_api_galvanization_load_to_legacy(row) for row in payload.get("items", [])]
        finally:
            client.close()

    def get_galvanization_load_dict(self, load_id: int) -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            return _api_galvanization_load_to_legacy(proposals.get_galvanization_load(token, load_id))
        finally:
            client.close()

    def galvanization_load_details(self, load_id: int) -> dict[str, Any]:
        """Retorna a visão completa da carga com uma única chamada oficial.

        A agregação permanece no endpoint de cargas; este adaptador somente
        traduz o contrato da API para os nomes usados pela interface desktop.
        """

        client, proposals, token = self._client()
        try:
            detail = proposals.get_galvanization_load(token, load_id)
            return {
                "load": _api_galvanization_load_to_legacy(detail),
                "proposals": [
                    _api_galvanization_proposal_to_legacy(row)
                    for row in detail.get("proposals", [])
                ],
                "items": [
                    _api_galvanization_item_to_legacy(row)
                    for row in detail.get("items", [])
                ],
                "returns": [
                    _api_galvanization_return_to_legacy(row, number=index)
                    for index, row in enumerate(detail.get("returns", []), start=1)
                ],
                "history": [
                    _api_galvanization_history_to_legacy(row)
                    for row in detail.get("history", [])
                ],
            }
        finally:
            client.close()

    def galvanization_load_items(self, load_id: int) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            detail = proposals.get_galvanization_load(token, load_id)
            return [_api_galvanization_proposal_to_legacy(row) for row in detail.get("proposals", [])]
        finally:
            client.close()

    def galvanization_load_proposal_items(self, load_id: int, process_id: int) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            detail = proposals.get_galvanization_load(token, load_id)
            return [_api_galvanization_item_to_legacy(row) for row in detail.get("items", []) if int(row.get("proposal_id") or 0) == int(process_id)]
        finally:
            client.close()

    def galvanization_load_all_items(self, load_id: int) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            detail = proposals.get_galvanization_load(token, load_id)
            return [_api_galvanization_item_to_legacy(row) for row in detail.get("items", [])]
        finally:
            client.close()

    def galvanization_return_proposals(self, load_id: int) -> list[dict[str, Any]]:
        return [row for row in self.galvanization_load_items(load_id) if _decimal(row.get("peso_pendente"), default="0") > 0]

    def galvanization_return_items(self, load_id: int, process_id: int) -> list[dict[str, Any]]:
        return [row for row in self.galvanization_load_proposal_items(load_id, process_id) if _decimal(row.get("quantidade_pendente"), default="0") > 0]

    def galvanization_available_weight_info(self, process_id: int, load_id: int | None = None) -> dict[str, Any]:
        candidates = self.galvanization_load_candidates()
        row = next((item for item in candidates if int(item.get("id") or 0) == int(process_id)), None)
        if not row:
            return {"processo_id": process_id, "peso_produzido_elegivel": 0, "peso_ja_enviado": 0, "peso_disponivel_envio": 0, "peso_sugerido": 0, "origem_peso": "api_galvanization"}
        return {
            "processo_id": process_id,
            "proposta": row.get("proposta"),
            "cliente": row.get("cliente"),
            "peso_total_proposta": row.get("peso"),
            "peso_produzido_elegivel": row.get("peso"),
            "peso_ja_enviado": 0,
            "peso_disponivel_envio": row.get("peso_disponivel_envio"),
            "peso_sugerido": row.get("peso_sugerido"),
            "origem_peso": "api_galvanization_items",
            "possui_peso_estimado": False,
            "possui_itens_sem_peso": False,
            "envio_parcial_anterior": False,
        }

    def save_galvanization_load(
        self,
        driver: str,
        max_weight: str,
        expected_return_date: str,
        items: list[dict[str, Any]],
        load_id: int | None = None,
        *,
        load_weight: str | None = None,
        load_weight_source: str | None = "MANUAL",
        expected_version: int | None = None,
    ) -> int:
        payload_items = []
        for row in items:
            item_id = int(row.get("item_id") or 0)
            if not item_id:
                continue
            entry: dict[str, Any] = {"proposal_item_id": item_id}
            version = row.get("version")
            if version:
                entry["version"] = int(version)
            sent_quantity = row.get("sent_quantity")
            if sent_quantity not in (None, ""):
                entry["sent_quantity"] = str(sent_quantity)
            payload_items.append(entry)
        payload = {
            "driver_name": driver,
            "max_weight": _optional_decimal(max_weight),
            "load_weight": _optional_known_decimal(load_weight),
            "load_weight_source": load_weight_source if _optional_known_decimal(load_weight) is not None else None,
            "expected_return_date": _date_iso(expected_return_date),
            "items": payload_items,
        }
        client, proposals, token = self._client()
        try:
            if load_id:
                if expected_version is None:
                    current = proposals.get_galvanization_load(token, load_id)
                    expected_version = int(current["version"])
                payload["version"] = int(expected_version)
                return int(proposals.update_galvanization_load(token, load_id, payload)["id"])
            return int(proposals.create_galvanization_load(token, payload)["id"])
        finally:
            client.close()

    def add_items_to_galvanization_load(
        self,
        load_id: int,
        *,
        item_ids: list[int] | None = None,
        proposal_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Inclui saldo elegivel em uma carga aberta sem abrir a tela de edicao.

        A composicao atual e preservada e somente os itens solicitados sao
        acrescentados. A API continua sendo a autoridade para saldo,
        elegibilidade, capacidade e concorrencia da carga.
        """
        client, proposals, token = self._client()
        try:
            current = proposals.get_galvanization_load(token, int(load_id))
            selected_ids = {int(value) for value in (item_ids or []) if value}
            selected_proposals = {int(value) for value in (proposal_ids or []) if value}
            existing_ids = {
                int(row.get("proposal_item_id"))
                for row in current.get("items", [])
                if row.get("active", True) and row.get("proposal_item_id")
            }
            entries = [
                {
                    "proposal_item_id": int(row["proposal_item_id"]),
                    "sent_quantity": str(row.get("sent_quantity")),
                }
                for row in current.get("items", [])
                if row.get("active", True) and row.get("proposal_item_id")
            ]
            candidates = proposals.list_galvanization_candidates(token, limit=200, offset=0).get("items", [])
            added_ids: list[int] = []
            for row in candidates:
                proposal_id = int(row.get("proposal_id") or 0)
                proposal_item_id = int(row.get("item_id") or 0)
                if not proposal_item_id or proposal_item_id in existing_ids:
                    continue
                if selected_ids and proposal_item_id not in selected_ids:
                    continue
                if not selected_ids and selected_proposals and proposal_id not in selected_proposals:
                    continue
                available = row.get("available_quantity")
                if available in (None, "", 0, "0"):
                    continue
                entries.append({
                    "proposal_item_id": proposal_item_id,
                    "version": int(row.get("version") or 1),
                    "sent_quantity": str(available),
                })
                added_ids.append(proposal_item_id)
            if not added_ids:
                raise ValueError("Nenhum item elegivel novo foi encontrado para adicionar a esta carga.")
            payload = {
                "version": int(current["version"]),
                "items": entries,
            }
            updated = proposals.update_galvanization_load(token, int(load_id), payload)
            updated["added_item_ids"] = added_ids
            return updated
        finally:
            client.close()

    def release_galvanization_load(self, load_id: int) -> None:
        client, proposals, token = self._client()
        try:
            current = proposals.get_galvanization_load(token, load_id)
            proposals.release_galvanization_load(token, load_id, {"version": int(current["version"])})
        finally:
            client.close()

    def register_galvanization_partial_return(self, load_id: int, returned_items: list[dict[str, Any]], observation: str = "") -> int:
        client, proposals, token = self._client()
        try:
            current = proposals.get_galvanization_load(token, load_id)
            proposal_ids = []
            items = []
            proposal_by_load_item = {int(row["id"]): int(row["proposal_id"]) for row in current.get("items", [])}
            for row in returned_items:
                if row.get("proposal_level") and row.get("processo_id"):
                    proposal_ids.append(int(row["processo_id"]))
                    continue
                if row.get("proposal_level") and row.get("carga_item_id"):
                    proposal_id = proposal_by_load_item.get(int(row["carga_item_id"]))
                    if proposal_id:
                        proposal_ids.append(proposal_id)
                    continue
                load_item_id = int(row.get("detail_id") or row.get("id") or 0)
                if load_item_id:
                    items.append({"load_item_id": load_item_id, "quantity_returned": str(row.get("quantidade_retornada") or row.get("quantity") or "") or None})
            proposals.register_galvanization_return(
                token,
                load_id,
                {"version": int(current["version"]), "proposal_ids": proposal_ids or None, "items": items or None, "observation": observation or None},
            )
            return len(proposal_ids) + len(items)
        finally:
            client.close()

    def list_expedition_proposals(self, **filters) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            payload = proposals.list_expedition_proposals(token, **filters)
            return [_api_expedition_to_process(row) for row in payload.get("items", [])]
        finally:
            client.close()

    def get_expedition_process(self, proposal_id: int) -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            return _api_expedition_to_process(proposals.get_expedition_detail(token, proposal_id))
        finally:
            client.close()

    def expedition_items(self, proposal_id: int, *, pending_delivery: bool = False) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            detail = proposals.get_expedition_detail(token, proposal_id)
            items = [_api_expedition_item_to_process_item(row) for row in detail.get("items", [])]
            if pending_delivery:
                return [row for row in items if _decimal(row.get("saldo_separado"), default="0") > 0]
            return [row for row in items if _decimal(row.get("saldo_pendente"), default="0") > 0 or _decimal(row.get("saldo_separado"), default="0") > 0]
        finally:
            client.close()

    def start_expedition_separation(self, proposal_id: int, version: int, observation: str = "") -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            return _api_expedition_to_process(proposals.start_expedition_separation(token, proposal_id, {"version": version, "observation": observation or None}))
        finally:
            client.close()

    def separate_expedition_items(self, proposal_id: int, version: int, item_ids: list[int] | None = None, observation: str = "") -> dict[str, Any]:
        payload = {"version": version, "items": _expedition_item_payload(item_ids), "observation": observation or None}
        client, proposals, token = self._client()
        try:
            return _api_expedition_to_process(proposals.separate_expedition_items(token, proposal_id, payload))
        finally:
            client.close()

    def deliver_expedition_items(self, proposal_id: int, version: int, item_ids: list[int] | None = None, observation: str = "") -> dict[str, Any]:
        payload = {"version": version, "items": _expedition_item_payload(item_ids), "observation": observation or None}
        log.debug("Registrando entrega: proposal_id=%r version=%r payload=%r", proposal_id, version, payload)
        client, proposals, token = self._client()
        try:
            return _api_expedition_to_process(proposals.deliver_expedition_items(token, proposal_id, payload))
        finally:
            client.close()

    def remanage_expedition_items(self, proposal_id: int, version: int, item_ids: list[int] | None = None, reason: str = "") -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            source = proposals.get_expedition_detail(token, proposal_id)
            payload = {
                "version": version,
                "items": _expedition_remanagement_item_payload(item_ids, source.get("items") or []),
                "reason": reason or "Remanejamento de material",
            }
            return _api_expedition_to_process(proposals.remanage_expedition_items(token, proposal_id, payload))
        finally:
            client.close()

    def deliver_by_material_remanagement(self, destination_id: int, source_id: int, observation: str, item_ids: list[int] | None = None) -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            destination = proposals.get_proposal(token, destination_id)
            source = proposals.get_proposal(token, source_id)
            compatible = proposals.compatible_remanagement_items(token, source_id, destination_id)
            selected = {int(value) for value in (item_ids or [])}
            mappings = [row for row in compatible if not selected or int(row["source_item_id"]) in selected]
            if not mappings:
                raise ValueError("Nao existem itens compativeis com saldo para este remanejamento.")
            import uuid
            payload = {
                "source_proposal_id": source_id,
                "destination_proposal_id": destination_id,
                "source_version": int(source["version"]),
                "destination_version": int(destination["version"]),
                "idempotency_key": str(uuid.uuid4()),
                "items": [
                    {
                        "source_item_id": int(row["source_item_id"]),
                        "destination_item_id": int(row["destination_item_id"]),
                        "source_item_version": int(row["source_item_version"]),
                        "destination_item_version": int(row["destination_item_version"]),
                        "quantity": str(row["max_remanageable"]),
                    }
                    for row in mappings
                ],
                "reason": observation or "Remanejamento compensado de material",
            }
            return proposals.create_remanagement(token, payload)
        finally:
            client.close()

    def remanagement_compatible_items(self, source_id: int, destination_id: int) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            return proposals.compatible_remanagement_items(token, source_id, destination_id)
        finally:
            client.close()

    def preview_material_remanagement(self, payload: dict[str, Any]) -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            return proposals.preview_remanagement(token, payload)
        finally:
            client.close()

    def apply_material_remanagement(self, payload: dict[str, Any]) -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            return proposals.create_remanagement(token, payload)
        finally:
            client.close()

    def remanagement_rows(self, *, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            response = proposals.list_remanagements(token, limit=limit, offset=offset)
            rows = []
            for operation in response.get("items", []):
                for item in operation.get("items", []):
                    unit_weight = item.get("weight_snapshot")
                    rows.append({
                        "acao": "REMANEJAMENTO_COMPENSADO",
                        "codigo": operation.get("code"),
                        "processo_origem_id": operation.get("source_proposal_id"),
                        "processo_destino_id": operation.get("destination_proposal_id"),
                        "item_origem_id": item.get("source_item_id"),
                        "item_destino_id": item.get("destination_item_id"),
                        "codigo_produto": item.get("product_code"),
                        "unidade": item.get("unit"),
                        "quantidade": item.get("quantity"),
                        "producao_realocada": item.get("production_reallocated_quantity"),
                        "peso_remanejado": str(Decimal(str(item["quantity"])) * Decimal(str(unit_weight))) if unit_weight is not None else None,
                        "motivo": operation.get("reason"),
                        "usuario_id": operation.get("created_by"),
                        "data": operation.get("created_at"),
                        "entrega": False,
                    })
            return rows
        finally:
            client.close()

    def fiscal_rows(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        filters = filters or {}
        client, proposals, token = self._client()
        try:
            payload = proposals.list_fiscal_records(
                token,
                search=filters.get("text") or None,
                status=filters.get("status_fiscal") or None,
                situation=filters.get("situacao_fiscal") or None,
                limit=200,
                offset=0,
            )
            rows = [_api_fiscal_record_to_legacy(row) for row in payload.get("items", [])]
            return _filter_fiscal_rows(rows, filters)
        finally:
            client.close()

    def fiscal_items(self, fiscal_record_id: int) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            detail = proposals.get_fiscal_record(token, fiscal_record_id)
            return [_api_fiscal_item_to_legacy(row) for row in detail.get("items", [])]
        finally:
            client.close()

    def fiscal_emissions(self, fiscal_record_id: int) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            detail = proposals.get_fiscal_record(token, fiscal_record_id)
            return [_api_fiscal_invoice_to_legacy(row) for row in detail.get("invoices", [])]
        finally:
            client.close()

    def fiscal_movements(self, fiscal_record_id: int) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            detail = proposals.get_fiscal_record(token, fiscal_record_id)
            return [_api_fiscal_event_to_legacy(row) for row in detail.get("events", [])]
        finally:
            client.close()

    def fiscal_indicators(self) -> dict[str, Any]:
        client, proposals, token = self._client()
        try:
            return proposals.fiscal_indicators(token)
        finally:
            client.close()

    def fiscal_indicator_rows(self, indicator: str) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            return [_api_fiscal_record_to_legacy(row) for row in proposals.fiscal_indicator_rows(token, indicator)]
        finally:
            client.close()

    def fiscal_report_rows(self, report_type: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if report_type == "EMISSOES":
            rows = []
            for record in self.fiscal_rows(filters):
                rows.extend(self.fiscal_emissions(int(record["fiscal_processo_id"])))
            return rows
        if report_type == "ITENS_PENDENTES":
            rows = []
            for record in self.fiscal_rows(filters):
                rows.extend([row for row in self.fiscal_items(int(record["fiscal_processo_id"])) if row.get("status_item_fiscal") != "FATURADO"])
            return rows
        status_by_report = {
            "PENDENTES": "FALTA_EMITIR_NOTA_FISCAL",
            "PARCIAIS": "NOTA_FISCAL_PARCIAL",
            "EMITIDAS": "NOTA_FISCAL_EMITIDA",
        }
        merged = dict(filters or {})
        if report_type in status_by_report:
            merged["status_fiscal"] = status_by_report[report_type]
        if report_type in {"CRITICAS", "ENTREGUES_SEM_NF"}:
            return self.fiscal_indicator_rows("pendencia_critica")
        if report_type == "MAIS_7_DIAS":
            return self.fiscal_indicator_rows("mais_7_dias_sem_emissao")
        return self.fiscal_rows(merged)

    def audit_rows(self) -> list[dict[str, Any]]:
        client, _proposals, token = self._client()
        try:
            payload = client.get("/api/v1/security-events?limit=200&offset=0", access_token=token).data
            return [_api_security_event_to_audit(row) for row in payload.get("items", [])]
        finally:
            client.close()

    def history_rows(self) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            return [_api_history_to_legacy(row) for row in proposals.proposal_history_rows(token, limit=300, offset=0)]
        finally:
            client.close()

    def process_history_rows(self, proposal_id: int) -> list[dict[str, Any]]:
        client, proposals, token = self._client()
        try:
            return [_api_history_to_legacy(row) for row in proposals.proposal_history(token, proposal_id, limit=300, offset=0)]
        finally:
            client.close()

    def user_rows(self) -> list[dict[str, Any]]:
        client, _proposals, token = self._client()
        try:
            payload = client.get("/api/v1/users?limit=200&offset=0", access_token=token).data
            return [_api_user_to_legacy(row) for row in payload.get("items", [])]
        finally:
            client.close()

    def get_user(self, user_id: int) -> dict[str, Any]:
        client, _proposals, token = self._client()
        try:
            payload = client.get(f"/api/v1/users/{int(user_id)}", access_token=token).data
            return _api_user_to_legacy(payload)
        finally:
            client.close()

    def save_user(self, data: dict[str, Any], user_id: int | None = None) -> dict[str, Any]:
        client, _proposals, token = self._client()
        try:
            display_name = str(data.get("nome") or "").strip()
            username = str(data.get("login") or "").strip()
            password = str(data.get("password") or "")
            is_admin = str(data.get("perfil") or "").strip().lower() == "admin"
            active = bool(data.get("ativo", True))
            permission_codes = legacy_permissions_to_api_codes(dict(data.get("permissions") or {}), is_admin=is_admin)
            if user_id:
                payload: dict[str, Any] = {
                    "username": username,
                    "display_name": display_name,
                    "active": active,
                    "is_superuser": is_admin,
                    "permission_codes": permission_codes,
                }
                updated = client.patch(f"/api/v1/users/{int(user_id)}", json_payload=payload, access_token=token).data
                if password:
                    updated = client.post(
                        f"/api/v1/users/{int(user_id)}/reset-password",
                        json_payload={"password": password, "revoke_sessions": True},
                        access_token=token,
                    ).data
                return _api_user_to_legacy(updated)
            payload = {
                "username": username,
                "display_name": display_name,
                "password": password,
                "active": active,
                "is_superuser": is_admin,
                "role_ids": [],
                "permission_codes": permission_codes,
            }
            created = client.post("/api/v1/users", json_payload=payload, access_token=token).data
            return _api_user_to_legacy(created)
        finally:
            client.close()

    def toggle_user(self, user_id: int) -> dict[str, Any]:
        current = self.get_user(user_id)
        client, _proposals, token = self._client()
        try:
            path = "deactivate" if current.get("ativo") else "activate"
            updated = client.post(f"/api/v1/users/{int(user_id)}/{path}", access_token=token).data
            return _api_user_to_legacy(updated)
        finally:
            client.close()

    def delete_user(self, user_id: int) -> None:
        client, _proposals, token = self._client()
        try:
            client.delete(f"/api/v1/users/{int(user_id)}", access_token=token)
        finally:
            client.close()

    def register_fiscal_emission(self, fiscal_record_id: int, emissions: list[dict[str, Any]], numero_controle: str = "", observacao: str = "") -> int:
        client, proposals, token = self._client()
        try:
            detail = proposals.get_fiscal_record(token, fiscal_record_id)
            invoice_number = (numero_controle or "").strip() or f"REGISTRO-{fiscal_record_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            items = []
            for row in emissions or []:
                fiscal_item_id = int(row.get("fiscal_item_id") or row.get("item_id") or 0)
                if not fiscal_item_id:
                    continue
                item_payload: dict[str, Any] = {"fiscal_item_id": fiscal_item_id}
                quantity_value = row.get("quantidade_emitida") if row.get("quantidade_emitida") is not None else row.get("quantity")
                if quantity_value is not None and _decimal(quantity_value, default="0") > 0:
                    item_payload["quantity"] = _decimal_text(quantity_value)
                weight_value = row.get("peso_emitido") if row.get("peso_emitido") is not None else row.get("weight")
                if weight_value is not None:
                    item_payload["weight"] = _decimal_text(weight_value) or "0"
                items.append(item_payload)
            payload = {"version": int(detail["version"]), "invoice_number": invoice_number, "observation": observacao or None, "items": items or None}
            try:
                updated = proposals.register_fiscal_invoice(token, fiscal_record_id, payload)
            except ApiClientError as exc:
                log.error(
                    "Erro ao registrar emissao fiscal: status=%s mensagem=%r request_id=%s payload=%r",
                    exc.status_code, exc.user_message, exc.request_id, payload,
                )
                raise
            invoices = updated.get("invoices") or []
            return int(invoices[0]["id"]) if invoices else 0
        finally:
            client.close()

    def mark_fiscal_invoice_withdrawn(self, fiscal_record_id: int, observacao: str = "") -> int | None:
        client, proposals, token = self._client()
        try:
            detail = proposals.get_fiscal_record(token, fiscal_record_id)
            proposals.mark_fiscal_invoice_withdrawn(token, fiscal_record_id, {"version": int(detail["version"]), "observation": observacao or None})
            return fiscal_record_id
        finally:
            client.close()

    def cancel_latest_fiscal_emission(self, fiscal_record_id: int, reason: str = "") -> int:
        client, proposals, token = self._client()
        try:
            detail = proposals.get_fiscal_record(token, fiscal_record_id)
            invoice = next(
                (
                    row for row in (detail.get("invoices") or [])
                    if (row.get("status") or "") != "CANCELADA"
                    and any(item.get("active", True) for item in (row.get("items") or []))
                ),
                None,
            )
            if not invoice:
                raise OfficialProposalStorageError("Nao existe emissao fiscal interna ativa para cancelar.", code="FISCAL_EMISSION_NOT_FOUND")
            cancelled = 0
            for item in list(invoice.get("items") or []):
                if not item.get("active", True):
                    continue
                detail = proposals.cancel_fiscal_invoice_item(
                    token,
                    int(item["id"]),
                    {
                        "version": int(detail["version"]),
                        "reason": reason or "Cancelamento interno pelo Desktop",
                    },
                )
                cancelled += 1
            return cancelled
        finally:
            client.close()

    def _sync_items(self, proposals: ProposalsApiClient, token: str, proposal_id: int, form_items: list[dict[str, Any]], current_items: list[dict[str, Any]]) -> None:
        current_by_id = {int(item["id"]): item for item in current_items if item.get("active", True)}
        seen: set[int] = set()
        for item in form_items:
            api_id = int(item.get("api_id") or 0)
            if api_id and api_id in current_by_id:
                seen.add(api_id)
                proposals.update_item(token, api_id, _item_update_payload(item, current_by_id[api_id]))
            else:
                proposals.create_item(token, proposal_id, _item_create_payload(item))
        for api_id, item in current_by_id.items():
            if api_id not in seen:
                proposals.delete_item(token, api_id)

    def start_session(self, username: str, password: str):
        settings = self._load_enabled_settings()
        session = self._ensure_session(settings)
        state = session.start(username, password)
        return state

    def refresh_session(self, *, force: bool = False):
        settings = self._load_enabled_settings()
        session = self._ensure_session(settings)
        before = session.state.access_token
        state = session.refresh_if_needed(force=force)
        if state.access_token and state.access_token != before:
            self.refresh_count += 1
        return state

    def current_access_token(self) -> str:
        state = self.refresh_session(force=False)
        if not state.access_token:
            raise OfficialProposalStorageError("Entre na API antes de salvar propostas oficiais.")
        return state.access_token

    def update_current_user(self, *, username: str | None = None, display_name: str | None = None):
        client = self._ensure_client(self._load_enabled_settings())
        return AuthApiClient(client).update_me(self.current_access_token(), username=username, display_name=display_name)

    def change_current_password(self, current_password: str, new_password: str, confirm_password: str):
        client = self._ensure_client(self._load_enabled_settings())
        return AuthApiClient(client).change_password(self.current_access_token(), current_password, new_password, confirm_password)

    def upload_current_avatar(self, filename: str, content: bytes, mime: str):
        client = self._ensure_client(self._load_enabled_settings())
        return AuthApiClient(client).upload_avatar(self.current_access_token(), filename, content, mime)

    def remove_current_avatar(self):
        client = self._ensure_client(self._load_enabled_settings())
        return AuthApiClient(client).remove_avatar(self.current_access_token())

    def avatar_bytes_for_user(self, user_id: int) -> bytes | None:
        client = self._ensure_client(self._load_enabled_settings())
        return AuthApiClient(client).avatar_bytes(self.current_access_token(), int(user_id))

    def logout_current_session(self) -> None:
        with self._client_lock:
            if self._session:
                self._session.logout()
            else:
                self.token_store.clear()

    def close(self) -> None:
        with self._client_lock:
            if self._persistent_client:
                self._persistent_client.close()
            self._persistent_client = None
            self._session = None
            self._settings_key = None

    def _client(self) -> tuple[DesktopApiClient, ProposalsApiClient, str]:
        settings = self._load_enabled_settings()
        client = self._ensure_client(settings)
        token = self.current_access_token()
        borrowed = _BorrowedApiClient(self, client)
        return borrowed, ProposalsApiClient(borrowed), token

    def _chat_client(self) -> tuple[DesktopApiClient, ChatApiClient, str]:
        settings = self._load_enabled_settings()
        client = self._ensure_client(settings)
        token = self.current_access_token()
        borrowed = _BorrowedApiClient(self, client)
        return borrowed, ChatApiClient(borrowed), token

    def chat_conversations(self, **filters) -> list[dict[str, Any]]:
        client, chat, token = self._chat_client()
        try:
            payload = chat.list_conversations(token, **filters)
            return payload.get("items", [])
        finally:
            client.close()

    def chat_messages(self, conversation_id: int, **filters) -> list[dict[str, Any]]:
        client, chat, token = self._chat_client()
        try:
            payload = chat.list_messages(token, conversation_id, **filters)
            return payload.get("items", [])
        finally:
            client.close()

    def chat_send_message(
        self,
        conversation_id: int,
        body: str,
        message_type: str = "MENSAGEM",
        mentioned_user_id: int | None = None,
        reply_to_message_id: int | None = None,
        area: str | None = None,
        due_at=None,
        is_important: bool = False,
    ) -> dict[str, Any]:
        client, chat, token = self._chat_client()
        try:
            payload: dict[str, Any] = {"body": body, "message_type": message_type}
            if mentioned_user_id:
                payload["mentioned_user_id"] = mentioned_user_id
            if reply_to_message_id:
                payload["reply_to_message_id"] = reply_to_message_id
            if area:
                payload["area"] = area
            if due_at:
                payload["due_at"] = due_at.isoformat() if hasattr(due_at, "isoformat") else due_at
            if is_important:
                payload["is_important"] = True
            return chat.post_message(token, conversation_id, payload)
        finally:
            client.close()

    def chat_answer_question(self, message_id: int, body: str) -> dict[str, Any]:
        client, chat, token = self._chat_client()
        try:
            return chat.answer_question(token, message_id, {"body": body})
        finally:
            client.close()

    def chat_proposal_timeline(self, proposal_id: int, **filters) -> dict[str, Any]:
        client, chat, token = self._chat_client()
        try:
            return chat.get_proposal_timeline(token, proposal_id, **filters)
        finally:
            client.close()

    def chat_mark_read(self, conversation_id: int, last_read_message_id: int) -> None:
        client, chat, token = self._chat_client()
        try:
            chat.mark_read(token, conversation_id, {"last_read_message_id": last_read_message_id})
        finally:
            client.close()

    def chat_unread_summary(self) -> dict[str, Any]:
        client, chat, token = self._chat_client()
        try:
            return chat.unread_summary(token)
        finally:
            client.close()

    def chat_mentionable_users(self, **filters) -> list[dict[str, Any]]:
        client, chat, token = self._chat_client()
        try:
            payload = chat.list_mentionable_users(token, **filters)
            return payload.get("items", [])
        finally:
            client.close()

    def chat_notifications(self, **filters) -> list[dict[str, Any]]:
        client, chat, token = self._chat_client()
        try:
            payload = chat.list_notifications(token, **filters)
            return payload.get("items", [])
        finally:
            client.close()

    def chat_notifications_page(self, *, status: str | None = None, limit: int = 30, offset: int = 0) -> dict[str, Any]:
        # ETAPA 10: variante paginada pra Central de Notificacoes -- devolve
        # o envelope inteiro (items/total/has_more), diferente de
        # chat_notifications() acima, que so serve pro polling de toasts
        # (esse ja tem callers existentes esperando uma lista simples).
        client, chat, token = self._chat_client()
        try:
            return chat.list_notifications(token, status=status, limit=limit, offset=offset)
        finally:
            client.close()

    def chat_mark_all_notifications_read(self) -> None:
        client, chat, token = self._chat_client()
        try:
            chat.mark_all_notifications_read(token)
        finally:
            client.close()

    def chat_mark_notification_read(self, notification_id: int) -> None:
        client, chat, token = self._chat_client()
        try:
            chat.mark_notification_read(token, notification_id)
        finally:
            client.close()

    def chat_mark_question_viewed(self, message_id: int) -> dict[str, Any]:
        client, chat, token = self._chat_client()
        try:
            return chat.mark_question_viewed(token, message_id)
        finally:
            client.close()

    def chat_cancel_question(self, message_id: int, reason: str) -> dict[str, Any]:
        client, chat, token = self._chat_client()
        try:
            return chat.cancel_question(token, message_id, {"reason": reason})
        finally:
            client.close()

    def chat_reassign_question(self, message_id: int, assignee_user_id: int, reason: str) -> dict[str, Any]:
        client, chat, token = self._chat_client()
        try:
            return chat.reassign_question(token, message_id, {"assignee_user_id": assignee_user_id, "reason": reason})
        finally:
            client.close()

    def proposal_activities(self, proposal_id: int, **filters) -> list[dict[str, Any]]:
        client, chat, token = self._chat_client()
        try:
            return chat.get_proposal_activities(token, proposal_id, **filters)
        finally:
            client.close()

    def _load_enabled_settings(self):
        settings = self.config_store.load_settings()
        if not settings.enabled:
            raise OfficialProposalStorageError("A API oficial esta desativada nas configuracoes do desktop.")
        return settings

    def _ensure_session(self, settings):
        client = self._ensure_client(settings)
        with self._client_lock:
            if not self._session:
                self._session = ExperimentalApiSession(settings=settings, auth_client=AuthApiClient(client), token_store=self.token_store)
            return self._session

    def _ensure_client(self, settings) -> DesktopApiClient:
        key = (
            settings.enabled,
            settings.base_url,
            settings.connect_timeout,
            settings.read_timeout,
        )
        with self._client_lock:
            if self._persistent_client is not None and self._settings_key == key:
                return self._persistent_client
            if self._persistent_client is not None:
                self._persistent_client.close()
            self._persistent_client = self.client_factory(settings)
            self._session = ExperimentalApiSession(settings=settings, auth_client=AuthApiClient(self._persistent_client), token_store=self.token_store)
            self._settings_key = key
            return self._persistent_client


def user_message_for_api_error(exc: Exception) -> str:
    if isinstance(exc, OfficialProposalStorageError):
        return str(exc)
    if isinstance(exc, ApiBusinessError):
        if exc.error_code == "PROPOSAL_VERSION_CONFLICT":
            return "Esta proposta foi alterada por outro usuario. Recarregue os dados mais recentes antes de salvar novamente."
        if exc.error_code == "PROPOSAL_NUMBER_ALREADY_EXISTS":
            return "Ja existe uma proposta com este numero no servidor."
        return exc.user_message
    if isinstance(exc, (ApiConnectionError, ApiTimeoutError)):
        return "Nao foi possivel salvar a proposta porque o servidor esta indisponivel. Os dados permanecem na tela para uma nova tentativa."
    if isinstance(exc, ApiAuthenticationError):
        return "Sua sessao da API expirou. Entre novamente na API e tente salvar outra vez."
    if isinstance(exc, ApiPermissionError):
        return "Seu usuario nao possui permissao na API para esta operacao."
    if isinstance(exc, ApiValidationError):
        return exc.user_message
    if isinstance(exc, ApiClientError):
        return exc.user_message
    return str(exc)


def _proposal_create_payload(data: dict[str, Any], import_metadata: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "proposal_number": str(data.get("proposta") or "").strip(),
        "customer_name": str(data.get("cliente") or "").strip(),
        "project_name": _optional(data.get("obra_site")),
        "purchase_order": _optional(data.get("pedido_compra")),
        "batch_reference": _optional(data.get("lote")),
        "proposal_date": _date_iso(data.get("data_entrada")),
        "deadline_date": _date_iso(data.get("prazo_entrega")),
        "source": _source(data, import_metadata),
        "warehouse_status": _warehouse_payload_status(data.get("necessita_almoxarifado")),
        "notes": _optional(data.get("observacoes_gerais")),
        "items": [_item_create_payload(item) for item in data.get("itens") or []],
    }


def _proposal_update_payload(data: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": int(current["version"]),
        "customer_name": str(data.get("cliente") or "").strip(),
        "project_name": _optional(data.get("obra_site")),
        "purchase_order": _optional(data.get("pedido_compra")),
        "batch_reference": _optional(data.get("lote")),
        "proposal_date": _date_iso(data.get("data_entrada")),
        "deadline_date": _date_iso(data.get("prazo_entrega")),
        "warehouse_status": _warehouse_payload_status(data.get("necessita_almoxarifado")),
        "notes": _optional(data.get("observacoes_gerais")),
    }


def _item_create_payload(item: dict[str, Any]) -> dict[str, Any]:
    quantity = _decimal(item.get("quantidade"), default="1")
    weight_text = _optional_known_decimal(item.get("peso"))
    weight = Decimal(weight_text) if weight_text is not None else None
    return {
        "item_number": str(item.get("numero_item") or "").strip(),
        "product_code": _optional(item.get("codigo_produto")),
        "description": str(item.get("descricao") or "").strip(),
        "quantity": str(quantity),
        "unit": "un",
        "unit_weight": str(weight) if weight is not None else None,
        "total_weight": str((quantity * weight).quantize(Decimal("0.0001"))) if weight is not None else None,
        "produce_internally": _flag_to_bool(item.get("produzir_internamente")),
        "non_production_reason": _optional(item.get("motivo_nao_produzir")),
        "requires_galvanization": _flag_to_bool(item.get("precisa_galvanizacao")),
        "notes": _optional(item.get("observacao_fluxo_item")),
    }


def _item_update_payload(item: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    payload = _item_create_payload(item)
    payload["version"] = int(current["version"])
    return payload


def _api_proposal_to_process(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "api_id": row.get("id"),
        "api_version": row.get("version"),
        "parent_proposal_id": row.get("parent_proposal_id"),
        "parent_legacy_id": row.get("parent_legacy_id"),
        "partial_number": row.get("partial_number"),
        "is_partial": bool(row.get("is_partial")),
        "proposta": row.get("proposal_number") or "",
        "cliente": row.get("customer_name") or "",
        "obra_site": row.get("project_name") or "",
        "pedido_compra": row.get("order_reference") or "",
        "lote": row.get("lot") or "",
        "data_entrada": _date_br(row.get("proposal_date")),
        "prazo_entrega": _date_br(row.get("deadline_date")),
        "peso": _sum_weight(row.get("items") or []),
        "observacoes_gerais": row.get("notes") or "",
        "necessita_almoxarifado": _warehouse_required_value(row.get("warehouse_status")),
        "status_geral": row.get("general_status") or row.get("current_status") or "",
        "status_producao": row.get("production_status") or "",
        "status_galvanizacao": row.get("galvanization_status") or "",
        "status_expedicao": row.get("shipping_status") or "",
        "status_almoxarifado": row.get("warehouse_status") or "",
        "is_cancelled": bool(row.get("is_cancelled")),
        "is_completed": bool(row.get("is_completed")),
        "cancelled_at": row.get("cancelled_at"),
        "cancelled_by": row.get("cancelled_by"),
        "cancellation_reason": row.get("cancellation_reason") or "",
        "tipo_processo": row.get("process_type") or "PRINCIPAL",
        "localizacao_atual": str(row.get("current_area") or "CONTROLE_GERAL").replace("_", " "),
        "status_localizacao": row.get("current_status") or row.get("general_status") or "",
    }


def _api_production_to_process(row: dict[str, Any]) -> dict[str, Any]:
    process = _api_proposal_to_process(row)
    progress = row.get("progress") or {}
    process.update(
        {
            "status_producao": row.get("production_status") or row.get("current_status") or "",
            "status_geral": row.get("general_status") or row.get("current_status") or "",
            "situacao_fluxo": row.get("flow_situation") or "",
            "tem_pendencia_producao": 1 if row.get("has_production_pending") else 0,
            "progresso_producao": progress,
            "peso": _decimal_text(progress.get("total_weight")) or process.get("peso") or "",
            "peso_produzido": _decimal_text(progress.get("produced_weight")),
            "saldo_pendente": _decimal_text(progress.get("pending_weight")),
            "quantidade_itens": progress.get("total_items", 0),
            "itens_produzidos": progress.get("produced_items", 0),
            "itens_pendentes": progress.get("pending_items", 0),
            "fluxo_indefinido": progress.get("undefined_flow_items", 0),
            "peso_ausente": progress.get("missing_weight_items", 0),
            "destino_previsto": progress.get("next_destination") or "",
            "data_entrada": _date_br(row.get("proposal_date")),
            "atualizado_em": _datetime_br(row.get("updated_at")),
        }
    )
    return process


def _api_partial_to_process(row: dict[str, Any]) -> dict[str, Any]:
    process = {
        "id": row.get("id"),
        "api_id": row.get("id"),
        "api_version": row.get("version"),
        "parent_proposal_id": row.get("parent_proposal_id"),
        "parent_legacy_id": row.get("parent_legacy_id"),
        "proposta": row.get("proposal_number") or "",
        "cliente": row.get("customer_name") or "",
        "obra_site": row.get("project_name") or "",
        "lote": row.get("lot") or "",
        "status_geral": row.get("current_status") or "",
        "status_producao": row.get("production_status") or "",
        "status_galvanizacao": row.get("galvanization_status") or "",
        "status_expedicao": row.get("shipping_status") or "",
        "status_almoxarifado": row.get("warehouse_status") or "",
        "status_fiscal": row.get("fiscal_status") or "",
        "situacao_fluxo": row.get("flow_situation") or row.get("partial_stage") or "",
        "tipo_processo": row.get("process_type") or ("PARCIAL" if row.get("partial_number") else "PRINCIPAL"),
        "numero_parcial": row.get("partial_number") or 0,
        "localizacao_atual": str(row.get("partial_stage") or row.get("current_area") or "PARCIAIS").replace("_", " "),
        "status_localizacao": _partial_current_status(row),
        "quantidade_itens": row.get("total_items", 0),
        "itens_produzidos": row.get("produced_items", 0),
        "itens_pendentes": row.get("production_pending_items", 0),
        "itens_galvanizacao_pendentes": row.get("galvanization_pending_items", 0),
        "itens_expedicao_pendentes": row.get("expedition_pending_items", 0),
        "itens_fiscais_pendentes": row.get("fiscal_pending_items", 0),
        "peso": _decimal_text(row.get("total_weight")),
        "peso_parcial": _partial_completed_weight(row),
        "saldo_pendente": _partial_pending_weight(row),
        "peso_produzido": _decimal_text(row.get("produced_weight")),
        "peso_pendente_producao": _decimal_text(row.get("production_pending_weight")),
        "peso_enviado_galv": _decimal_text(row.get("galvanization_sent_weight")),
        "peso_retornado_galv": _decimal_text(row.get("galvanization_returned_weight")),
        "peso_pendente_galv": _decimal_text(row.get("galvanization_pending_weight")),
        "peso_entregue": _decimal_text(row.get("expedition_delivered_weight")),
        "peso_pendente_expedicao": _decimal_text(row.get("expedition_pending_weight")),
        "peso_faturado": _decimal_text(row.get("fiscal_billed_weight")),
        "peso_pendente_fiscal": _decimal_text(row.get("fiscal_pending_weight")),
        "atualizado_em": _datetime_br(row.get("updated_at")),
    }
    return process


def _api_warehouse_to_process(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "api_id": row.get("id"),
        "api_version": row.get("version"),
        "proposta": row.get("proposal_number") or "",
        "cliente": row.get("customer_name") or "",
        "obra_site": row.get("project_name") or "",
        "lote": row.get("lot") or "",
        "status_geral": row.get("general_status") or row.get("current_status") or "",
        "status_expedicao": row.get("shipping_status") or "",
        "status_almoxarifado": row.get("warehouse_status") or "",
        "necessita_almoxarifado": row.get("warehouse_required") or "NAO_DEFINIDO",
        "localizacao_atual": "ALMOXARIFADO",
        "status_localizacao": row.get("warehouse_status") or "",
        "quantidade_itens": row.get("total_items", 0),
        "peso": _decimal_text(row.get("total_weight")),
        "atualizado_em": _datetime_br(row.get("updated_at")),
    }


def _warehouse_required_value(status: Any) -> str:
    text = str(status or "").strip().upper()
    if text == "SEM_PARAFUSOS":
        return "NAO"
    if text:
        return "SIM"
    return "NAO_DEFINIDO"


def _warehouse_payload_status(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text in {"SIM", "AGUARDANDO_CONFIRMACAO"}:
        return "AGUARDANDO_CONFIRMACAO"
    if text in {"NAO", "SEM_PARAFUSOS"}:
        return "SEM_PARAFUSOS"
    if text in {"EM_SEPARACAO", "SEPARADO", "ALMOXARIFADO_ENTREGUE", "ALMOXARIFADO_ENTREGUE_PARCIAL"}:
        return text
    return None


def _partial_current_status(row: dict[str, Any]) -> str:
    stage = str(row.get("partial_stage") or "").upper()
    if stage == "PRODUCAO":
        return row.get("production_status") or row.get("current_status") or ""
    if stage == "GALVANIZACAO":
        return row.get("galvanization_status") or row.get("current_status") or ""
    if stage == "EXPEDICAO":
        return row.get("shipping_status") or row.get("current_status") or ""
    if stage == "FISCAL":
        return row.get("fiscal_status") or row.get("current_status") or ""
    if stage == "ALMOXARIFADO":
        return row.get("warehouse_status") or row.get("current_status") or ""
    return row.get("current_status") or ""


def _partial_completed_weight(row: dict[str, Any]) -> str:
    for key in ("fiscal_billed_weight", "expedition_delivered_weight", "galvanization_returned_weight", "produced_weight"):
        value = _decimal(row.get(key), default="0")
        if value > 0:
            return _decimal_text(value)
    return "0.0000"


def _partial_pending_weight(row: dict[str, Any]) -> str:
    for key in ("fiscal_pending_weight", "expedition_pending_weight", "galvanization_pending_weight", "production_pending_weight"):
        value = _decimal(row.get(key), default="0")
        if value > 0:
            return _decimal_text(value)
    return "0.0000"


def _api_expedition_to_process(row: dict[str, Any]) -> dict[str, Any]:
    process = _api_proposal_to_process(row)
    status = row.get("shipping_status") or row.get("current_status") or ""
    process.update(
        {
            "parent_proposal_id": row.get("parent_proposal_id"),
            "numero_parcial": row.get("partial_number"),
            "status_expedicao": status,
            "status_geral": row.get("general_status") or "EM_EXPEDICAO",
            "localizacao_atual": "EXPEDICAO" if status != "ENTREGUE" else "FINALIZADO",
            "status_localizacao": status,
            "quantidade_itens": row.get("item_count", 0),
            "quantidade_disponivel": _decimal_text(row.get("available_quantity")),
            "quantidade_separada": _decimal_text(row.get("separated_quantity")),
            "quantidade_entregue": _decimal_text(row.get("delivered_quantity")),
            "saldo_pendente": _decimal_text(row.get("pending_quantity")),
            "origem_expedicao": ", ".join(row.get("origins") or []),
            "peso": _decimal_text(row.get("available_quantity")),
            "atualizado_em": _datetime_br(row.get("updated_at")),
        }
    )
    return process


def _api_item_to_process_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "api_id": item.get("id"),
        "api_version": item.get("version"),
        "numero_item": item.get("item_number") or "",
        "codigo_produto": item.get("product_code") or "",
        "descricao": item.get("description") or "",
        "quantidade": item.get("quantity") or "1",
        "peso": item.get("unit_weight") or "",
        "produzir_internamente": _api_flag(item.get("produce_internally")),
        "motivo_nao_produzir": item.get("non_production_reason") or "",
        "precisa_galvanizacao": _api_flag(item.get("requires_galvanization")),
        "observacao_fluxo_item": item.get("notes") or "",
        "processo_atual_id": item.get("proposal_id"),
        "produzido": item.get("produced", False),
        "galvanizado": item.get("galvanized", False),
        "entregue": item.get("delivered", False),
        "version": item.get("version"),
        "editavel": item.get("flow_editable", True),
        "motivo_bloqueio": item.get("flow_lock_reason"),
    }


def _api_production_item_row_to_process_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("item_id"),
        "api_id": row.get("item_id"),
        "api_version": row.get("version"),
        "numero_item": row.get("item_number") or "",
        "codigo_produto": row.get("product_code") or "",
        "descricao": row.get("description") or "",
        "quantidade": row.get("quantity") or "1",
        "peso": row.get("unit_weight") or "",
        "peso_total": _decimal_text(row.get("total_weight")),
        "produzir_internamente": _api_flag(row.get("produce_internally")),
        "precisa_galvanizacao": _api_flag(row.get("requires_galvanization")),
        "fluxo_definido": bool(row.get("flow_defined")),
        "observacao_fluxo_item": row.get("notes") or "",
        "produzido": bool(row.get("produced")),
        "processo_atual_id": row.get("proposal_id"),
        "api_proposal_id": row.get("proposal_id"),
        "api_proposal_version": row.get("proposal_version"),
        "proposta": row.get("proposal_number") or "",
        "cliente": row.get("customer_name") or "",
        "obra_site": row.get("project_name") or "",
        "lote": row.get("lot") or "",
        "status_producao": row.get("proposal_status") or "",
        "status_producao_item": "FLUXO_INDEFINIDO" if not row.get("flow_defined") else (row.get("proposal_status") or ""),
    }


def _api_galvanization_item_row_to_process_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("item_id"),
        "api_id": row.get("item_id"),
        "api_version": row.get("version"),
        "numero_item": row.get("item_number") or "",
        "codigo_produto": row.get("product_code") or "",
        "descricao": row.get("description") or "",
        "quantidade": row.get("quantity") or "0",
        "quantidade_disponivel": row.get("available_quantity") or "0",
        "quantidade_em_galvanizacao": row.get("sent_quantity") or "0",
        "peso_unitario": row.get("unit_weight") or "",
        "peso": _decimal_text(row.get("available_weight")),
        "peso_em_galvanizacao": _decimal_text(row.get("sent_weight")),
        "situacao": row.get("situation") or "",
        "status_galvanizacao": row.get("situation") or "",
        "processo_atual_id": row.get("proposal_id"),
        "api_proposal_id": row.get("proposal_id"),
        "proposta": row.get("proposal_number") or "",
        "cliente": row.get("customer_name") or "",
        "obra_site": row.get("project_name") or "",
        "lote": row.get("lot") or "",
    }


def _api_expedition_item_to_process_item(item: dict[str, Any]) -> dict[str, Any]:
    separated_balance = _decimal(item.get("separated_quantity"), default="0") - _decimal(item.get("delivered_quantity"), default="0")
    return {
        "id": item.get("proposal_item_id"),
        "api_id": item.get("proposal_item_id"),
        "api_expedition_item_id": item.get("id"),
        "api_expedition_version": item.get("version"),
        "api_version": item.get("version"),
        "numero_item": item.get("item_number") or "",
        "codigo_produto": item.get("product_code") or "",
        "descricao": item.get("description") or "",
        "quantidade": item.get("available_quantity") or "0",
        "quantidade_disponivel": item.get("available_quantity") or "0",
        "quantidade_separada": item.get("separated_quantity") or "0",
        "quantidade_entregue": item.get("delivered_quantity") or "0",
        "quantidade_remanejada": item.get("remanaged_quantity") or "0",
        "saldo_pendente": item.get("pending_quantity") or "0",
        "saldo_separado": _decimal_text(separated_balance),
        "peso": item.get("unit_weight") or "",
        "peso_total": item.get("total_weight") or "",
        "origem_expedicao": item.get("origin") or "",
        "status_expedicao": item.get("status") or "",
        "processo_atual_id": item.get("proposal_id"),
        "produzido": 1,
        "entregue": 1 if item.get("status") == "ENTREGUE" else 0,
    }


def _expedition_item_payload(item_ids: list[int] | None) -> list[dict[str, Any]] | None:
    if not item_ids:
        return None
    # item_ids here are ProposalItem.id (see _api_expedition_item_to_process_item's "id"),
    # not ExpeditionItem.id, so they must be sent as proposal_item_id.
    return [{"proposal_item_id": int(item_id)} for item_id in item_ids]


def _expedition_remanagement_item_payload(item_ids: list[int] | None, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not item_ids:
        return []
    items_by_proposal_item_id = {int(item.get("proposal_item_id") or 0): item for item in items}
    payload = []
    for item_id in item_ids:
        proposal_item_id = int(item_id)
        item = items_by_proposal_item_id.get(proposal_item_id) or {}
        quantity = item.get("pending_quantity") or item.get("available_quantity") or None
        row = {"proposal_item_id": proposal_item_id}
        if quantity not in (None, ""):
            row["quantity"] = str(quantity)
        payload.append(row)
    return payload


def _api_fiscal_record_to_legacy(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "fiscal_processo_id": row.get("id"),
        "fiscal_processo_ids": row.get("fiscal_processo_ids") or [row.get("id")],
        "processo_id": row.get("proposal_id"),
        "parent_proposal_id": row.get("parent_proposal_id"),
        "numero_parcial": row.get("partial_number"),
        "proposta": row.get("proposal_number") or "",
        "cliente": row.get("customer_name") or "",
        "pedido_compra": "",
        "obra_site": row.get("project_name") or "",
        "lote": row.get("lot") or "",
        "status_fiscal": row.get("status_fiscal") or "",
        "situacao_fiscal": row.get("fiscal_situation") or "",
        "data_entrada_fiscal": _date_br(row.get("entry_date")),
        "data_ultima_emissao": _datetime_br(row.get("last_emission_at")),
        "data_retirada_nf": _datetime_br(row.get("invoice_withdrawn_at")),
        "status_expedicao": row.get("shipping_status") or "",
        "quantidade_itens": row.get("item_count", 0),
        "itens_pendentes": row.get("pending_items", 0),
        "itens_faturados": row.get("billed_items", 0),
        "peso_total": _decimal_text(row.get("total_weight")),
        "peso_faturado": _decimal_text(row.get("billed_weight")),
        "peso_pendente": _decimal_text(row.get("pending_weight")),
        "itens_com_peso": int(row.get("weight_known_items") or 0),
        "itens_total_peso": int(row.get("weight_total_items") or row.get("item_count") or 0),
        "cobertura_peso_completa": bool(row.get("weight_complete")),
        "mais_7_dias_sem_emissao": 1 if row.get("older_than_7_days") else 0,
        "pendencia_critica": 1 if row.get("critical_pending") else 0,
        "api_version": row.get("version"),
        "version": row.get("version"),
    }


def _api_fiscal_item_to_legacy(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "fiscal_processo_id": row.get("fiscal_record_id"),
        "processo_id": row.get("proposal_id"),
        "item_id": row.get("proposal_item_id"),
        "numero_item": row.get("item_number") or "",
        "codigo_produto": row.get("product_code") or "",
        "descricao": row.get("description") or "",
        "quantidade_total": row.get("total_quantity"),
        "quantidade_faturada": row.get("billed_quantity"),
        "quantidade_pendente": row.get("pending_quantity"),
        "peso_total": row.get("total_weight"),
        "peso_faturado": row.get("billed_weight"),
        "peso_pendente": row.get("pending_weight"),
        "status_item_fiscal": row.get("status") or "",
        "api_version": row.get("version"),
        "version": row.get("version"),
    }


def _api_fiscal_invoice_to_legacy(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "fiscal_processo_id": row.get("fiscal_record_id"),
        "processo_id": row.get("proposal_id"),
        "numero_controle": row.get("invoice_number") or "",
        "serie": row.get("series") or "",
        "chave_acesso": row.get("access_key") or "",
        "tipo_emissao": row.get("emission_type") or "",
        "data_emissao": _datetime_br(row.get("issued_at")),
        "usuario": row.get("source") or "",
        "observacao": row.get("observation") or "",
        "quantidade_itens": row.get("item_count", 0),
        "quantidade_emitida": row.get("quantity"),
        "peso_emitido": row.get("weight"),
        "itens": row.get("items") or [],
    }


def _api_fiscal_event_to_legacy(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "tipo_movimento": row.get("event_type") or "",
        "status_anterior": row.get("from_status") or "",
        "status_novo": row.get("to_status") or "",
        "usuario": row.get("actor_user_id") or "",
        "data_hora": _datetime_br(row.get("created_at")),
        "observacao": ((row.get("metadata") or {}).get("observation") or (row.get("metadata") or {}).get("reason") or ""),
    }


def _filter_fiscal_rows(rows: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
    entry_date = str(filters.get("data_entrada_fiscal") or "").strip()
    critical = str(filters.get("pendencia_critica") or "").strip()
    older = str(filters.get("mais_7_dias_sem_emissao") or "").strip()
    exclude_withdrawn = str(filters.get("excluir_retiradas") or "").strip()
    result = rows
    if entry_date:
        normalized = _date_br(entry_date)
        if normalized:
            result = [row for row in result if str(row.get("data_entrada_fiscal") or "") == normalized]
    if critical:
        result = [row for row in result if int(row.get("pendencia_critica") or 0) == int(critical)]
    if older:
        result = [row for row in result if int(row.get("mais_7_dias_sem_emissao") or 0) == int(older)]
    if exclude_withdrawn:
        result = [row for row in result if str(row.get("situacao_fiscal") or "").upper() != "NF_RETIRADA_CLIENTE"]
    return result


def _api_security_event_to_audit(row: dict[str, Any]) -> dict[str, Any]:
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    actor = row.get("actor_user_id")
    target = row.get("target_user_id")
    return {
        "id": row.get("id"),
        "acao": row.get("event_type") or "",
        "entidade": details.get("entity") or details.get("path") or "API",
        "entidade_id": target or details.get("entity_id") or "",
        "campo": details.get("field") or "",
        "valor_anterior": details.get("before") or "",
        "valor_novo": details.get("after") or "",
        "data_hora": _datetime_br(row.get("created_at")),
        "usuario": f"Usuario {actor}" if actor else "-",
        "sucesso": "Sim" if row.get("success") else "Nao",
        "request_id": row.get("request_id") or "",
    }


def _api_history_to_legacy(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "proposta": row.get("proposal_number") or "",
        "processo_id": row.get("proposal_id"),
        "area": _history_area_legacy(row.get("area") or _history_area_from_source(row.get("source") or "")),
        "status_anterior": row.get("from_status") or "",
        "status_novo": row.get("to_status") or row.get("event_type") or "",
        "data_hora": _datetime_br(row.get("created_at")),
        "usuario": row.get("actor_name") or (f"Usuario {row.get('actor_user_id')}" if row.get("actor_user_id") else "-"),
        "computador": "API",
        "observacao": row.get("observation") or row.get("event_type") or "",
        "origem": row.get("source") or "",
        "request_id": row.get("request_id") or "",
    }


def _history_area_from_source(source: str) -> str:
    return {
        "proposal": "CONTROLE GERAL",
        "expedition": "EXPEDICAO",
        "galvanization": "GALVANIZACAO",
        "fiscal": "FISCAL",
    }.get(str(source or "").lower(), "")


def _history_area_legacy(area: Any) -> str:
    text = str(area or "").strip().upper()
    return {
        "CONTROLE_GERAL": "CONTROLE GERAL",
        "PRODUCAO": "PRODUCAO",
        "GALVANIZACAO": "GALVANIZACAO",
        "EXPEDICAO": "EXPEDICAO",
        "FISCAL": "FISCAL",
        "FINALIZADO": "FINALIZADO",
    }.get(text, text.replace("_", " "))


def _api_user_to_legacy(row: dict[str, Any]) -> dict[str, Any]:
    roles = row.get("roles") or []
    role_names = [str(item.get("name") or item.get("code") or "") for item in roles if isinstance(item, dict)]
    is_admin = bool(row.get("is_superuser") or any(name.lower() == "admin" for name in role_names))
    permissions = _api_permissions_to_legacy(row.get("permissions") or [], is_admin)
    return {
        "id": row.get("id"),
        "nome": row.get("display_name") or row.get("username") or "",
        "login": row.get("username") or "",
        "perfil": "admin" if is_admin else "usuario",
        "perfil_label": "Administrador" if is_admin else "Usuario API",
        "ativo": 1 if row.get("active") else 0,
        "ativo_label": "Sim" if row.get("active") else "Nao",
        "areas_acesso": ", ".join(role_names),
        "areas_label": ", ".join(role_names) or "Permissoes pela API",
        "permissions": permissions,
    }


def legacy_permissions_to_api_codes(permissions: dict[str, str], *, is_admin: bool = False) -> list[str]:
    if is_admin:
        return []
    codes: set[str] = set()
    for area_key, level in permissions.items():
        normalized_level = str(level or "NONE").upper()
        if normalized_level in {"VIEW", "EDIT"}:
            codes.update(AREA_VIEW_PERMISSIONS.get(area_key, set()))
        if normalized_level == "EDIT":
            codes.update(AREA_EDIT_PERMISSIONS.get(area_key, set()))
    return sorted(codes)


def api_permission_level(codes: set[str], area_key: str, *, is_admin: bool = False) -> str:
    if is_admin or "*" in codes:
        return "EDIT"
    view_codes = AREA_VIEW_PERMISSIONS.get(area_key, set())
    edit_codes = AREA_EDIT_PERMISSIONS.get(area_key, set())
    if edit_codes and codes.intersection(edit_codes):
        return "EDIT"
    if view_codes and codes.intersection(view_codes):
        return "VIEW"
    if area_key in {"dashboard", "executive_dashboard"} and "proposals.view" in codes:
        return "VIEW"
    if area_key in {"partials", "warehouse"} and codes.intersection({"proposals.view", "proposal_items.view"}):
        return "VIEW"
    if area_key == "operational_reports" and codes.intersection({"proposals.view", "fiscal.view"}):
        return "VIEW"
    return "NONE"


def _api_permissions_to_legacy(codes: list[str], is_admin: bool) -> dict[str, str]:
    area_keys = [
        "dashboard",
        "executive_dashboard",
        "control_general",
        "production",
        "galvanization",
        "expedition",
        "fiscal",
        "partials",
        "warehouse",
        "operational_reports",
        "history",
        "settings",
        "users_permissions",
    ]
    if is_admin or "*" in codes:
        return {key: "EDIT" for key in area_keys}
    code_set = set(codes)
    return {key: api_permission_level(code_set, key, is_admin=False) for key in area_keys}


def _api_galvanization_load_to_legacy(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "codigo": row.get("code") or row.get("id"),
        "status": row.get("status") or "",
        "motorista": row.get("driver_name") or "",
        "peso_maximo": _decimal_text(row.get("max_weight")),
        "peso_informado_carga": _decimal_text(row.get("load_weight")),
        "origem_peso_carga": row.get("load_weight_source") or "",
        "peso_carga_atualizado_em": _datetime_br(row.get("load_weight_updated_at")),
        "peso_total": _decimal_text(row.get("total_weight")),
        "peso_conhecido_itens": _decimal_text(row.get("known_items_weight") if "known_items_weight" in row else row.get("total_weight")),
        "itens_com_peso": int(row.get("weight_known_items") or 0),
        "itens_total_peso": int(row.get("weight_total_items") or row.get("item_count") or 0),
        "cobertura_peso_completa": bool(row.get("weight_complete")),
        "item_count": row.get("item_count", 0),
        "proposal_count": row.get("proposal_count", 0),
        "data_prevista_retorno": _date_br(row.get("expected_return_date")),
        "data_envio": _datetime_br(row.get("sent_at")),
        "data_retorno": _datetime_br(row.get("returned_at")) or "",
        "encerrado_em": _datetime_br(row.get("closed_at")) or "",
        "criado_em": _datetime_br(row.get("created_at")),
        "atualizado_em": _datetime_br(row.get("updated_at")),
        "criado_por_id": row.get("created_by_user_id"),
        "criado_por": row.get("created_by_name") or "",
        "atualizado_por_id": row.get("updated_by_user_id"),
        "atualizado_por": row.get("updated_by_name") or "",
        "observacao": row.get("notes") or "",
        "api_version": row.get("version"),
        "version": row.get("version"),
    }


def _api_galvanization_proposal_to_legacy(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "carga_item_id": row.get("proposal_id"),
        "processo_id": row.get("proposal_id"),
        "parent_proposal_id": row.get("parent_proposal_id"),
        "numero_parcial": row.get("partial_number"),
        "proposta": row.get("proposal_number") or "",
        "cliente": row.get("customer_name") or "",
        "obra_site": row.get("project_name") or "",
        "peso_total_proposta": _decimal_text(row.get("sent_weight")),
        "peso_enviado": _decimal_text(row.get("sent_weight")),
        "peso_retornado": _decimal_text(row.get("returned_weight")),
        "peso_pendente": _decimal_text(row.get("pending_weight")),
        "itens_pendentes": row.get("pending_item_count", 0),
        "parcial": 1 if _decimal(row.get("pending_weight"), default="0") > 0 and _decimal(row.get("returned_weight"), default="0") > 0 else 0,
        "status_retorno": row.get("status") or "",
    }


def _api_galvanization_item_to_legacy(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "detail_id": row.get("id"),
        "processo_id": row.get("proposal_id"),
        "proposta_item_id": row.get("proposal_item_id"),
        "proposta": row.get("proposal_number") or "",
        "cliente": row.get("customer_name") or "",
        "numero_item": row.get("item_number") or "",
        "codigo_produto": row.get("product_code") or "",
        "descricao": row.get("description") or "",
        "quantidade": row.get("sent_quantity"),
        "quantidade_enviada": row.get("sent_quantity"),
        "quantidade_retornada": row.get("returned_quantity"),
        "quantidade_pendente": row.get("pending_quantity"),
        "peso": row.get("unit_weight"),
        "peso_unitario": row.get("unit_weight"),
        "peso_enviado": row.get("sent_weight"),
        "peso_retornado": row.get("returned_weight"),
        "peso_pendente": row.get("pending_weight"),
        "status_retorno": row.get("status") or "",
        "version": row.get("version"),
        "produzido": 1,
        "galvanizado": 1 if row.get("status") == "RETORNADO" else 0,
        "precisa_galvanizacao": "sim",
    }


def _api_galvanization_return_to_legacy(row: dict[str, Any], *, number: int) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "numero_retorno": number,
        "request_id": row.get("request_id") or "",
        "data": _datetime_br(row.get("occurred_at")),
        "usuario_id": row.get("actor_user_id"),
        "usuario": row.get("actor_name") or "",
        "status_anterior": row.get("from_status") or "",
        "status_novo": row.get("to_status") or "",
        "tipo_retorno": row.get("return_type") or "",
        "observacao": row.get("observation") or "",
        "peso_retornado": row.get("returned_weight"),
        "itens_com_peso": int(row.get("weight_known_items") or 0),
        "itens_total_peso": int(row.get("weight_total_items") or 0),
        "itens": [
            {
                "evento_id": item.get("event_id"),
                "carga_item_id": item.get("load_item_id"),
                "processo_id": item.get("proposal_id"),
                "proposta": item.get("proposal_number") or "",
                "proposta_item_id": item.get("proposal_item_id"),
                "numero_item": item.get("item_number") or "",
                "codigo_produto": item.get("product_code") or "",
                "descricao": item.get("description") or "",
                "quantidade_retornada": item.get("returned_quantity"),
                "peso_unitario": item.get("unit_weight"),
                "peso_retornado": item.get("returned_weight"),
            }
            for item in row.get("items", [])
        ],
    }


def _api_galvanization_history_to_legacy(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "evento": row.get("event_type") or "",
        "carga_item_id": row.get("load_item_id"),
        "processo_id": row.get("proposal_id"),
        "proposta_item_id": row.get("proposal_item_id"),
        "usuario_id": row.get("actor_user_id"),
        "usuario": row.get("actor_name") or "",
        "request_id": row.get("request_id") or "",
        "status_anterior": row.get("from_status") or "",
        "status_novo": row.get("to_status") or "",
        "metadata": row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
        "data": _datetime_br(row.get("created_at")),
    }


def _source(data: dict[str, Any], import_metadata: dict[str, Any] | None) -> str:
    if import_metadata and str(import_metadata.get("origem") or "").upper() == "NOMUS_PDF":
        return "NOMUS_PDF"
    source = str(data.get("_import_source") or "").upper()
    return "NOMUS_API" if source == "NOMUS_API" else "MANUAL"


def _optional(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_decimal(value: Any) -> str | None:
    text = str(value or "").strip().replace(",", ".")
    return text or None


def _optional_known_decimal(value: Any) -> str | None:
    text = _optional_decimal(value)
    if text is None:
        return None
    try:
        parsed = Decimal(text).quantize(Decimal("0.0001"))
    except InvalidOperation as exc:
        raise OfficialProposalStorageError("Informe um peso numerico valido.") from exc
    # Zero enviado por Desktops antigos e tratado como campo limpo. Negativos
    # continuam seguindo para a validacao oficial da API.
    if parsed == Decimal("0"):
        return None
    return str(parsed)


def _decimal(value: Any, *, default: str) -> Decimal:
    text = str(value if value not in (None, "") else default).replace(",", ".")
    try:
        return Decimal(text).quantize(Decimal("0.0001"))
    except InvalidOperation:
        return Decimal(default).quantize(Decimal("0.0001"))


def _flag_to_bool(value: Any) -> bool | None:
    text = str(value or "").strip().lower()
    if text in {"sim", "true", "1"}:
        return True
    if text in {"nao", "não", "false", "0"}:
        return False
    return None


def _api_flag(value: Any) -> str:
    text = str(value or "").upper()
    if text == "SIM":
        return "sim"
    if text == "NAO":
        return "nao"
    return "indefinido"


def _date_iso(value: Any) -> str | None:
    text = str(value or "").strip()
    for pattern in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            pass
    return None


def _date_br(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], pattern).strftime("%d/%m/%Y")
        except ValueError:
            pass
    return text


def _sum_weight(items: list[dict[str, Any]]) -> str:
    total = Decimal("0")
    for item in items:
        total += _decimal(item.get("total_weight"), default="0")
    return f"{total.normalize():f}" if total else ""


def _decimal_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    return f"{_decimal(value, default='0').normalize():f}"


def _datetime_br(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        return text
