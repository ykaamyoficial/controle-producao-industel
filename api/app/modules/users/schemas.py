from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.app.modules.auth.schemas import UserOut


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=200)
    password: str = Field(min_length=1, max_length=256)
    active: bool = True
    is_superuser: bool = False
    role_ids: list[int] = Field(default_factory=list)
    permission_codes: list[str] | None = None


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=80)
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=200)
    active: bool | None = None
    is_superuser: bool | None = None
    role_ids: list[int] | None = None
    permission_codes: list[str] | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    revoke_sessions: bool = True


class MeUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=80)
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=200)


class ChangePassword(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)
    confirm_password: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def passwords_match(self):
        if self.new_password != self.confirm_password:
            raise ValueError("A confirmacao da nova senha nao confere.")
        return self


class UserList(BaseModel):
    items: list[UserOut]
    total: int


class UserSyncPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legacy_id: int = Field(gt=0)
    username: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=160)
    active: bool = True
    is_superuser: bool = False
    permission_codes: list[str] = Field(default_factory=list)
    source_hash: str = Field(min_length=64, max_length=64)

    @field_validator("username", "display_name", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class UserSyncBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_identifier: str = Field(min_length=1, max_length=300)
    dry_run: bool = False
    batch_number: int = Field(default=1, ge=1)
    batch_total: int = Field(default=1, ge=1)
    default_password: str = Field(min_length=1, max_length=256)
    users: list[UserSyncPayload] = Field(default_factory=list, max_length=200)


class SyncSummary(BaseModel):
    received: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: int = 0
    errors: list[str] = Field(default_factory=list)
    dry_run: bool = False
    sync_run_id: int | None = None
