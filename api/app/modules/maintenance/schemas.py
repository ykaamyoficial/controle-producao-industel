from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from api.app.maintenance.models import MaintenanceReasonCode


class ScheduleMaintenanceRequest(BaseModel):
    reason_code: MaintenanceReasonCode
    message: str = Field(..., min_length=1, max_length=1000)
    scheduled_start_at: datetime
    expected_end_at: datetime | None = None
    maintenance_id: str | None = Field(default=None, max_length=80)


class BeginDrainingRequest(BaseModel):
    reason_code: MaintenanceReasonCode
    message: str = Field(..., min_length=1, max_length=1000)
    expected_end_at: datetime | None = None
    maintenance_id: str | None = Field(default=None, max_length=80)


class ActivateMaintenanceRequest(BaseModel):
    reason_code: MaintenanceReasonCode
    message: str = Field(..., min_length=1, max_length=1000)
    expected_end_at: datetime | None = None
    maintenance_id: str | None = Field(default=None, max_length=80)


class BeginRecoveryRequest(BaseModel):
    message: str | None = Field(default=None, max_length=1000)


class MaintenanceAdminStateResponse(BaseModel):
    """Estado completo incluindo campos administrativos (activated_by,
    policy_revision) -- nunca exposto no GET publico /system/maintenance."""

    model_config = ConfigDict(extra="forbid")

    state: str
    maintenance_id: str
    reason_code: str
    message: str
    scheduled_start_at: str | None = None
    started_at: str | None = None
    expected_end_at: str | None = None
    activated_by: str | None = None
    policy_revision: int
    updated_at: str
