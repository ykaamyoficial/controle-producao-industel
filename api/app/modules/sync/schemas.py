from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SyncHead(BaseModel):
    seq: int
    min_seq_available: int
    schema_version: int
    entities: list[str]


class SyncChange(BaseModel):
    seq: int
    entity: str
    id: int
    op: str
    row: dict[str, Any] | None = None


class SyncChangesResponse(BaseModel):
    changes: list[SyncChange]
    next_seq: int
    has_more: bool
    resync_required: bool
    schema_version: int


class SyncSnapshotResponse(BaseModel):
    entity: str
    rows: list[dict[str, Any]]
    next_after_id: int
    has_more: bool
    schema_version: int
