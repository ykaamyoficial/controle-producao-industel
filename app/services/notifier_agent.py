from __future__ import annotations

import ctypes
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.integrations.api.auth_client import AuthApiClient
from app.integrations.api.chat_client import ChatApiClient
from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiConfigStore
from app.integrations.api.exceptions import ApiClientError
from app.integrations.api.token_store import ApiTokenStore
from app.services.app_logging import get_logger
from app.services.app_paths import get_app_data_dir, is_packaged
from app.ui.app_icon import app_icon_path


log = get_logger("notifier_agent")

MAIN_APP_MUTEX_NAME = "Global\\ControleProducaoIndustel_MainAppRunning"
NOTIFIER_INSTANCE_MUTEX_NAME = "Global\\ControleProducaoIndustel_NotifierInstance"
STATE_FILE_NAME = "notifier_state.json"
POLL_INTERVAL_SECONDS = 180
TOAST_APP_ID = "Controle de Producao Industel"
STARTUP_SCRIPT_NAME = "ControleProducaoIndustelNotificacoes.bat"
SYNCHRONIZE = 0x00100000
ERROR_ALREADY_EXISTS = 183


def acquire_main_app_mutex() -> int | None:
    """Cria um mutex nomeado que fica aberto enquanto o app principal (GUI) roda.

    O Windows fecha o handle automaticamente quando o processo termina (mesmo em
    caso de crash), entao nenhuma liberacao explicita e necessaria.
    """
    if not hasattr(ctypes, "windll"):
        return None
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, MAIN_APP_MUTEX_NAME)
    if not handle:
        log.warning("notifier_mutex_create_falhou")
        return None
    return handle


def is_main_app_running() -> bool:
    if not hasattr(ctypes, "windll"):
        return False
    handle = ctypes.windll.kernel32.OpenMutexW(SYNCHRONIZE, False, MAIN_APP_MUTEX_NAME)
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    return False


def _try_acquire_notifier_instance_lock() -> int | None:
    """Garante uma unica instancia do agente --notifier por vez.

    Sem isso, uma instancia lancada manualmente (ex.: para teste) rodando ao
    mesmo tempo que a instancia registrada na pasta Startup poderia disputar a
    renovacao do MESMO refresh token — e como o backend revoga a familia
    inteira do token ao detectar reuso, isso derrubaria a sessao do usuario
    (inclusive do app principal) sem aviso.
    """
    if not hasattr(ctypes, "windll"):
        return None
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, NOTIFIER_INSTANCE_MUTEX_NAME)
    last_error = ctypes.windll.kernel32.GetLastError()
    if not handle:
        return None
    if last_error == ERROR_ALREADY_EXISTS:
        ctypes.windll.kernel32.CloseHandle(handle)
        return None
    return handle


@dataclass
class NotifierState:
    total_unread: int = 0
    pending_questions: int = 0
    new_observations: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NotifierState":
        return cls(
            total_unread=int(data.get("total_unread") or 0),
            pending_questions=int(data.get("pending_questions") or 0),
            new_observations=int(data.get("new_observations") or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_unread": self.total_unread,
            "pending_questions": self.pending_questions,
            "new_observations": self.new_observations,
        }


def _state_path() -> Path:
    return get_app_data_dir() / STATE_FILE_NAME


def load_state() -> NotifierState:
    path = _state_path()
    if not path.exists():
        return NotifierState()
    try:
        return NotifierState.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, OSError):
        return NotifierState()


def save_state(state: NotifierState) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def build_notification_message(previous: NotifierState, current: NotifierState) -> str | None:
    """Funcao pura: decide se ha novidade desde o ciclo anterior e monta o texto do toast."""
    new_messages = max(0, current.total_unread - previous.total_unread)
    new_questions = max(0, current.pending_questions - previous.pending_questions)
    new_observations = max(0, current.new_observations - previous.new_observations)
    parts = []
    if new_messages:
        parts.append(f"{new_messages} nova(s) mensagem(ns)")
    if new_questions:
        parts.append(f"{new_questions} pergunta(s) pendente(s)")
    if new_observations:
        parts.append(f"{new_observations} nova(s) observação(ões)")
    return ", ".join(parts) if parts else None


