"""Balao nativo do Windows para o agente de avisos.

Usa `windows-toasts` (WinRT direto: botoes, nome/icone proprios, clique tratado
dentro do proprio agente, que fica sempre em execucao). Se a biblioteca nao
estiver disponivel no pacote, cai no `winotify` — o mesmo caminho que ja
funcionava — sem perder o aviso.
"""

from __future__ import annotations

import threading
from typing import Callable

from app.services.app_logging import get_logger


log = get_logger("windows_toast")

# Mesmo AUMID de sempre: preserva as escolhas que o usuario ja fez em
# Configuracoes > Notificacoes do Windows.
TOAST_APP_ID = "Controle de Producao Industel"
OPEN_BUTTON_LABEL = "Abrir"

_toaster = None
_toaster_failed = False
_lock = threading.Lock()
# O WinRT chama os callbacks de ativacao enquanto o objeto estiver vivo.
_alive: list = []


def register_aumid(icon_path: str = "") -> None:
    """Registra o nome e o icone do app para o Windows (HKCU, sem admin). Sem
    isso o balao aparece com o nome/icone de outro programa."""
    try:
        import winreg

        key_path = rf"Software\Classes\AppUserModelId\{TOAST_APP_ID}"
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, TOAST_APP_ID)
            if icon_path:
                winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, icon_path)
            winreg.SetValueEx(key, "ShowInSettings", 0, winreg.REG_DWORD, 1)
    except Exception:
        log.warning("toast_aumid_registro_falhou", exc_info=True)


def _get_toaster(icon_path: str):
    global _toaster, _toaster_failed
    if _toaster is not None or _toaster_failed:
        return _toaster
    with _lock:
        if _toaster is not None or _toaster_failed:
            return _toaster
        try:
            from windows_toasts import InteractableWindowsToaster

            register_aumid(icon_path)
            _toaster = InteractableWindowsToaster(TOAST_APP_ID, TOAST_APP_ID)
        except Exception:
            _toaster_failed = True
            log.warning("toast_windows_toasts_indisponivel | usando_winotify", exc_info=True)
    return _toaster


def _show_with_windows_toasts(
    title: str,
    message: str,
    owner: str,
    deep_link: str,
    icon_path: str,
    on_open: Callable[[str], None] | None,
) -> bool:
    toaster = _get_toaster(icon_path)
    if toaster is None:
        return False
    from windows_toasts import Toast, ToastButton, ToastDisplayImage, ToastDuration, ToastImagePosition

    lines = [title or TOAST_APP_ID, message or ""]
    if owner:
        lines.append(f"Para: {owner}")
    toast = Toast(text_fields=[line for line in lines if line], duration=ToastDuration.Long)
    toast.AddAction(ToastButton(OPEN_BUTTON_LABEL, arguments="open"))
    if icon_path:
        try:
            toast.AddImage(ToastDisplayImage.fromPath(icon_path, position=ToastImagePosition.AppLogo))
        except Exception:
            log.debug("toast_icone_ignorado", exc_info=True)

    def _activated(_args) -> None:
        # Corpo do balao e botao "Abrir" fazem a mesma coisa.
        if on_open is not None:
            try:
                on_open(deep_link)
            except Exception:
                log.exception("toast_abrir_falhou")

    toast.on_activated = _activated
    toaster.show_toast(toast)
    _alive.append(toast)
    del _alive[:-20]
    return True


def _show_with_winotify(title: str, message: str, owner: str, launch: str, icon_path: str) -> bool:
    try:
        from winotify import Notification
    except ImportError:
        log.warning("notifier_winotify_indisponivel")
        return False
    msg = message or ""
    if owner:
        msg = f"{msg}\nPara: {owner}".strip()
    Notification(
        app_id=TOAST_APP_ID,
        title=title or TOAST_APP_ID,
        msg=msg,
        icon=icon_path,
        duration="long",
        launch=launch,
    ).show()
    return True


def show_toast(
    title: str,
    message: str,
    *,
    owner: str = "",
    deep_link: str = "",
    icon_path: str = "",
    launch_target: str = "",
    on_open: Callable[[str], None] | None = None,
) -> bool:
    """Mostra o balao. Retorna False se nenhum dos dois caminhos conseguiu."""
    try:
        if _show_with_windows_toasts(title, message, owner, deep_link, icon_path, on_open):
            return True
    except Exception:
        log.warning("toast_windows_toasts_falhou | tentando_winotify", exc_info=True)
    try:
        return _show_with_winotify(title, message, owner, launch_target, icon_path)
    except Exception:
        log.exception("notifier_toast_erro_ao_exibir")
        return False
