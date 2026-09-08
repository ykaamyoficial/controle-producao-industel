from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20)


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class PermissionOut(BaseModel):
    id: int
    code: str
    name: str
    module: str


class RoleOut(BaseModel):
    id: int
    code: str
    name: str
    active: bool = True


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    email: str | None = None
    active: bool
    is_superuser: bool
    password_must_change: bool = False
    locked_until: datetime | None = None
    roles: list[RoleOut] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    avatar_available: bool = False
    avatar_mime: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