def _fetch_unread_summary() -> dict[str, Any] | None:
    config_store = DesktopApiConfigStore()
    settings = config_store.load_settings()
    if not settings.enabled:
        return None
    token_store = ApiTokenStore()
    refresh_token = token_store.get_refresh_token()
    if not refresh_token:
        log.info("notifier_sem_sessao_salva")
        return None
    client = DesktopApiClient(settings)
    try:
        pair = AuthApiClient(client).refresh(refresh_token)
        token_store.save_refresh_token(pair.refresh_token)
        return ChatApiClient(client).unread_summary(pair.access_token)
    except ApiClientError as exc:
        log.warning("notifier_ciclo_falhou | detalhe=%s", exc)
        return None
    finally:
        client.close()


def _send_toast(message: str) -> bool:
    """Tenta exibir o toast. Retorna False se nao foi possivel disparar."""
    try:
        from winotify import Notification
    except ImportError:
        log.warning("notifier_winotify_indisponivel")
        return False
    icon_path = app_icon_path()
    launch_target = str(Path(sys.executable)) if is_packaged() else ""
    try:
        toast = Notification(
            app_id=TOAST_APP_ID,
            title=TOAST_APP_ID,
            msg=message,
            icon=str(icon_path) if icon_path.exists() else "",
            duration="long",
            launch=launch_target,
        )
        toast.show()
        return True
    except Exception:
        log.exception("notifier_toast_erro_ao_exibir")
        return False


def run_cycle() -> None:
    if is_main_app_running():
        log.info("notifier_ciclo_ignorado | motivo=app_principal_aberto")
        return
    summary = _fetch_unread_summary()
    if summary is None:
        return
    previous = load_state()
    current = NotifierState(
        total_unread=int(summary.get("total_unread") or 0),
        pending_questions=int(summary.get("pending_questions") or 0),
        new_observations=int(summary.get("new_observations") or 0),
    )
    message = build_notification_message(previous, current)
    if message:
        log.info("notifier_toast_disparado | resumo=%s", message)
        if not _send_toast(message):
            # Nao avanca o estado salvo: se o toast falhou, a novidade
            # precisa continuar "pendente" para ser tentada no proximo ciclo.
            return
    save_state(current)


def run_notifier_loop(*, poll_interval: int = POLL_INTERVAL_SECONDS) -> None:
    if hasattr(ctypes, "windll"):
        instance_lock = _try_acquire_notifier_instance_lock()
        if instance_lock is None:
            log.warning("notifier_ja_em_execucao | outra_instancia_do_agente_detectada")
            return
    log.info("notifier_iniciado | intervalo_segundos=%s", poll_interval)
    while True:
        try:
            run_cycle()
        except Exception:
            log.exception("notifier_ciclo_erro_inesperado")
        time.sleep(poll_interval)


def ensure_startup_registration() -> None:
    """Registra (uma vez, de forma idempotente) o modo --notifier na pasta Startup do Windows."""
    if not is_packaged() or sys.platform != "win32":
        return
    import os

    appdata = os.environ.get("APPDATA")
    if not appdata:
        return
    startup_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    script_path = startup_dir / STARTUP_SCRIPT_NAME
    exe_path = Path(sys.executable)
    expected_content = f'@echo off\nstart "" "{exe_path}" --notifier\n'
    try:
        if script_path.exists() and script_path.read_text(encoding="utf-8") == expected_content:
            return
        startup_dir.mkdir(parents=True, exist_ok=True)
        script_path.write_text(expected_content, encoding="utf-8")
        log.info("notifier_startup_registrado | arquivo=%s", script_path)
    except OSError:
        log.warning("notifier_startup_registro_falhou")
