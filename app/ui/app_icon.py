from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PySide6.QtGui import QIcon


APP_USER_MODEL_ID = "Industel.ControleProducao.2"


def app_icon_path() -> Path:
    base = Path(__file__).resolve().parents[1]
    return base / "assets" / "images" / "Logo_Industel_Icone.ico"


def app_icon() -> QIcon:
    path = app_icon_path()
    return QIcon(str(path)) if path.exists() else QIcon()


def configure_windows_taskbar_icon() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass
