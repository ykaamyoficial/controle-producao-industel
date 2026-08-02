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


def _token_pair(data: dict) -> TokenPair:
    return TokenPair(
        access_token=str(data["access_token"]),
        refresh_token=str(data["refresh_token"]),
        expires_in=int(data["expires_in"]),
        user=ApiUser.from_payload(data["user"]),
    )
