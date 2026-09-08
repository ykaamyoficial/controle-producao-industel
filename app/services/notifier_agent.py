from __future__ import annotations

import ctypes
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.integrations.api.auth_client import AuthApiClient
from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiConfigStore
from app.integrations.api.exceptions import ApiClientError
from app.integrations.api.notifications_client import NotificationsApiClient
from app.integrations.api.token_store import ApiTokenStore
from app.services.app_logging import get_logger
from app.services.app_paths import get_app_data_dir, is_packaged
from app.ui.app_icon import app_icon_path


log = get_logger("notifier_agent")

MAIN_APP_MUTEX_NAME = "Global\\ControleProducaoIndustel_MainAppRunning"
NOTIFIER_INSTANCE_MUTEX_NAME = "Global\\ControleProducaoIndustel_NotifierInstance"
STATE_FILE_NAME = "notifier_state.json"
PENDING_DEEP_LINK_FILE_NAME = "pending_deep_link.json"
# Push instantaneo via WebSocket + este poll como rede de seguranca (WS caido,
# maquina que dormiu). Bem mais curto que os 180s do desenho antigo so-poll.
POLL_INTERVAL_SECONDS = 60
TOAST_APP_ID = "Controle de Producao Industel"
STARTUP_SCRIPT_NAME = "ControleProducaoIndustelNotificacoes.bat"
SYNCHRONIZE = 0x00100000
ERROR_ALREADY_EXISTS = 183

# Severidades que merecem um toast proprio; o resto e agrupado num unico aviso.
_INDIVIDUAL_TOAST_SEVERITIES = {"alta", "critica"}


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
    """Ponteiro do que o agente ja mostrou. `last_seen_notification_id` e o id
    da notificacao generica mais recente que ja virou toast — o proximo ciclo
    so busca `id > last_seen` (endpoint /notifications/catch-up)."""

    last_seen_notification_id: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NotifierState":
        return cls(last_seen_notification_id=int(data.get("last_seen_notification_id") or 0))

    def to_dict(self) -> dict[str, Any]:
        return {"last_seen_notification_id": self.last_seen_notification_id}


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


# --------------------------------------------------------------- deep link

def stash_pending_deep_link(route: str) -> None:
    """Grava a rota que o app principal deve abrir ao iniciar (clique no toast
    quando o app estava fechado). Consumida uma unica vez por
    `consume_pending_deep_link`."""
    route = (route or "").strip()
    if not route:
        return
    try:
        path = get_app_data_dir() / PENDING_DEEP_LINK_FILE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"route": route, "at": time.time()}), encoding="utf-8")
    except OSError:
        log.warning("notifier_pending_deep_link_write_falhou")


def consume_pending_deep_link(*, max_age_seconds: float = 600.0) -> str | None:
    path = get_app_data_dir() / PENDING_DEEP_LINK_FILE_NAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        path.unlink(missing_ok=True)
    except (ValueError, OSError):
        return None
    route = str(data.get("route") or "").strip()
    if not route or (time.time() - float(data.get("at") or 0)) > max_age_seconds:
        return None
    return route


# --------------------------------------------------------------- rede/API

def _fetch_notifications(since_id: int) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    """Renova o token e busca (catch-up + resumo de nao lidas). Retorna
    (novos_itens, resumo) ou None se nao ha sessao/servidor."""
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
        api = NotificationsApiClient(client)
        catch_up = api.catch_up(pair.access_token, since_id=since_id, limit=50)
        summary = api.unread_summary(pair.access_token)
        items = [item for item in (catch_up.get("items") or []) if isinstance(item, dict)]
        return items, summary
    except ApiClientError as exc:
        log.warning("notifier_ciclo_falhou | detalhe=%s", exc)
        return None
    finally:
        client.close()


def _mark_all_read_remote() -> bool:
    config_store = DesktopApiConfigStore()
    settings = config_store.load_settings()
    if not settings.enabled:
        return False
    token_store = ApiTokenStore()
    refresh_token = token_store.get_refresh_token()
    if not refresh_token:
        return False
    client = DesktopApiClient(settings)
    try:
        pair = AuthApiClient(client).refresh(refresh_token)
        token_store.save_refresh_token(pair.refresh_token)
        NotificationsApiClient(client).mark_all_read(pair.access_token)
        return True
    except ApiClientError as exc:
        log.warning("notifier_mark_all_read_falhou | detalhe=%s", exc)
        return False
    finally:
        client.close()


# --------------------------------------------------------------- toasts

