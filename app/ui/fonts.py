"""Fonte da interface: Inter embutida em `app/assets/fonts/` (licenca OFL,
ver `Inter-LICENSE.txt` na mesma pasta), com Segoe UI como reserva.

A folha de estilo (`app/ui/styles.py`) ja pede "Inter" primeiro; este modulo
so registra os arquivos no Qt. Se a pasta nao existir ou um arquivo falhar ao
carregar, o Qt cai sozinho para Segoe UI - nunca impede o app de abrir.
"""

from __future__ import annotations

import logging
import re
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


# ---- escala da fonte -------------------------------------------------------
# Todo o texto do programa, menos os titulos, e um pouco menor que o desenho
# original (pedido do usuario em 08/10/2026). Muda so este numero para ajustar.
FONT_SCALE = 0.92
MIN_FONT_PX = 9

_QSS_BLOCK = re.compile(r"([^{}]+)\{([^{}]*)\}")
_QSS_FONT_SIZE = re.compile(r"(font-size:\s*)(\d+(?:\.\d+)?)px")
# Regras cujo seletor tem objectName terminado em Title/Heading mantem o tamanho.
_TITLE_SELECTOR = re.compile(r"#\w*(?:Title|Heading)\b")


def scaled_px(px: float) -> int:
    """Tamanho de fonte em pixels depois da escala (para componentes pintados)."""
    return max(MIN_FONT_PX, round(px * FONT_SCALE))


def scale_qss_fonts(qss: str) -> str:
    """Aplica a escala a todo `font-size: Npx` da folha de estilo, exceto nas
    regras de titulo (FilterTitle, DetailTitle, PanelTitle, ...)."""

    def scale_block(match: re.Match) -> str:
        selector, body = match.group(1), match.group(2)
        if _TITLE_SELECTOR.search(selector):
            return match.group(0)
        body = _QSS_FONT_SIZE.sub(lambda m: f"{m.group(1)}{scaled_px(float(m.group(2)))}px", body)
        return f"{selector}{{{body}}}"

    return _QSS_BLOCK.sub(scale_block, qss)
