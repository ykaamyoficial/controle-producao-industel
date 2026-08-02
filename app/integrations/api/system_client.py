from __future__ import annotations

from typing import Any

from app.integrations.api.client import DesktopApiClient
from app.integrations.api.models import SystemIdentity, SystemVersion


class SystemApiClient:
    def __init__(self, client: DesktopApiClient):
        self.client = client

    def health(self) -> dict[str, Any]:
        return self.client.get("/api/v1/system/health").data

    def readiness(self) -> dict[str, Any]:
        return self.client.get("/api/v1/system/ready").data

    def version(self) -> SystemVersion:
        return SystemVersion.from_payload(self.client.get("/api/v1/system/version").data)

    def identity(self) -> SystemIdentity:
        return SystemIdentity.from_payload(self.client.get("/api/v1/system/identity").data)
