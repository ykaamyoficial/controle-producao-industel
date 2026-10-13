from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PySide6.QtGui import QIcon


APP_USER_MODEL_ID = "Industel.ControleProducao.2"


def app_icon_path() -> Path:
    base = Path(__file__).resolve().parents[1]
    return base / "assets" / "images" / "Logo_Industel_Icone.ico"


def toast_icon_path() -> Path:
    """Logo do balao do Windows. O .ico guarda varios tamanhos e o Windows pega o
    menor quadro dele para o logo do balao (fica borrado); o PNG de 256 px e o
    mesmo desenho em alta resolucao. Se faltar, volta ao .ico."""
    png = app_icon_path().with_name("Logo_Industel_Icone_256.png")
    return png if png.exists() else app_icon_path()


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
