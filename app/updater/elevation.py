"""Elevacao administrativa sob demanda (Fase 10, pendencia da Secao 17).

PRECHECK_LOCAL ja detectava falta de permissao de escrita em `install_dir`
(normalmente `Program Files`, que exige admin) e falhava com uma mensagem
clara -- mas nao tentava resolver o problema sozinho. Em maquinas onde o
usuario Windows logado nao e administrador (comum em estacoes corporativas),
toda atualizacao silenciosa falhava sempre, exigindo reinstalacao manual.

Este modulo fecha essa lacuna: antes de processar o request, o Updater
verifica se `install_dir` e gravavel; se nao for E o processo atual nao for
elevado, tenta relançar a si mesmo via UAC (`ShellExecuteW` com verbo
"runas") e encerra a instancia nao-elevada. Se o usuario recusar o prompt UAC
(ou a elevacao falhar por qualquer motivo), o fluxo normal continua e
PRECHECK_LOCAL reprova com a mensagem ja existente -- nenhum comportamento
anterior foi removido, isto e so uma tentativa adicional antes de desistir.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path

log = logging.getLogger("controle_producao.updater")


def is_admin() -> bool:
    """True se o processo atual ja roda com privilegios administrativos."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        # Nao-Windows (testes) -- nunca elevamos fora do Windows.
        return True


def is_writable(directory: Path) -> bool:
    probe_dir = directory if directory.exists() else directory.parent
    if not probe_dir.exists():
        return False
    probe = probe_dir / ".updater-elevation-check.tmp"
    try:
        probe.write_text("x", encoding="utf-8")
        return True
    except OSError:
        return False
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass


def relaunch_elevated(argv: list[str]) -> bool:
    """Relanca o proprio Updater elevado (prompt UAC) com os mesmos
    argumentos. Retorna True se o SO aceitou lancar o processo elevado
    (nao espera o resultado -- o processo atual deve encerrar em seguida).
    Retorna False se o usuario recusou o UAC ou a elevacao falhou."""
    try:
        if getattr(sys, "frozen", False):
            executable = sys.executable
            params = " ".join(f'"{arg}"' for arg in argv)
        else:
            executable = sys.executable
            params = " ".join(f'"{arg}"' for arg in ["-m", "app.updater", *argv])

        result = ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
            None, "runas", executable, params, None, 1,
        )
        # ShellExecuteW retorna um valor > 32 em caso de sucesso.
        return int(result) > 32
    except (AttributeError, OSError) as exc:
        log.warning("update_elevation_relaunch_failed | erro=%s", exc)
        return False
