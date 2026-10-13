from __future__ import annotations

import ctypes
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiConfigStore, normalize_api_base_url
from app.integrations.api.exceptions import ApiAuthenticationError, ApiClientError
from app.integrations.api.notifier_client import NotifierApiClient
from app.services import notifier_credentials as creds
from app.services.app_logging import get_logger
from app.services.app_paths import get_app_data_dir, get_launcher_path, is_packaged
from app.services.notifier_credentials import NotifierState, load_state, save_state  # noqa: F401  (reexport)
from app.ui.app_icon import app_icon_path


log = get_logger("notifier_agent")

MAIN_APP_MUTEX_NAME = "Global\\ControleProducaoIndustel_MainAppRunning"
NOTIFIER_INSTANCE_MUTEX_NAME = "Global\\ControleProducaoIndustel_NotifierInstance"
STATE_FILE_NAME = creds.STATE_FILE_NAME
PENDING_DEEP_LINK_FILE_NAME = "pending_deep_link.json"
# Push instantaneo via WebSocket + este poll como rede de seguranca (WS caido,
# maquina que dormiu). Bem mais curto que os 180s do desenho antigo so-poll.
POLL_INTERVAL_SECONDS = 60
TOAST_APP_ID = "Controle de Producao Industel"
STARTUP_SCRIPT_NAME = "ControleProducaoIndustelNotificacoes.bat"  # legado (pasta Startup)
STARTUP_RUN_VALUE_NAME = "ControleProducaoIndustelNotificacoes"
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
SYNCHRONIZE = 0x00100000
ERROR_ALREADY_EXISTS = 183
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000

# Severidades que merecem um toast proprio; o resto e agrupado num unico aviso.
_INDIVIDUAL_TOAST_SEVERITIES = {"alta", "critica"}


def _mutex_exists(name: str) -> bool:
    if not hasattr(ctypes, "windll"):
        return False
    handle = ctypes.windll.kernel32.OpenMutexW(SYNCHRONIZE, False, name)
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    return False


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
    return _mutex_exists(MAIN_APP_MUTEX_NAME)


def is_notifier_running() -> bool:
    return _mutex_exists(NOTIFIER_INSTANCE_MUTEX_NAME)


def _try_acquire_notifier_instance_lock() -> int | None:
    """Garante uma unica instancia do agente --notifier por vez (duas
    instancias mostrariam cada aviso em dobro)."""
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

@dataclass
class FetchResult:
    items: list[dict[str, Any]]
    summary: dict[str, Any]
    user_id: int
    owner_name: str
    state: NotifierState


_no_session_logged = False


def _log_no_session_once() -> None:
    """Sem usuario o agente fica quieto: registra a mudanca UMA vez, nao a cada
    ciclo (eram 1.440 linhas por dia)."""
    global _no_session_logged
    if not _no_session_logged:
        _no_session_logged = True
        log.info("notifier_sem_sessao_salva")


class _AgentSession:
    """Credencial do computador trocada por um token curto de avisos."""

    def __init__(self, client: DesktopApiClient, credential: creds.NotifierCredential, access_token: str):
        self.client = client
        self.credential = credential
        self.access_token = access_token
        self.api = NotifierApiClient(client)

    def close(self) -> None:
        self.client.close()


