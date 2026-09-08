from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from api.app.channels.models import Channel


class ClientInstallationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    installation_id: str
    machine_name: str | None
    os_version: str | None
    channel: str
    current_desktop_version: str | None
    last_seen_at: str | None
    assigned_by: str | None
    assigned_at: str | None
    created_at: str | None
    updated_at: str | None


class ClientInstallationList(BaseModel):
    items: list[ClientInstallationOut]


class AssignChannelRequest(BaseModel):
    channel: Channel


class ReleaseChannelStateOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    channel: str
    status: str
    manifest_sha256: str
    artifact_sha256: str
    policy_revision: int
    created_at: str
    updated_at: str
    pilot_authorized_at: str | None
    promoted_at: str | None
    promoted_by: str | None
    actor: str | None
    note: str | None


class ReleaseChannelStateList(BaseModel):
    items: list[ReleaseChannelStateOut]


class AuthorizePilotRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class PilotActionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class RevokeChannelReleaseRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class ApprovePilotRequest(BaseModel):
    min_pilot_clients_updated: int = Field(default=1, ge=1)
    observation_minutes: int = Field(default=60, ge=0)
    note: str | None = Field(default=None, max_length=1000)


class PilotGateEvaluationOut(BaseModel):
    eligible: bool
    clients_updated: int
    clients_required: int
    critical_update_failures: int
    start_failures: int
    incompatible_after_update: int
    observation_elapsed_minutes: float
    observation_required_minutes: int
    reasons: list[str]


class PilotClientReportRequest(BaseModel):
    installation_id: str = Field(..., min_length=1, max_length=36)
    release_version: str = Field(..., min_length=1, max_length=32)
    update_result: str = Field(..., min_length=1, max_length=20)
    app_start_result: str = Field(..., min_length=1, max_length=20)
    compatibility_result: str = Field(..., min_length=1, max_length=20)
    error_code: str | None = Field(default=None, max_length=80)


class PilotClientReportOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    installation_id: str
    release_version: str
    update_result: str
    app_start_result: str
    compatibility_result: str
    error_code: str | None
    reported_at: str | None
