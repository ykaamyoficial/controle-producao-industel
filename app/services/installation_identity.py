from __future__ import annotations

import platform
import uuid
from dataclasses import dataclass

from app.services.app_paths import get_config_path
from app.services.configuration_service import get_configuration_service

_CONFIG_KEY = "installation_identity"


@dataclass(frozen=True)
class InstallationIdentity:
    """Identidade estavel desta instalacao do Desktop (Fase 15, Secao 6) --
    NUNCA regenerada em reinicios/updates, usada pelo servidor para resolver
    o canal (DEVELOPMENT/PILOT/PRODUCTION) desta maquina. `machine_name`/
    `os_version` sao somente diagnostico -- nunca usados como identidade
    (Secao 6: "nao use somente nome do usuario/IP como identidade")."""

    installation_id: str
    machine_name: str
    os_version: str


def _read_existing(data: dict) -> InstallationIdentity | None:
    existing = data.get(_CONFIG_KEY)
    if not isinstance(existing, dict):
        return None
    installation_id = str(existing.get("installation_id") or "").strip()
    if not installation_id:
        return None
    return InstallationIdentity(
        installation_id=installation_id,
        machine_name=str(existing.get("machine_name") or platform.node()),
        os_version=str(existing.get("os_version") or platform.platform()),
    )


def get_or_create_installation_identity() -> InstallationIdentity:
    """Le a identidade persistida em config.json (mesmo arquivo atomico de
    desktop_api/nomus_api, sob a chave propria "installation_identity" --
    nao colide com nenhuma chave existente). Gera e persiste uma nova
    identidade somente na primeira chamada em uma instalacao nova; chamadas
    seguintes sempre devolvem o mesmo installation_id (Secao 6: "deve
    sobreviver a reinicios e updates", "nao regenerar a cada versao")."""
    service = get_configuration_service(get_config_path())
    current = _read_existing(service.load())
    if current is not None:
        return current

    identity = InstallationIdentity(
        installation_id=str(uuid.uuid4()),
        machine_name=platform.node(),
        os_version=platform.platform(),
    )

    def _apply(data: dict) -> dict:
        data[_CONFIG_KEY] = {
            "installation_id": identity.installation_id,
            "machine_name": identity.machine_name,
            "os_version": identity.os_version,
        }
        return data

    service.update(_apply)
    return identity