def _open_session() -> "_AgentSession | None":
    """Abre uma sessao de avisos, ou devolve None se nao ha usuario/servidor.

    Credencial recusada pelo servidor (revogada, expirada, usuario desativado)
    e apagada UMA vez, so se o arquivo ainda guardar esse mesmo token. Falha de
    rede/servidor nao apaga nada: a credencial continua valida."""
    global _no_session_logged
    settings = DesktopApiConfigStore().load_settings()
    if not settings.enabled:
        return None
    credential = creds.load_credential()
    if credential is None:
        _log_no_session_once()
        return None
    if credential.base_url and credential.base_url != normalize_api_base_url(settings.base_url):
        # Credencial de outro servidor (ex.: oficial x dev): nao serve aqui.
        _log_no_session_once()
        return None
    _no_session_logged = False
    client = DesktopApiClient(settings)
    try:
        data = NotifierApiClient(client).exchange_token(credential.device_token)
    except ApiAuthenticationError as exc:
        client.close()
        creds.clear_credential(only_if_token=credential.device_token)
        log.warning("notifier_credencial_recusada | credencial_local_apagada=true | detalhe=%s", exc)
        return None
    except ApiClientError as exc:
        client.close()
        log.warning("notifier_ciclo_falhou | detalhe=%s", exc)
        return None
    access_token = str(data.get("access_token") or "")
    if not access_token:
        client.close()
        return None
    owner = data.get("user") or {}
    if owner.get("display_name"):
        # o nome do dono pode ter mudado desde o login
        credential = creds.NotifierCredential(
            **{**credential.__dict__, "display_name": str(owner.get("display_name"))}
        )
    return _AgentSession(client, credential, access_token)


def _fetch_notifications(state: NotifierState) -> FetchResult | None:
    """Busca (catch-up + resumo de nao lidas) em nome do ULTIMO login deste
    computador. Retorna None se nao ha usuario/servidor."""
    session = _open_session()
    if session is None:
        return None
    try:
        summary = session.api.unread_summary(session.access_token)
        owner = session.credential
        if state.user_id != owner.user_id:
            # Novo dono: comeca do zero, sem despejar o historico em toasts.
            fresh = NotifierState(
                last_seen_notification_id=int(summary.get("latest_id") or 0), user_id=owner.user_id
            )
            save_state(fresh)
            log.info("notifier_novo_dono | usuario=%s | partida_em_id=%s", owner.username, fresh.last_seen_notification_id)
            return FetchResult([], summary, owner.user_id, owner.display_name, fresh)
        catch_up = session.api.catch_up(session.access_token, since_id=state.last_seen_notification_id, limit=50)
        items = [item for item in (catch_up.get("items") or []) if isinstance(item, dict)]
        return FetchResult(items, summary, owner.user_id, owner.display_name, state)
    except ApiClientError as exc:
        log.warning("notifier_ciclo_falhou | detalhe=%s", exc)
        return None
    finally:
        session.close()


# --------------------------------------------------------------- toasts

