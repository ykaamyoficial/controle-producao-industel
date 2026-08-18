from __future__ import annotations

from typing import Any

from app.integrations.api.planned_loads_client import PlannedLoadsApiClient
from app.services.api_proposal_storage import OfficialProposalApiStorage


class ApiPlannedLoadStorage:
    """Storage dedicada ao modulo Carga Planejada (FASE_PL5).

    O backend `planned_loads` e um modulo separado de `proposals` (router +
    service + schemas proprios), por isso esta storage tambem e uma classe
    separada de `OfficialProposalApiStorage` -- nao mistura os dois. Ainda
    assim a sessao HTTP (login/refresh/retry) do desktop e uma unica por
    processo, entao esta classe reaproveita o `_client()` ja gerido por
    `OfficialProposalApiStorage` (mesmo padrao que `_chat_client()` usa
    internamente) em vez de duplicar login/refresh aqui.

    Sem `_cached_read`/TTL nenhum aqui de proposito: disponibilidade/saldo de
    planejamento (FASE_PL2) e sempre lida ao vivo do servidor, cachear no
    desktop reintroduziria dado desatualizado.
    """

    def __init__(self, proposal_storage: OfficialProposalApiStorage):
        self._proposal_storage = proposal_storage

    def _client(self):
        client, _proposals, token = self._proposal_storage._client()
        return client, PlannedLoadsApiClient(client), token

    def list_planned_loads(self, **filters) -> dict[str, Any]:
        client, planned_loads, token = self._client()
        try:
            return planned_loads.list_planned_loads(token, **filters)
        finally:
            client.close()

    def get_planned_load(self, planned_load_id: int) -> dict[str, Any]:
        client, planned_loads, token = self._client()
        try:
            return planned_loads.get_planned_load(token, planned_load_id)
        finally:
            client.close()

    def create_planned_load(self, payload: dict[str, Any]) -> dict[str, Any]:
        client, planned_loads, token = self._client()
        try:
            return planned_loads.create_planned_load(token, payload)
        finally:
            client.close()

    def update_planned_load(self, planned_load_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        client, planned_loads, token = self._client()
        try:
            return planned_loads.update_planned_load(token, planned_load_id, payload)
        finally:
            client.close()

    def add_planned_load_items(self, planned_load_id: int, items: list[dict[str, Any]]) -> dict[str, Any]:
        client, planned_loads, token = self._client()
        try:
            return planned_loads.add_planned_load_items(token, planned_load_id, {"items": items})
        finally:
            client.close()

    def update_planned_load_item(self, planned_load_id: int, item_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        client, planned_loads, token = self._client()
        try:
            return planned_loads.update_planned_load_item(token, planned_load_id, item_id, payload)
        finally:
            client.close()

    def delete_planned_load_item(self, planned_load_id: int, item_id: int, version: int) -> dict[str, Any]:
        client, planned_loads, token = self._client()
        try:
            return planned_loads.delete_planned_load_item(token, planned_load_id, item_id, version)
        finally:
            client.close()

    def cancel_planned_load(self, planned_load_id: int, version: int) -> dict[str, Any]:
        client, planned_loads, token = self._client()
        try:
            return planned_loads.cancel_planned_load(token, planned_load_id, version)
        finally:
            client.close()

    def build_planned_load(self, planned_load_id: int) -> dict[str, Any]:
        client, planned_loads, token = self._client()
        try:
            return planned_loads.build_planned_load(token, planned_load_id)
        finally:
            client.close()

    def mark_planned_load_converted(self, planned_load_id: int, version: int, real_load_id: int) -> dict[str, Any]:
        client, planned_loads, token = self._client()
        try:
            return planned_loads.mark_planned_load_converted(token, planned_load_id, version, real_load_id)
        finally:
            client.close()
