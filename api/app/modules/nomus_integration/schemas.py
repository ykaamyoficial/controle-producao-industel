from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class NomusSettingsOut(BaseModel):
    enabled: bool
    base_url: str
    api_key_configured: bool
    masked_api_key: str | None
    last_tested_at: datetime | None
    last_test_status: str | None
    last_test_message: str | None


class NomusSettingsUpdate(BaseModel):
    enabled: bool
    base_url: str = Field(default="", max_length=500)


class NomusApiKeyIn(BaseModel):
    api_key: str = Field(min_length=1, max_length=2000)


class NomusImportRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=120)


class NomusConnectionTestOut(BaseModel):
    success: bool
    status_code: int | None
    category: str
    user_message: str
    technical_message: str | None
    tested_at: datetime
    duration_ms: int
    endpoint: str | None = None
    content_type: str | None = None
    authentication_confirmed: bool = False
