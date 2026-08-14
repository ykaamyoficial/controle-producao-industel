from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from api.app.modules.auth.schemas import UserOut


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=1, max_length=256)
    active: bool = True
    is_superuser: bool = False
    role_ids: list[int] = Field(default_factory=list)
    permission_codes: list[str] | None = None


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=80)
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
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