def plan_toasts(items: list[dict[str, Any]], *, suppress_individual: bool) -> list[dict[str, str]]:
    """Funcao pura: decide quais toasts disparar para um lote de novidades.

    - `suppress_individual=True` (app principal aberto): nenhum toast — o app
      principal ja mostra o aviso in-app; o agente so mantem o icone/contador.
    - severidade alta/critica: um toast por notificacao, com deep-link proprio.
    - o resto: um unico toast agrupado, sem deep-link.
    """
    if suppress_individual or not items:
        return []
    toasts: list[dict[str, str]] = []
    grouped: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("severity")) in _INDIVIDUAL_TOAST_SEVERITIES:
            toasts.append(
                {
                    "title": str(item.get("title") or TOAST_APP_ID),
                    "message": str(item.get("body") or "").strip(),
                    "deep_link": str(item.get("deep_link") or ""),
                }
            )
        else:
            grouped.append(item)
    if grouped:
        if len(grouped) == 1:
            only = grouped[0]
            toasts.append(
                {
                    "title": str(only.get("title") or TOAST_APP_ID),
                    "message": str(only.get("body") or "").strip(),
                    "deep_link": str(only.get("deep_link") or ""),
                }
            )
        else:
            toasts.append(
                {
                    "title": TOAST_APP_ID,
                    "message": f"{len(grouped)} novas notificacoes",
                    "deep_link": "",
                }
            )
    return toasts


def _launch_target(deep_link: str) -> str:
    if not is_packaged():
        return ""
    exe = str(Path(sys.executable))
    route = (deep_link or "").strip()
    return f'"{exe}" --open {route}' if route else f'"{exe}"'


def _send_toast(title: str, message: str, deep_link: str = "") -> bool:
    """Tenta exibir o toast. Retorna False se nao foi possivel disparar."""
    try:
        from winotify import Notification
    except ImportError:
        log.warning("notifier_winotify_indisponivel")
        return False
    icon_path = app_icon_path()
    try:
        toast = Notification(
            app_id=TOAST_APP_ID,
            title=title or TOAST_APP_ID,
            msg=message or "",
            icon=str(icon_path) if icon_path.exists() else "",
            duration="long",
            launch=_launch_target(deep_link),
        )
        toast.show()
        return True
    except Exception:
        log.exception("notifier_toast_erro_ao_exibir")
        return False


# --------------------------------------------------------------- ciclo

_TRAY_UPDATER: Callable[[dict[str, Any]], None] | None = None


def set_tray_updater(callback: Callable[[dict[str, Any]], None] | None) -> None:
    global _TRAY_UPDATER
    _TRAY_UPDATER = callback


def run_cycle() -> int:
    """Um ciclo do agente. Retorna quantos toasts foram efetivamente exibidos.

    Sempre atualiza o icone da bandeja (mesmo com o app principal aberto);
    so os toasts respeitam `is_main_app_running()`."""
    state = load_state()
    result = _fetch_notifications(state.last_seen_notification_id)
    if result is None:
        return 0
    items, summary = result

    if _TRAY_UPDATER is not None:
        try:
            _TRAY_UPDATER(summary)
        except Exception:
            log.exception("notifier_tray_update_falhou")

    if not items:
        return 0

    highest_id = max(int(item.get("id") or 0) for item in items)
    toasts = plan_toasts(items, suppress_individual=is_main_app_running())

    shown = 0
    for toast in toasts:
        if _send_toast(toast["title"], toast["message"], toast.get("deep_link", "")):
            shown += 1
        else:
            # toast falhou: nao avanca o estado — a novidade continua pendente
            # para o proximo ciclo.
            log.warning("notifier_toast_falhou | mantendo_estado_para_retry")
            return shown

    # Sem toasts (app principal aberto) OU todos exibidos: avanca o ponteiro.
    save_state(NotifierState(last_seen_notification_id=highest_id))
    if toasts:
        log.info("notifier_toasts_exibidos | quantidade=%s | ate_id=%s", shown, highest_id)
    return shown


# --------------------------------------------------------------- bandeja + loop

