from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class UpdateDiscoveryResponse(BaseModel):
    available: bool
    version: str | None = None
    manifest_url: str | None = None
    package_url: str | None = None
    release_state: str | None = None


class SyncReleaseRequest(BaseModel):
    manifest_path: str = Field(..., min_length=1)
    package_path: str = Field(..., min_length=1)
    source: str = Field(default="manual", min_length=1)


class RevokeReleaseRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class ReleaseAdminOut(BaseModel):
    version: str
    state: str
    channel: str
    minimum_server_version: str
    api_contract_version: str
    artifact: dict[str, Any] | None
    source: str
    created_at: datetime
    updated_at: datetime
    authorized_at: datetime | None
    revoked_at: datetime | None
    revoked_reason: str | None
    failed_reason: str | None


class ReleaseAdminList(BaseModel):
    items: list[ReleaseAdminOut]


class DesktopUpdatePolicyOut(BaseModel):
    enforcement: str
    authorized_release_version: str | None
    grace_until: str | None
    message: str
    policy_revision: int
    updated_at: str | None


class DesktopUpdatePolicyUpdateRequest(BaseModel):
    enforcement: str = Field(..., min_length=1)
    authorized_release_version: str | None = None
    grace_until: str | None = None
    message: str = Field(default="", max_length=1000)
