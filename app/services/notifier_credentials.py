from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.services.app_logging import get_logger
from app.services.app_paths import get_app_data_dir


log = get_logger("notifier_credentials")

NOTIFIER_DIR_ENV = "CONTROLE_PRODUCAO_NOTIFIER_DIR"
CREDENTIAL_FILE_NAME = "credential.dpapi"
STATE_FILE_NAME = "state.json"
STATUS_FILE_NAME = "status.json"


def credential_dir() -> Path:
    """Pasta do agente de avisos, POR usuario do Windows (%LOCALAPPDATA%).

    A credencial NAO fica em ProgramData: la todos os usuarios do Windows da
    maquina compartilhariam o mesmo arquivo (e o DPAPI de um nao abre o do
    outro, o que fazia o agente apagar a credencial alheia)."""
    override = os.environ.get(NOTIFIER_DIR_ENV)
    if override:
        return Path(override)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "ControleProducao" / "notifier"
    return get_app_data_dir() / "notifier"


@dataclass(frozen=True)
class NotifierCredential:
    """Credencial do computador, emitida pela API no ultimo login. Dona do
    aviso e sempre `user_id`; `base_url` impede usar a credencial de um
    servidor (ex.: oficial) contra outro (ex.: dev)."""

    device_token: str
    user_id: int
    username: str
    display_name: str
    base_url: str
    installation_id: str
    registered_at: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NotifierCredential | None":
        token = str(data.get("device_token") or "").strip()
        try:
            user_id = int(data.get("user_id") or 0)
        except (TypeError, ValueError):
            return None
        if not token or user_id <= 0:
            return None
        return cls(
            device_token=token,
            user_id=user_id,
            username=str(data.get("username") or ""),
            display_name=str(data.get("display_name") or data.get("username") or ""),
            base_url=str(data.get("base_url") or ""),
            installation_id=str(data.get("installation_id") or ""),
            registered_at=float(data.get("registered_at") or 0),
        )


def _protector():
    from app.services.nomus_api_config import WindowsDpapiProtector

    return WindowsDpapiProtector()


def save_credential(credential: NotifierCredential, *, protector=None) -> None:
    path = credential_dir() / CREDENTIAL_FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = (protector or _protector()).protect(json.dumps(asdict(credential), ensure_ascii=False))
    temp = path.with_suffix(".tmp")
    temp.write_bytes(blob)
    os.replace(temp, path)
    log.info("notifier_credencial_salva | usuario=%s", credential.username)


def load_credential(*, protector=None) -> NotifierCredential | None:
    path = credential_dir() / CREDENTIAL_FILE_NAME
    try:
        blob = path.read_bytes()
    except OSError:
        return None
    if not blob:
        return None
    try:
        data = json.loads((protector or _protector()).unprotect(blob))
    except Exception:
        # Arquivo de outro usuario do Windows ou corrompido: tratado como
        # "sem credencial", nunca apagado aqui (nao e nosso para apagar).
        log.warning("notifier_credencial_ilegivel")
        return None
    return NotifierCredential.from_dict(data) if isinstance(data, dict) else None


def clear_credential(*, only_if_token: str | None = None, protector=None) -> bool:
    """Apaga a credencial local. Com `only_if_token`, so apaga se o arquivo ainda
    guardar esse mesmo token: evita derrubar a credencial NOVA que o app
    principal acabou de gravar enquanto o agente ainda segurava a antiga."""
    if only_if_token is not None:
        current = load_credential(protector=protector)
        if current is not None and current.device_token != only_if_token:
            return False
    path = credential_dir() / CREDENTIAL_FILE_NAME
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    log.info("notifier_credencial_removida")
    return True


# ------------------------------------------------------------ estado e status


@dataclass
class NotifierState:
    """Ponteiro do que o agente ja mostrou, POR dono. `user_id` diz de quem e o
    ponteiro: ao trocar de usuario o agente recomeca do zero em vez de
    despejar avisos antigos."""

    last_seen_notification_id: int = 0
    user_id: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NotifierState":
        return cls(
            last_seen_notification_id=int(data.get("last_seen_notification_id") or 0),
            user_id=int(data.get("user_id") or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"last_seen_notification_id": self.last_seen_notification_id, "user_id": self.user_id}


def load_state() -> NotifierState:
    path = credential_dir() / STATE_FILE_NAME
    if not path.exists():
        return NotifierState()
    try:
        return NotifierState.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, OSError, TypeError):
        return NotifierState()


def save_state(state: NotifierState) -> None:
    path = credential_dir() / STATE_FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def write_status(**fields: Any) -> None:
    """Situacao do agente para a tela de Configuracoes (best effort)."""
    path = credential_dir() / STATUS_FILE_NAME
    try:
        current: dict[str, Any] = {}
        if path.exists():
            current = json.loads(path.read_text(encoding="utf-8"))
        current.update(fields)
        current["updated_at"] = time.time()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
    except (OSError, ValueError):
        pass


def read_status() -> dict[str, Any]:
    try:
        data = json.loads((credential_dir() / STATUS_FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
