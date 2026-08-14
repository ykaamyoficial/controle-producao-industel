"""Controle de processo do Updater (Fase 10, Secao 9/18/23).

O Updater sobrevive ao fechamento do Desktop (processo independente) e
prioriza encerramento cooperativo: so espera o parent_pid sair, nunca mata
por padrao. Forcar encerramento e uma acao explicita, separada, nunca chamada
implicitamente pelo fluxo padrao.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259


def is_process_running(pid: int) -> bool:
    if pid is None or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    else:
        import os
        import errno

        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError as exc:
            return exc.errno != errno.ESRCH
        return True


def wait_for_process_exit(pid: int, *, timeout_seconds: float, poll_interval_seconds: float = 0.5) -> bool:
    """Espera cooperativamente (Secao 18) -- nunca mata o processo. Retorna
    True se o processo ja nao estiver mais rodando dentro do timeout."""
    if not is_process_running(pid):
        return True
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not is_process_running(pid):
            return True
        time.sleep(poll_interval_seconds)
    return not is_process_running(pid)


def terminate_process_forcefully(pid: int) -> bool:
    """Encerramento forcado -- SOMENTE chamado mediante politica explicita do
    orquestrador (Secao 18: 'nunca como comportamento silencioso padrao'),
    nunca automaticamente pelo fluxo comum."""
    if sys.platform != "win32":
        import os
        import signal

        try:
            os.kill(pid, signal.SIGKILL)
            return True
        except OSError:
            return False

    import ctypes

    _PROCESS_TERMINATE = 0x0001
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(_PROCESS_TERMINATE, False, pid)
    if not handle:
        return False
    try:
        return bool(kernel32.TerminateProcess(handle, 1))
    finally:
        kernel32.CloseHandle(handle)


def launch_detached_process(executable_path: Path, args: list[str] | None = None, *, cwd: Path | None = None) -> int:
    """Inicia um processo independente (sobrevive ao encerramento do
    processo que o lancou) e retorna o PID -- usado tanto para reabrir o
    Desktop (Secao 23) quanto, futuramente, para o Desktop lancar o Updater."""
    command = [str(executable_path), *(args or [])]
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd else None,
        creationflags=creationflags,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return process.pid
