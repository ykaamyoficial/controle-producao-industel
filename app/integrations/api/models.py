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
    avatar_available: bool = False
    avatar_mime: str | None = None

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
            avatar_available=bool(payload.get("avatar_available", False)),
            avatar_mime=payload.get("avatar_mime"),
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
class MaintenanceInfoDto:
    """Desserializacao tipada do sub-objeto `maintenance` de
    /system/compatibility (Fase 14, Secao 11). Ausente na resposta ->
    tratado como OFF (API anterior a Fase 14, mesma politica de campo
    aditivo com default seguro das demais fases)."""

    state: str = "OFF"
    maintenance_id: str = "mnt-none"
    message: str = ""
    expected_end_at: str | None = None
    retry_after_seconds: int | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "MaintenanceInfoDto":
        if not payload:
            return cls()
        return cls(
            state=str(payload.get("state") or "OFF"),
            maintenance_id=str(payload.get("maintenance_id") or "mnt-none"),
            message=str(payload.get("message") or ""),
            expected_end_at=payload.get("expected_end_at"),
            retry_after_seconds=payload.get("retry_after_seconds"),
        )


@dataclass(frozen=True)
class SystemCompatibilityDto:
    """Desserializacao tipada de GET /api/v1/system/compatibility (contrato da Fase 02,
    estendido na Fase 13 com os campos de politica de enforcement e na Fase 14
    com o resumo de manutencao).

    Nao espalhe acesso ao dicionario JSON cru pela UI: sempre construa via from_payload.
    Os campos novos (desktop_state, enforcement, authorized_update_version,
    policy_revision, grace_until, message, maintenance) tem default seguro -- uma
    API anterior a essas fases (que nunca os envia) continua sendo desserializada
    normalmente.
    """

    server_version: str
    api_contract_version: str
    database_revision: str
    minimum_desktop_version: str
    recommended_desktop_version: str
    maintenance_mode: bool
    desktop_state: str | None = None
    enforcement: str = "NONE"
    authorized_update_version: str | None = None
    policy_revision: int = 0
    grace_until: str | None = None
    message: str = ""
    maintenance: MaintenanceInfoDto = field(default_factory=MaintenanceInfoDto)
    # Fase 15: aditivos, default seguro para uma API anterior que nunca os envia.
    desktop_channel: str = "PRODUCTION"
    production_version: str | None = None
    pilot_version: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SystemCompatibilityDto":
        try:
            return cls(
                server_version=str(payload["server_version"]),
                api_contract_version=str(payload["api_contract_version"]),
                database_revision=str(payload["database_revision"]),
                minimum_desktop_version=str(payload["minimum_desktop_version"]),
                recommended_desktop_version=str(payload["recommended_desktop_version"]),
                maintenance_mode=bool(payload["maintenance_mode"]),
                desktop_state=payload.get("desktop_state"),
                enforcement=str(payload.get("enforcement") or "NONE"),
                authorized_update_version=payload.get("authorized_update_version"),
                policy_revision=int(payload.get("policy_revision") or 0),
                grace_until=payload.get("grace_until"),
                message=str(payload.get("message") or ""),
                maintenance=MaintenanceInfoDto.from_payload(payload.get("maintenance")),
                desktop_channel=str(payload.get("desktop_channel") or "PRODUCTION"),
                production_version=payload.get("production_version"),
                pilot_version=payload.get("pilot_version"),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"Resposta de /system/compatibility invalida: campo ausente ou malformado ({exc}).") from exc


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
