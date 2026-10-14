"""Launcher: abre a versao ativa e sai (ver app/updater/versions.py)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.updater.versions import APP_EXECUTABLE_NAME, resolve_active_version, version_dir

_ERROR_TITLE = "Controle de Producao Industel"


def _show_error(message: str) -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, _ERROR_TITLE, 0x10)
            return
        except Exception:  # noqa: BLE001 - ultimo recurso, nada mais a tentar
            pass
    print(message, file=sys.stderr)


def install_root_from_executable(executable: str | Path) -> Path:
    return Path(executable).resolve().parent


def launch(install_root: Path, args: list[str], *, popen=subprocess.Popen) -> int:
    # Durante a atualizacao automatica (--post-update) quem relata a falha e o
    # Updater (com rollback); uma caixa de mensagem aqui ficaria presa na tela.
    show_error = _show_error if "--post-update" not in args else (lambda message: print(message, file=sys.stderr))
    version = resolve_active_version(install_root)
    if version is None:
        show_error(
            "Nenhuma versao do programa foi encontrada.\n"
            "Execute o instalador do Controle de Producao para reparar a instalacao."
        )
        return 1
    app_dir = version_dir(install_root, version)
    try:
        popen(
            [str(app_dir / APP_EXECUTABLE_NAME), *args],
            cwd=str(install_root),
            close_fds=True,
        )
    except OSError as exc:
        show_error(f"Nao foi possivel abrir a versao {version}:\n{exc}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    return launch(install_root_from_executable(sys.executable), args)


if __name__ == "__main__":
    raise SystemExit(main())
