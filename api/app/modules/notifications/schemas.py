from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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


class NotifierDeviceRegisterPayload(BaseModel):
    installation_id: str = Field(min_length=8, max_length=64)
    os_user: str = Field(default="", max_length=120)
    device_name: str | None = Field(default=None, max_length=160)


class NotifierUserOut(BaseModel):
    id: int
    username: str
    display_name: str


class NotifierDeviceRegistered(BaseModel):
    device_token: str
    expires_at: datetime
    user: NotifierUserOut


class NotifierTokenPayload(BaseModel):
    device_token: str = Field(min_length=16, max_length=200)


class NotifierTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: NotifierUserOut
