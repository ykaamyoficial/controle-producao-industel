from __future__ import annotations

from pydantic import BaseModel, Field

from api.app.modules.auth.schemas import PermissionOut, RoleOut


class RoleCreate(BaseModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    active: bool = True
    permission_ids: list[int] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    active: bool | None = None


class RoleDetail(RoleOut):
    description: str | None = None
    system_role: bool
    permissions: list[PermissionOut] = Field(default_factory=list)


class RoleList(BaseModel):
    items: list[RoleDetail]
    total: int


class PermissionList(BaseModel):
    items: list[PermissionOut]
    total: int
