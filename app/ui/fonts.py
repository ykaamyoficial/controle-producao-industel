"""Fonte da interface: Inter embutida em `app/assets/fonts/` (licenca OFL,
ver `Inter-LICENSE.txt` na mesma pasta), com Segoe UI como reserva.

A folha de estilo (`app/ui/styles.py`) ja pede "Inter" primeiro; este modulo
so registra os arquivos no Qt. Se a pasta nao existir ou um arquivo falhar ao
carregar, o Qt cai sozinho para Segoe UI - nunca impede o app de abrir.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QFontDatabase

log = logging.getLogger(__name__)

FONTS_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
UI_FONT_FAMILY = "Inter"
FALLBACK_FONT_FAMILY = "Segoe UI"

_loaded_family: str | None = None


def load_app_fonts() -> str:
    """Registra as fontes embutidas (uma vez por processo) e devolve a
    familia que a interface vai usar de fato. Requer QApplication criada."""
    global _loaded_family
    if _loaded_family is not None:
        return _loaded_family
    families: set[str] = set()
    for font_file in sorted(FONTS_DIR.glob("*.ttf")) if FONTS_DIR.is_dir() else []:
        font_id = QFontDatabase.addApplicationFont(str(font_file))
        if font_id < 0:
            log.warning("Fonte embutida nao carregou: %s", font_file.name)
            continue
        families.update(QFontDatabase.applicationFontFamilies(font_id))
    _loaded_family = UI_FONT_FAMILY if UI_FONT_FAMILY in families else FALLBACK_FONT_FAMILY
    if _loaded_family != UI_FONT_FAMILY:
        log.warning("Fonte %s indisponivel; usando %s", UI_FONT_FAMILY, FALLBACK_FONT_FAMILY)
    return _loaded_family


def ui_font_family() -> str:
    """Familia em uso, para componentes pintados a mao (QFont explicito)."""
    return _loaded_family or FALLBACK_FONT_FAMILY
