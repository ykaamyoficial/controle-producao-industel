from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LivenessResponse(BaseModel):
    """GET /health/live -- contrato minimo do prompt (Secao 8): nunca toca banco."""

    model_config = ConfigDict(extra="forbid")

    status: str
    server_version: str


class HealthCheckResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: str
    critical: bool
    duration_ms: int
    message: str
    error_code: str | None = None


class HealthReportResponse(BaseModel):
    """GET /health/ready -- Secao 10."""

    model_config = ConfigDict(extra="forbid")

    overall_status: str
    checked_at_utc: str
    server_version: str
    api_contract_version: str
    database_revision: str | None = None
    commit_sha: str | None = None
    build_time_utc: str | None = None
    checks: list[HealthCheckResultResponse] = Field(default_factory=list)
    maintenance_state: str | None = None
