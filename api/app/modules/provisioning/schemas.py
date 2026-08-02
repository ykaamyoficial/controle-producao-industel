from __future__ import annotations

from pydantic import BaseModel, Field

from api.app.modules.auth.schemas import UserOut


class InitialAdminCreate(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=2, max_length=160)
    temporary_password: str = Field(min_length=10, max_length=256)


class InitialAdminResponse(BaseModel):
    user: UserOut
    created: bool
    message: str
