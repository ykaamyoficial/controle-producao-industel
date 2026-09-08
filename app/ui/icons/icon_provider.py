"""IconProvider: resolve (AppIcons, tamanho, cor) num QIcon renderizado a
partir do SVG Lucide vendorizado, com cache e re-coloracao por tema.

Os SVGs da Lucide vem com `stroke="currentColor"`; a re-coloracao por tema e
feita trocando essa string pela cor resolvida antes de passar pro
QSvgRenderer - evita duplicar arquivo por tema (regra do PDF).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import icon_cache
from .icon_registry import LUCIDE_DIR, lucide_slug
from .icon_tokens import IconColorRole, IconState, resolve_color
from .semantic_icons import AppIcons

log = logging.getLogger(__name__)

_MISSING_LOGGED: set[str] = set()
# Sem devicePixelRatio > 1 aqui de proposito: varias telas extraem o pixmap
# bruto do QIcon (`make_icon(...).pixmap(w, h)`) pra colar direto num QLabel,
# fora do mecanismo de escala por-DPI do QIcon/QPushButton. Um pixmap marcado
# com devicePixelRatio=2 nessas telas aparecia cortado (so o canto superior
# esquerdo, ~1/4 do icone) porque o QLabel desenha o buffer fisico 2x maior
# sem reescalar. Como o icone vem de SVG, renderizar direto no tamanho pedido
# ja fica nitido sem precisar desse truque de alta-resolucao.
_RENDER_DPR = 1.0


def _log_missing_once(key: str, message: str) -> None:
    if key not in _MISSING_LOGGED:
        log.warning(message)
        _MISSING_LOGGED.add(key)


def _colored_svg_bytes(slug: str, color: str) -> bytes | None:
    path = LUCIDE_DIR / f"{slug}.svg"
    if not path.exists():
        _log_missing_once(slug, f"Asset Lucide ausente para '{slug}' em {path}")
        return None
    raw = path.read_text(encoding="utf-8")
    colored = raw.replace('stroke="currentColor"', f'stroke="{color}"')
    return colored.encode("utf-8")


def render_pixmap(icon: AppIcons, size: int, color: str, dpr: float = _RENDER_DPR) -> QPixmap | None:
    slug = lucide_slug(icon)
    if slug is None:
        _log_missing_once(f"registry:{icon}", f"AppIcons.{getattr(icon, 'name', icon)} sem entrada em ICON_REGISTRY")
        return None

    cache_key = (slug, size, color, round(dpr, 2))
    cached = icon_cache.get(cache_key)
    if cached is not None:
        return cached

    svg_bytes = _colored_svg_bytes(slug, color)
    if svg_bytes is None:
        return None

    renderer = QSvgRenderer(svg_bytes)
    if not renderer.isValid():
        _log_missing_once(f"invalid:{slug}", f"SVG invalido para '{slug}'")
        return None

    physical = max(1, round(size * dpr))
    pixmap = QPixmap(physical, physical)
    pixmap.fill(Qt.transparent)
    pixmap.setDevicePixelRatio(dpr)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()

    icon_cache.put(cache_key, pixmap)
    return pixmap


def get_icon(icon: AppIcons, size: int, color: str) -> QIcon | None:
    pixmap = render_pixmap(icon, size, color)
    if pixmap is None:
        return None
    return QIcon(pixmap)


def resolve_icon(
    icon: AppIcons,
    size: int,
    color_role: IconColorRole,
    palette: dict | None,
    state: IconState = IconState.NORMAL,
) -> QIcon | None:
    effective_role = IconColorRole.DISABLED if state == IconState.DISABLED else color_role
    color = resolve_color(effective_role, palette)
    return get_icon(icon, size, color)
