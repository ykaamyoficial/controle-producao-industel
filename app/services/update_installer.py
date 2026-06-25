from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from shutil import copy2

from app.services.app_paths import get_app_data_dir


class UpdateInstallError(RuntimeError):
    pass


def _database_path() -> Path:
    return get_app_data_dir() / "controle_producao.db"


def _backup_dir() -> Path:
    return get_app_data_dir() / "backups" / "pre_update"


def _validate_sqlite_database(db_path: Path) -> None:
    if not db_path.exists():
        return

    try:
        with sqlite3.connect(str(db_path)) as conn:
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

    _validate_sqlite_database(db_path)

    destination_dir = _backup_dir()
    destination_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_version = str(target_version or "nova").replace(".", "_")
    backup_path = destination_dir / f"controle_producao_pre_update_{safe_version}_{stamp}.db"

    try:
        copy2(db_path, backup_path)
    except OSError as exc:
        raise UpdateInstallError(f"Nao foi possivel criar backup antes da atualizacao: {exc}") from exc

    if not backup_path.exists() or backup_path.stat().st_size <= 0:
        raise UpdateInstallError("Backup pre-atualizacao nao foi criado corretamente.")

    _validate_sqlite_database(backup_path)
    return backup_path


def _program_executable_path() -> Path:
    return Path(r"C:\Program Files\Industel\Controle de Producao\ControleProducao.exe")


def _create_restart_script() -> Path:
    updates_dir = get_app_data_dir() / "updates"
    updates_dir.mkdir(parents=True, exist_ok=True)

    exe_path = _program_executable_path()
    script_path = updates_dir / "restart_after_update.bat"

    script_path.write_text(
        "@echo off\n"
        "timeout /t 8 /nobreak >nul\n"
        f'start "" "{exe_path}"\n',
        encoding="utf-8",
    )
    return script_path


def run_silent_installer(installer_path: str | Path) -> None:
    installer = Path(installer_path)
    if not installer.exists():
        raise UpdateInstallError(f"Instalador nao encontrado: {installer}")

    restart_script = _create_restart_script()

    args = [
        str(installer),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/CLOSEAPPLICATIONS",
    ]

    try:
        subprocess.Popen(args, shell=False)
        subprocess.Popen(["cmd.exe", "/c", str(restart_script)], shell=False)
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