class NotifierTrayIcon:
    """Icone permanente na bandeja do Windows. So instanciado quando ha um
    QApplication (dentro de run_notifier_loop)."""

    def __init__(self, app, *, on_open, on_mark_all_read, on_quit):
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon

        icon_path = app_icon_path()
        self._icon = QSystemTrayIcon(QIcon(str(icon_path)) if icon_path.exists() else QIcon(), app)
        self._icon.setToolTip(TOAST_APP_ID)
        menu = QMenu()
        menu.addAction("Abrir programa", on_open)
        menu.addAction("Marcar todas como lidas", on_mark_all_read)
        menu.addSeparator()
        menu.addAction("Sair", on_quit)
        self._icon.setContextMenu(menu)
        self._icon.activated.connect(lambda reason: on_open() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self._icon.show()

    def apply_summary(self, summary: dict[str, Any]) -> None:
        total = int(summary.get("total_unread") or 0)
        self._icon.setToolTip(f"{TOAST_APP_ID}\n{total} notificacao(oes) nao lida(s)" if total else TOAST_APP_ID)


def _open_main_app() -> None:
    if not is_packaged():
        return
    try:
        import subprocess

        subprocess.Popen([str(Path(sys.executable))])  # noqa: S603
    except OSError:
        log.warning("notifier_abrir_app_falhou")


def run_notifier_loop(*, poll_interval: int = POLL_INTERVAL_SECONDS) -> None:
    if hasattr(ctypes, "windll"):
        instance_lock = _try_acquire_notifier_instance_lock()
        if instance_lock is None:
            log.warning("notifier_ja_em_execucao | outra_instancia_do_agente_detectada")
            return

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    tray = NotifierTrayIcon(
        app,
        on_open=_open_main_app,
        on_mark_all_read=lambda: (_mark_all_read_remote(), _run_cycle_safe()),
        on_quit=app.quit,
    )
    set_tray_updater(tray.apply_summary)

    realtime = _NotifierRealtime(on_event=_run_cycle_safe)
    realtime.start()

    timer = QTimer()
    timer.timeout.connect(_run_cycle_safe)
    timer.start(max(10, poll_interval) * 1000)

    QTimer.singleShot(0, _run_cycle_safe)
    log.info("notifier_iniciado | intervalo_segundos=%s", poll_interval)
    try:
        app.exec()
    finally:
        realtime.stop()
        set_tray_updater(None)


def _run_cycle_safe() -> None:
    try:
        run_cycle()
    except Exception:
        log.exception("notifier_ciclo_erro_inesperado")


class _NotifierRealtime:
    """WebSocket minimo e reconectavel: qualquer evento `notification.*`
    dispara um ciclo imediato (o corpo vem por REST no ciclo). Reaproveita o
    endpoint /chat/ws, que ja entrega notification.created."""

    def __init__(self, *, on_event: Callable[[], None]):
        self._on_event = on_event
        self._socket = None
        self._timer = None
        self._stopped = True
        self._delay_ms = 1000

    def start(self) -> None:
        try:
            from PySide6.QtCore import QTimer
            from PySide6.QtWebSockets import QWebSocket
        except Exception:
            log.info("notifier_realtime_indisponivel")
            return
        self._stopped = False
        self._socket = QWebSocket()
        self._socket.connected.connect(lambda: setattr(self, "_delay_ms", 1000))
        self._socket.disconnected.connect(self._schedule_reconnect)
        self._socket.textMessageReceived.connect(self._on_text)
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._connect)
        self._connect()

    def stop(self) -> None:
        self._stopped = True
        if self._timer is not None:
            self._timer.stop()
        if self._socket is not None:
            self._socket.close()

    def _connect(self) -> None:
        if self._stopped or self._socket is None:
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtNetwork import QNetworkRequest

        try:
            config_store = DesktopApiConfigStore()
            settings = config_store.load_settings()
            if not settings.enabled:
                return
            token_store = ApiTokenStore()
            refresh_token = token_store.get_refresh_token()
            if not refresh_token:
                return
            client = DesktopApiClient(settings)
            try:
                pair = AuthApiClient(client).refresh(refresh_token)
                token_store.save_refresh_token(pair.refresh_token)
            finally:
                client.close()
            from app.integrations.api.config import normalize_api_base_url

            base = normalize_api_base_url(settings.base_url)
            ws_url = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/api/v1/chat/ws"
            request = QNetworkRequest(QUrl(ws_url))
            request.setRawHeader(b"Authorization", f"Bearer {pair.access_token}".encode("utf-8"))
            self._socket.open(request)
        except Exception:
            log.debug("notifier_realtime_connect_falhou", exc_info=True)
            self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        if self._stopped or self._timer is None:
            return
        self._timer.start(self._delay_ms)
        self._delay_ms = min(self._delay_ms * 2, 30000)

    def _on_text(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except ValueError:
            return
        if isinstance(payload, dict) and str(payload.get("type", "")).startswith("notification."):
            self._on_event()


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
