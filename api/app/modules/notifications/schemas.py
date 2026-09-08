from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: int
    category: str
    severity: str
    title: str
    body: str
    deep_link: str | None = None
    actor_name: str | None = None
    created_at: datetime
    read_at: datetime | None = None


class NotificationList(BaseModel):
    items: list[NotificationOut]
    total: int
    has_more: bool = False


class NotificationUnreadSummary(BaseModel):
    total_unread: int = 0
    by_severity: dict[str, int] = {}
    by_category: dict[str, int] = {}
    server_time: str | None = None


class CatchUpResponse(BaseModel):
    items: list[NotificationOut]
    latest_id: int = 0


class NotificationPreferenceOut(BaseModel):
    category: str
    label: str
    default_severity: str
    channel_in_app: bool
    channel_tray: bool
    channel_email: bool
    min_severity_email: str
    is_custom: bool = False


class NotificationPreferenceItem(BaseModel):
    category: str
    channel_in_app: bool = True
    channel_tray: bool = True
    channel_email: bool = False
    min_severity_email: str = "alta"


class NotificationPreferencesPayload(BaseModel):
    items: list[NotificationPreferenceItem]


class NotificationUserSettingsOut(BaseModel):
    quiet_start: str | None = None
    quiet_end: str | None = None
    quiet_channels: list[str] = []


class NotificationSettingsPayload(BaseModel):
    quiet_start: str | None = None
    quiet_end: str | None = None
    quiet_channels: list[str] = []
