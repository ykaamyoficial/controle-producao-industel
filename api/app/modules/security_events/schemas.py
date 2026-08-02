from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SecurityEventOut(BaseModel):
    id: int
    event_type: str
    actor_user_id: int | None
    target_user_id: int | None
    request_id: str | None
    ip_address: str | None
    user_agent: str | None
    success: bool
    details: dict[str, Any] | None
    created_at: datetime


class SecurityEventList(BaseModel):
    items: list[SecurityEventOut] = Field(default_factory=list)
    total: int
