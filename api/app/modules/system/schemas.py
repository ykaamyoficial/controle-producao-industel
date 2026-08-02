from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    service: str


class ReadyResponse(BaseModel):
    status: str
    database: str
    mode: str


class VersionResponse(BaseModel):
    api_version: str
    api_stage: str
    database_revision: str | None
    database_status: str
    minimum_desktop_version: str | None = None
    maximum_desktop_version: str | None = None
    supported_features: list[str] = Field(default_factory=list)


class IdentityResponse(BaseModel):
    instance_id: str
    company_id: str | None = None
    company_code: str
    company_name: str
    environment_type: str
    api_name: str
    api_version: str
    api_stage: str
    database_revision: str
    database_status: str
    minimum_desktop_version: str | None = None
    maximum_desktop_version: str | None = None
    supported_features: list[str] = Field(default_factory=list)
