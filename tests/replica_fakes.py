from __future__ import annotations

import copy
from typing import Any
from urllib.parse import parse_qs, urlsplit


class FakeSyncServer:
    """Imita /api/v1/sync/* (api/app/modules/sync/service.py) em memoria."""

    def __init__(self, entities=("proposals", "proposal_items")):
        self.entities = list(entities)
        self.schema_version = 1
        self.tables: dict[str, dict[int, dict[str, Any]]] = {entity: {} for entity in self.entities}
        self.log: list[tuple[int, str, int, str]] = []
        self.seq = 0
        self.calls: list[str] = []
        self.fail_next: Exception | None = None
        # Chamado depois de cada pagina de snapshot (simula escrita durante a carga inicial).
        self.on_snapshot_page = None

    # ---- escrita do "servidor" ---------------------------------------------
    def upsert(self, entity: str, row_id: int, **fields) -> None:
        self.tables.setdefault(entity, {})[row_id] = {"id": row_id, **fields}
        self._event(entity, row_id, "upsert")

    def delete(self, entity: str, row_id: int) -> None:
        self.tables.get(entity, {}).pop(row_id, None)
        self._event(entity, row_id, "delete")

    def _event(self, entity: str, row_id: int, op: str) -> None:
        self.seq += 1
        self.log.append((self.seq, entity, row_id, op))

    def purge_log_up_to(self, seq: int) -> None:
        self.log = [event for event in self.log if event[0] > seq]

    # ---- transporte ---------------------------------------------------------
    def get_json(self, path: str) -> Any:
        self.calls.append(path)
        if self.fail_next is not None:
            error, self.fail_next = self.fail_next, None
            raise error
        parts = urlsplit(path)
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        if parts.path.endswith("/sync/head"):
            return self._head()
        if parts.path.endswith("/sync/changes"):
            return self._changes(int(query.get("since", 0)), int(query.get("limit", 500)))
        if parts.path.endswith("/sync/snapshot"):
            return self._snapshot(query["entity"], int(query.get("after_id", 0)), int(query.get("limit", 1000)))
        raise AssertionError(f"rota inesperada: {path}")

    def _head(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "min_seq_available": self.log[0][0] if self.log else 0,
            "schema_version": self.schema_version,
            "entities": list(self.entities),
        }

    def _changes(self, since: int, limit: int) -> dict[str, Any]:
        head = self.seq
        minimum = self.log[0][0] if self.log else 0
        if (minimum and since + 1 < minimum) or since > head:
            return {"changes": [], "next_seq": since, "has_more": False, "resync_required": True, "schema_version": self.schema_version}
        events = [event for event in self.log if since < event[0] <= head and event[1] in self.entities]
        has_more = len(events) > limit
        events = events[:limit]
        latest: dict[tuple[str, int], tuple[int, str, int, str]] = {}
        for event in events:
            latest.pop((event[1], event[2]), None)
            latest[(event[1], event[2])] = event
        changes = []
        for seq, entity, row_id, op in latest.values():
            row = copy.deepcopy(self.tables.get(entity, {}).get(row_id)) if op == "upsert" else None
            changes.append({"seq": seq, "entity": entity, "id": row_id, "op": "upsert" if row is not None else "delete", "row": row})
        return {
            "changes": changes,
            "next_seq": events[-1][0] if has_more else head,
            "has_more": has_more,
            "resync_required": False,
            "schema_version": self.schema_version,
        }

    def _snapshot(self, entity: str, after_id: int, limit: int) -> dict[str, Any]:
        if entity not in self.entities:
            raise PermissionError(entity)
        ids = sorted(row_id for row_id in self.tables.get(entity, {}) if row_id > after_id)
        page = ids[:limit]
        response = {
            "entity": entity,
            "rows": [copy.deepcopy(self.tables[entity][row_id]) for row_id in page],
            "next_after_id": page[-1] if page else after_id,
            "has_more": len(ids) > limit,
            "schema_version": self.schema_version,
        }
        if self.on_snapshot_page is not None:
            self.on_snapshot_page(entity)
        return response

    def expected_state(self) -> dict[str, dict[int, dict[str, Any]]]:
        return {entity: copy.deepcopy(self.tables.get(entity, {})) for entity in self.entities}
