from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class UpdateAuditEventOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_type: str
    occurred_at: str
    severity: str
    actor_type: str
    actor_id: str | None
    component: str
    result: str
    correlation_id: str | None
    release_id: str | None
    deployment_id: str | None
    maintenance_id: str | None
    installation_id: str | None
    version: str | None
    channel: str | None
    message: str
    metadata: dict
    created_at: str | None


class UpdateAuditEventList(BaseModel):
    items: list[UpdateAuditEventOut]
    total: int
    limit: int
    offset: int


class InstallationUpdateStatusOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    installation_id: str
    machine_name: str | None
    channel: str
    current_version: str | None
    last_seen_at: str | None
    last_update_version: str | None
    last_update_result: str | None
    last_update_at: str | None
    compatibility_state: str | None