def plan_toasts(items: list[dict[str, Any]], *, suppress_individual: bool, owner: str = "") -> list[dict[str, str]]:
    """Funcao pura: decide quais toasts disparar para um lote de novidades.

    - `suppress_individual=True` (app principal aberto): nenhum toast — o app
      principal ja mostra o aviso in-app; o agente so mantem o icone/contador.
    - severidade alta/critica: um toast por notificacao, com deep-link proprio.
    - o resto: um unico toast agrupado, sem deep-link.
    - `owner`: para quem e o aviso (ultimo login), mostrado no balao.
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
                    "owner": owner,
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
                    "owner": owner,
                }
            )
        else:
            toasts.append(
                {
                    "title": TOAST_APP_ID,
                    "message": f"{len(grouped)} novas notificacoes",
                    "deep_link": "",
                    "owner": owner,
                }
            )
    return toasts


def _launch_target(deep_link: str) -> str:
    if not is_packaged():
        return ""
    exe = str(get_launcher_path())
    route = (deep_link or "").strip()
    return f'"{exe}" --open {route}' if route else f'"{exe}"'


def _open_main_app(deep_link: str = "") -> None:
    """Abre o programa (ja na rota do aviso, se houver)."""
    if not is_packaged():
        return
    try:
        import subprocess

        args = [str(get_launcher_path())]
        route = (deep_link or "").strip()
        if route:
            args += ["--open", route]
        subprocess.Popen(args)  # noqa: S603
    except OSError:
        log.warning("notifier_abrir_app_falhou")


def _send_toast(title: str, message: str, deep_link: str = "", owner: str = "") -> bool:
    """Tenta exibir o toast. Retorna False se nao foi possivel disparar."""
    from app.services import windows_toast

    icon_path = app_icon_path()
    return windows_toast.show_toast(
        title or TOAST_APP_ID,
        message or "",
        owner=owner,
        deep_link=deep_link,
        icon_path=str(icon_path) if icon_path.exists() else "",
        launch_target=_launch_target(deep_link),
        on_open=_open_main_app,
    )


# --------------------------------------------------------------- ciclo

_TRAY_UPDATER: Callable[[dict[str, Any]], None] | None = None


def set_tray_updater(callback: Callable[[dict[str, Any]], None] | None) -> None:
    global _TRAY_UPDATER
    _TRAY_UPDATER = callback


def _update_tray(summary: dict[str, Any]) -> None:
    if _TRAY_UPDATER is None:
        return
    try:
        _TRAY_UPDATER(summary)
    except Exception:
        log.exception("notifier_tray_update_falhou")


def run_cycle() -> int:
    """Um ciclo do agente. Retorna quantos toasts foram efetivamente exibidos.

    Sempre atualiza o icone da bandeja (mesmo com o app principal aberto);
    so os toasts respeitam `is_main_app_running()`."""
    state = load_state()
    result = _fetch_notifications(state)
    if result is None:
        if creds.load_credential() is None:
            _update_tray({"no_session": True, "total_unread": 0})
            creds.write_status(running=True, owner="", unread=0)
        return 0
    items, summary = result.items, result.summary

    _update_tray(dict(summary, owner_name=result.owner_name))
    creds.write_status(
        running=True,
        owner=result.owner_name,
        user_id=result.user_id,
        unread=int(summary.get("total_unread") or 0),
        last_cycle_at=time.time(),
    )

    if not items:
        return 0

    highest_id = max(int(item.get("id") or 0) for item in items)
    toasts = plan_toasts(items, suppress_individual=is_main_app_running(), owner=result.owner_name)

    shown = 0
    for toast in toasts:
        if _send_toast(toast["title"], toast["message"], toast.get("deep_link", ""), toast.get("owner", "")):
            shown += 1
        else:
            # toast falhou: nao avanca o estado — a novidade continua pendente
            # para o proximo ciclo.
            log.warning("notifier_toast_falhou | mantendo_estado_para_retry")
            return shown

    # Sem toasts (app principal aberto) OU todos exibidos: avanca o ponteiro.
    save_state(NotifierState(last_seen_notification_id=highest_id, user_id=result.user_id))
    if toasts:
        creds.write_status(last_toast_at=time.time())
        log.info("notifier_toasts_exibidos | quantidade=%s | ate_id=%s", shown, highest_id)
    return shown


# --------------------------------------------------------------- bandeja + loop

class NotifierTrayIcon:
    """Icone permanente na bandeja do Windows. So instanciado quando ha um
    QApplication (dentro de run_notifier_loop)."""

    def __init__(self, app, *, on_open, on_quit):
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon

        icon_path = app_icon_path()
        self._icon = QSystemTrayIcon(QIcon(str(icon_path)) if icon_path.exists() else QIcon(), app)
        self._icon.setToolTip(TOAST_APP_ID)
        menu = QMenu()
        menu.addAction("Abrir programa", on_open)
        menu.addSeparator()
        menu.addAction("Sair", on_quit)
        self._icon.setContextMenu(menu)
        self._icon.activated.connect(lambda reason: on_open() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self._icon.show()

    def apply_summary(self, summary: dict[str, Any]) -> None:
        if summary.get("no_session"):
            self._icon.setToolTip(f"{TOAST_APP_ID}\nSem usuario: entre no programa para receber avisos")
            return
        total = int(summary.get("total_unread") or 0)
        owner = str(summary.get("owner_name") or "").strip()
        lines = [TOAST_APP_ID]
        if owner:
            lines.append(f"Avisos de {owner}")
        if total:
            lines.append(f"{total} notificacao(oes) nao lida(s)")
        self._icon.setToolTip("\n".join(lines))


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

    # O Updater pede a saida de todos os processos do app antes de ativar a versao nova.
    from app.services.update_quit_watcher import install_quit_watcher

    install_quit_watcher(app, app.quit)

    tray = NotifierTrayIcon(app, on_open=_open_main_app, on_quit=app.quit)
    set_tray_updater(tray.apply_summary)

    realtime = _NotifierRealtime(on_event=_run_cycle_safe)
    realtime.start()

    timer = QTimer()
    timer.timeout.connect(_run_cycle_safe)
    timer.start(max(10, poll_interval) * 1000)

    QTimer.singleShot(0, _run_cycle_safe)
    creds.write_status(running=True, started_at=time.time())
    log.info("notifier_iniciado | intervalo_segundos=%s", poll_interval)
    try:
        app.exec()
    finally:
        creds.write_status(running=False)
        realtime.stop()
        set_tray_updater(None)


def _run_cycle_safe() -> None:
    try:
        run_cycle()
    except Exception:
        log.exception("notifier_ciclo_erro_inesperado")


class _NotifierRealtime:
    """WebSocket minimo e reconectavel: qualquer evento `notification.*`
    dispara um ciclo imediato (o corpo vem por REST no ciclo). Usa
    /api/v1/notifier/ws, autenticado pela credencial do computador."""

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
            session = _open_session()
            if session is None:
                # Sem login guardado (ou apagado por credencial recusada): volta
                # a olhar mais tarde para reconectar depois do proximo login.
                self._schedule_reconnect()
                return
            try:
                settings = DesktopApiConfigStore().load_settings()
                base = normalize_api_base_url(settings.base_url)
                ws_url = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/api/v1/notifier/ws"
                request = QNetworkRequest(QUrl(ws_url))
                request.setRawHeader(b"Authorization", f"Bearer {session.access_token}".encode("utf-8"))
                self._socket.open(request)
            finally:
                session.close()
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


# --------------------------------------------------------------- inicializacao

def ensure_notifier_running() -> bool:
    """Liga o agente se ele nao estiver rodando (apos atualizacao, falha ou
    reinicio sem login). Chamado pelo app principal ao abrir. Retorna True se
    iniciou um novo."""
    if not is_packaged() or sys.platform != "win32" or is_notifier_running():
        return False
    try:
        import subprocess

        subprocess.Popen(  # noqa: S603
            [str(get_launcher_path()), "--notifier"],
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            close_fds=True,
        )
        log.info("notifier_religado_pelo_app_principal")
        return True
    except OSError:
        log.warning("notifier_religar_falhou")
        return False


def ensure_startup_registration() -> None:
    """Registra (idempotente) o modo --notifier para iniciar com o Windows.

    Usa a chave Run do usuario (HKCU), que nao depende de pasta nem de script;
    remove o .bat antigo da pasta Startup para nao iniciar duas vezes."""
    if not is_packaged() or sys.platform != "win32":
        return
    import os

    exe_path = get_launcher_path()
    expected = f'"{exe_path}" --notifier'
    try:
        import winreg

        access = winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, access) as key:
            try:
                current, _kind = winreg.QueryValueEx(key, STARTUP_RUN_VALUE_NAME)
            except FileNotFoundError:
                current = None
            if current != expected:
                winreg.SetValueEx(key, STARTUP_RUN_VALUE_NAME, 0, winreg.REG_SZ, expected)
                log.info("notifier_startup_registrado | chave=Run | comando=%s", expected)
    except OSError:
        log.warning("notifier_startup_registro_falhou")
        return

    appdata = os.environ.get("APPDATA")
    if appdata:
        legacy = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / STARTUP_SCRIPT_NAME
        try:
            legacy.unlink(missing_ok=True)
        except OSError:
            log.warning("notifier_startup_legado_nao_removido")
