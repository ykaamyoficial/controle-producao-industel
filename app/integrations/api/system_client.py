from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.integrations.api.client import DesktopApiClient
from app.integrations.api.exceptions import ApiUnexpectedResponseError
from app.integrations.api.models import SystemCompatibilityDto, SystemIdentity, SystemVersion


class SystemApiClient:
    def __init__(self, client: DesktopApiClient):
        self.client = client

    def health(self) -> dict[str, Any]:
        return self.client.get("/api/v1/system/health").data

    def readiness(self) -> dict[str, Any]:
        return self.client.get("/api/v1/system/ready").data

    def version(self) -> SystemVersion:
        return SystemVersion.from_payload(self.client.get("/api/v1/system/version").data)

    def compatibility(
        self,
        *,
        desktop_version: str | None = None,
        installation_id: str | None = None,
        machine_name: str | None = None,
        os_version: str | None = None,
    ) -> SystemCompatibilityDto:
        path = "/api/v1/system/compatibility"
        params = {
            key: value
            for key, value in (
                ("desktop_version", desktop_version),
                ("installation_id", installation_id),
                ("machine_name", machine_name),
                ("os_version", os_version),
            )
            if value
        }
        if params:
            path = f"{path}?{urlencode(params)}"
        response = self.client.get(path)
        try:
            return SystemCompatibilityDto.from_payload(response.data)
        except ValueError as exc:
            raise ApiUnexpectedResponseError(str(exc), request_id=response.request_id) from exc

    def identity(self) -> SystemIdentity:
        return SystemIdentity.from_payload(self.client.get("/api/v1/system/identity").data)
