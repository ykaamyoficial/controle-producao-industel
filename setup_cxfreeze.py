from __future__ import annotations

from pathlib import Path

from cx_Freeze import Executable, setup


ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / "app"
ICON_FILE = APP_DIR / "assets" / "images" / "Logo_Industel_Icone.ico"


build_exe_options = {
    "build_exe": str(ROOT / "gerados" / "Controle Producao 2.0"),
    "packages": [
        "app",
        "sqlite3",
        "tkinter",
        "PySide6",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtPrintSupport",
    ],
    "includes": [
        "hmac",
        "hashlib",
        "secrets",
        "json",
        "datetime",
        "pathlib",
        "shutil",
    ],
    "include_files": [
        (str(APP_DIR / "assets"), "app/assets"),
        (str(APP_DIR / "config"), "app/config"),
    ],
    "include_msvcr": True,
    "excludes": [
        "pytest",
        "unittest",
        "email",
        "html",
        "http",
    ],
}


setup(
    name="Controle Producao Industel",
    version="2.0.0",
    description="Controle de Producao Industel",
    options={"build_exe": build_exe_options},
    executables=[
        Executable(
            script=str(APP_DIR / "main.py"),
            base="Win32GUI",
            target_name="Controle Producao Industel 2.0.exe",
            icon=str(ICON_FILE),
        )
    ],
)
