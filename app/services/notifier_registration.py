"""Registro, na API, do computador como destino dos avisos do Windows.

Chamado pelo app principal: a cada login (o ultimo login vence) e, sem forcar,
ao abrir com sessao restaurada (cobre o primeiro start depois da atualizacao,
quando ainda nao existe credencial local)."""

from __future__ import annotations

import getpass
import platform
import threading
import time

from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiConfigStore, normalize_api_base_url
from app.integrations.api.exceptions import ApiClientError
from app.integrations.api.notifier_client import NotifierApiClient
from app.services import notifier_credentials as creds
from app.services.app_logging import get_logger


log = get_logger("notifier_registration")


def _os_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return ""


def register_current_login(access_token: str, user_id: int, *, force: bool) -> bool:
    """Devolve True se uma credencial nova foi gravada. Nunca levanta: falha de
    rede aqui so adia os avisos do Windows, nao pode atrapalhar o login."""
    try:
        if not access_token or not user_id:
            return False
        settings = DesktopApiConfigStore().load_settings()
        if not settings.enabled:
            return False
        base_url = normalize_api_base_url(settings.base_url)
        current = creds.load_credential()
        if (
            not force
            and current is not None
            and current.user_id == int(user_id)
            and current.base_url == base_url
        ):
            return False

        from app.services.installation_identity import get_or_create_installation_identity

        identity = get_or_create_installation_identity()
        client = DesktopApiClient(settings)
        try:
            data = NotifierApiClient(client).register_device(
                access_token,
                installation_id=identity.installation_id,
                os_user=_os_user(),
                device_name=platform.node() or None,
            )
        finally:
            client.close()
        owner = data.get("user") or {}
        creds.save_credential(
            creds.NotifierCredential(
                device_token=str(data["device_token"]),
                user_id=int(owner.get("id") or user_id),
                username=str(owner.get("username") or ""),
                display_name=str(owner.get("display_name") or owner.get("username") or ""),
                base_url=base_url,
                installation_id=identity.installation_id,
                registered_at=time.time(),
            )
        )
        return True
    except ApiClientError as exc:
        log.warning("notifier_registro_falhou | detalhe=%s", exc)
    except Exception:
        log.warning("notifier_registro_erro_inesperado", exc_info=True)
    return False


def register_in_background(access_token: str, user_id: int, *, force: bool) -> None:
    threading.Thread(
        target=register_current_login,
        args=(access_token, user_id),
        kwargs={"force": force},
        name="notifier-registration",
        daemon=True,
    ).start()
