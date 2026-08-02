from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class ApiRole:
    id: int
    code: str
    name: str
    active: bool = True


@dataclass(frozen=True)
class ApiUser:
    id: int
    username: str
    display_name: str
    active: bool
    is_superuser: bool
    password_must_change: bool = False
    roles: list[ApiRole] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ApiUser":
        roles = [ApiRole(id=int(item["id"]), code=str(item["code"]), name=str(item["name"]), active=bool(item.get("active", True))) for item in payload.get("roles") or []]
        return cls(
            id=int(payload["id"]),
            username=str(payload["username"]),
            display_name=str(payload["display_name"]),
            active=bool(payload["active"]),
            is_superuser=bool(payload.get("is_superuser", False)),
            password_must_change=bool(
                payload.get("password_must_change", False)
            ),    
            roles=roles,
            permissions=[str(code) for code in payload.get("permissions") or []],
        )


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    user: ApiUser

    @property
    def access_token_expires_at(self) -> datetime:
        return datetime.now() + timedelta(seconds=max(0, self.expires_in))


@dataclass(frozen=True)
class SystemVersion:
    api_version: str
    api_stage: str
    database_revision: str | None
    database_status: str
    minimum_desktop_version: str | None = None
    maximum_desktop_version: str | None = None
    supported_features: list[str] = field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SystemVersion":
        return cls(
            api_version=str(payload["api_version"]),
            api_stage=str(payload["api_stage"]),
            database_revision=payload.get("database_revision"),
            database_status=str(payload["database_status"]),
            minimum_desktop_version=payload.get("minimum_desktop_version"),
            maximum_desktop_version=payload.get("maximum_desktop_version"),
            supported_features=[str(item) for item in payload.get("supported_features") or []],
        )


@dataclass(frozen=True)
class SystemIdentity:
    instance_id: str
    company_id: str | None
    company_code: str
    company_name: str
    environment_type: str
    api_name: str
    api_version: str
    api_stage: str
    database_revision: str | None
    database_status: str
    minimum_desktop_version: str | None = None
    maximum_desktop_version: str | None = None
    supported_features: list[str] = field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SystemIdentity":
        return cls(
            instance_id=str(payload["instance_id"]),
            company_id=payload.get("company_id"),
            company_code=str(payload["company_code"]),
            company_name=str(payload["company_name"]),
            environment_type=str(payload["environment_type"]),
            api_name=str(payload["api_name"]),
            api_version=str(payload["api_version"]),
            api_stage=str(payload["api_stage"]),
            database_revision=payload.get("database_revision"),
            database_status=str(payload["database_status"]),
            minimum_desktop_version=payload.get("minimum_desktop_version"),
            maximum_desktop_version=payload.get("maximum_desktop_version"),
            supported_features=[str(item) for item in payload.get("supported_features") or []],
        )


@dataclass(frozen=True)
class ApiSessionState:
    access_token: str | None = None
    access_token_expires_at: datetime | None = None
    authenticated_user: ApiUser | None = None
    api_session_active: bool = False

    @property
    def roles(self) -> list[ApiRole]:
        return list(self.authenticated_user.roles) if self.authenticated_user else []

    @property
    def permissions(self) -> list[str]:
        return list(self.authenticated_user.permissions) if self.authenticated_user else []

    def expires_soon(self, *, within_seconds: int = 120) -> bool:
        if not self.access_token_expires_at:
            return True
        return self.access_token_expires_at <= datetime.now() + timedelta(seconds=within_seconds)

    def has_permission(self, permission: str) -> bool:
        permissions = set(self.permissions)
        return "*" in permissions or permission in permissions
