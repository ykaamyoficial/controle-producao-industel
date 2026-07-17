from __future__ import annotations

import sqlite3
import subprocess
import sys
import os
from contextlib import closing
from pathlib import Path

from app.services.app_logging import get_logger
from app.services.app_paths import get_app_data_dir, get_logs_dir
from app.services.sqlite_safety import safe_backup
from app.services.update_state import write_pending_update
from app.version import APP_VERSION


class UpdateInstallError(RuntimeError):
    pass


log = get_logger("updates.installer")


def _database_path() -> Path:
    return get_app_data_dir() / "controle_producao.db"


def _backup_dir() -> Path:
    return get_app_data_dir() / "backups" / "pre_update"


def _validate_sqlite_database(db_path: Path) -> None:
    if not db_path.exists():
        return

    try:
        with closing(sqlite3.connect(str(db_path))) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise UpdateInstallError(f"Banco com integrity_check invalido: {integrity}")

            foreign_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_errors:
                raise UpdateInstallError(f"Banco com problemas de foreign key: {foreign_errors}")
    except sqlite3.Error as exc:
        raise UpdateInstallError(f"Nao foi possivel validar o banco antes da atualizacao: {exc}") from exc


def create_pre_update_backup(target_version: str) -> Path | None:
    db_path = _database_path()
    if not db_path.exists():
        return None

    destination_dir = _backup_dir()
    safe_version = str(target_version or "nova").replace(".", "_")
    try:
        backup_path = safe_backup(db_path, destination_dir, f"pre_update_{safe_version}")
    except Exception as exc:
        raise UpdateInstallError(f"Nao foi possivel criar backup antes da atualizacao: {exc}") from exc
    return backup_path


def _program_executable_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return Path(r"C:\Program Files\Industel\Controle de Producao\ControleProducao.exe")


def _quote_ps(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _create_update_runner(installer_path: Path, *, wait_pid: int | None = None) -> Path:
    updates_dir = get_app_data_dir() / "updates"
    updates_dir.mkdir(parents=True, exist_ok=True)

    exe_path = _program_executable_path()
    log_path = get_logs_dir() / "atualizacao_instalador.log"
    script_path = updates_dir / "run_update_hidden.ps1"
    pid = wait_pid or os.getpid()

    script_path.write_text(
        "$ErrorActionPreference = 'SilentlyContinue'\n"
        f"$pidToWait = {int(pid)}\n"
        "try { Wait-Process -Id $pidToWait -Timeout 90 } catch { Start-Sleep -Seconds 3 }\n"
        f"$installer = {_quote_ps(installer_path)}\n"
        f"$appExe = {_quote_ps(exe_path)}\n"
        f"$installLog = {_quote_ps(log_path)}\n"
        "$args = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CLOSEAPPLICATIONS', \"/LOG=$installLog\")\n"
        "try {\n"
        "    $process = Start-Process -FilePath $installer -ArgumentList $args -Wait -PassThru\n"
        "    Start-Sleep -Seconds 2\n"
        "    if (Test-Path $appExe) { Start-Process -FilePath $appExe }\n"
        "} catch {\n"
        "    Add-Content -Path $installLog -Value $_.Exception.Message\n"
        "}\n",
        encoding="utf-8",
    )
    return script_path


def _hidden_subprocess_options() -> dict:
    if sys.platform.startswith("win"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def run_silent_installer(
    installer_path: str | Path,
    *,
    target_version: str | None = None,
    sha256: str | None = None,
    backup_path: str | None = None,
) -> None:
    installer = Path(installer_path)
    if not installer.exists():
        raise UpdateInstallError(f"Instalador nao encontrado: {installer}")

    target = target_version or "nova"
    runner_script = _create_update_runner(installer, wait_pid=os.getpid())

    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-WindowStyle",
        "Hidden",
        "-File",
        str(runner_script),
    ]

    try:
        subprocess.Popen(args, shell=False, **_hidden_subprocess_options())
        write_pending_update(
            target_version=target,
            current_version=APP_VERSION,
            installer_path=installer,
            sha256=sha256,
            backup_path=backup_path,
        )
        log.info("Instalador silencioso agendado | destino=%s | runner=%s", target, runner_script)
    except OSError as exc:
        raise UpdateInstallError(f"Nao foi possivel iniciar o instalador: {exc}") from exc

    app = None
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
    except Exception:
        app = None

    if app:
        app.quit()
    else:
        sys.exit(0)
