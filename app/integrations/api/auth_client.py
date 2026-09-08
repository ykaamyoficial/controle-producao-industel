from __future__ import annotations

from app.integrations.api.client import DesktopApiClient
from app.integrations.api.models import ApiUser, TokenPair


class AuthApiClient:
    def __init__(self, client: DesktopApiClient):
        self.client = client

    def login(self, username: str, password: str) -> TokenPair:
        data = self.client.post("/api/v1/auth/login", json_payload={"username": username, "password": password}).data
        return _token_pair(data)

    def refresh(self, refresh_token: str) -> TokenPair:
        data = self.client.post("/api/v1/auth/refresh", json_payload={"refresh_token": refresh_token}).data
        return _token_pair(data)

    def logout(self, access_token: str, refresh_token: str | None = None) -> None:
        self.client.post("/api/v1/auth/logout", json_payload={"refresh_token": refresh_token}, access_token=access_token)

    def logout_all(self, access_token: str) -> None:
        self.client.post("/api/v1/auth/logout-all", access_token=access_token)

    def me(self, access_token: str) -> ApiUser:
        return ApiUser.from_payload(self.client.get("/api/v1/auth/me", access_token=access_token).data)

    def update_me(self, access_token: str, *, username: str | None = None, display_name: str | None = None, email: str | None = None) -> ApiUser:
        payload = {key: value for key, value in {"username": username, "display_name": display_name, "email": email}.items() if value is not None}
        return ApiUser.from_payload(self.client.patch("/api/v1/users/me", json_payload=payload, access_token=access_token).data)

    def change_password(self, access_token: str, current_password: str, new_password: str, confirm_password: str) -> ApiUser:
        return ApiUser.from_payload(self.client.post("/api/v1/users/me/change-password", json_payload={"current_password": current_password, "new_password": new_password, "confirm_password": confirm_password}, access_token=access_token).data)

    def upload_avatar(self, access_token: str, filename: str, content: bytes, mime: str) -> ApiUser:
        return ApiUser.from_payload(self.client.request("POST", "/api/v1/users/me/avatar", files={"file": (filename, content, mime)}, access_token=access_token).data)

    def remove_avatar(self, access_token: str) -> ApiUser:
        return ApiUser.from_payload(self.client.delete("/api/v1/users/me/avatar", access_token=access_token).data)

    def avatar_bytes(self, access_token: str, user_id: int) -> bytes | None:
        return self.client.get_bytes(f"/api/v1/users/{int(user_id)}/avatar", access_token=access_token)


def _token_pair(data: dict) -> TokenPair:
    return TokenPair(
        access_token=str(data["access_token"]),
        refresh_token=str(data["refresh_token"]),
        expires_in=int(data["expires_in"]),
        user=ApiUser.from_payload(data["user"]),
    )
