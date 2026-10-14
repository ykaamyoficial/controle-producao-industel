from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
APP_DIR = ROOT_DIR / "app"
CONFIG_FILE_NAME = "controle_producao_config.json"
CONFIG_EXAMPLE_FILE_NAME = "controle_producao_config.example.json"


def is_packaged() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_install_root() -> Path:
    """Raiz da instalacao (onde fica o launcher). No layout versionado o exe
    roda em <raiz>/versions/<v>/; no layout antigo (plano) a raiz e a propria
    pasta do exe. Fora do pacote PyInstaller devolve a raiz do repositorio."""
    if not is_packaged():
        return ROOT_DIR
    exe_dir = Path(sys.executable).resolve().parent
    if exe_dir.parent.name == "versions":
        return exe_dir.parent.parent
    return exe_dir


def get_launcher_path() -> Path:
    """Executavel que atalhos/Startup/toasts devem apontar. Estavel entre
    versoes (no layout antigo e o proprio exe)."""
    if not is_packaged():
        return Path(sys.executable)
    root = get_install_root()
    launcher = root / "ControleProducao.exe"
    if launcher.is_file():
        return launcher
    return Path(sys.executable).resolve()


def get_program_data_root() -> Path:
    override = os.environ.get("CONTROLE_PRODUCAO_DATA_DIR")
    if override:
        return Path(override)
    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    return Path(program_data) / "Industel" / "ControleProducao"


def get_app_data_dir() -> Path:
    if is_packaged():
        return get_program_data_root()
    return APP_DIR / "data"


def get_config_path() -> Path:
    if is_packaged():
        return get_app_data_dir() / CONFIG_FILE_NAME
    return APP_DIR / "config" / CONFIG_FILE_NAME


def get_updates_dir() -> Path:
    return get_app_data_dir() / "updates"


def get_logs_dir() -> Path:
    override = os.environ.get("CONTROLE_PRODUCAO_LOG_DIR")
    if override:
        return Path(override)
    if is_packaged():
        app_data = os.environ.get("APPDATA")
        if app_data:
            return Path(app_data) / "ControleProducao" / "logs"
    return get_app_data_dir() / "logs"


def get_diagnostics_dir() -> Path:
    return get_app_data_dir() / "diagnostics"


def get_config_example_path() -> Path:
    if is_packaged():
        base_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        return base_dir / "app" / "config" / CONFIG_EXAMPLE_FILE_NAME
    return APP_DIR / "config" / CONFIG_EXAMPLE_FILE_NAME


def ensure_app_data_dirs() -> None:
    get_app_data_dir().mkdir(parents=True, exist_ok=True)
    get_updates_dir().mkdir(parents=True, exist_ok=True)
    get_logs_dir().mkdir(parents=True, exist_ok=True)
    get_diagnostics_dir().mkdir(parents=True, exist_ok=True)
    get_config_path().parent.mkdir(parents=True, exist_ok=True)
