"""Tokens centralizados de tamanho, cor semantica, estado e motion para o
sistema de icones. Nao permitir que uma tela escolha tamanho/cor arbitrarios
por conta propria - toda resolucao passa por aqui.
"""

from __future__ import annotations

from enum import Enum, IntEnum


class IconSize(IntEnum):
    XS = 14
    SM = 16
    MD = 18
    LG = 20
    NAV = 24
    EMPTY = 48
    TABLE_STATUS = 15


class IconColorRole(Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    MUTED = "muted"
    ON_ACCENT = "on_accent"
    SUCCESS = "success"
    WARNING = "warning"
    DANGER = "danger"
    INFO = "info"
    DISABLED = "disabled"


class IconState(Enum):
    NORMAL = "normal"
    HOVER = "hover"
    PRESSED = "pressed"
    SELECTED = "selected"
    FOCUSED = "focused"
    DISABLED = "disabled"


class IconMotion(Enum):
    NONE = "none"
    PULSE = "pulse"
    SHAKE = "shake"
    ROTATE = "rotate"
    BOUNCE = "bounce"
    FADE = "fade"
    SCALE = "scale"
    SUCCESS = "success"


# IconColorRole -> chave existente em OFFICIAL_COLOR_PALETTES (app/services/backend_adapter.py).
# Nao inventa cor nova: reaproveita os tokens que a paleta ja expoe pro resto da UI.
_ROLE_TO_PALETTE_KEY = {
    IconColorRole.PRIMARY: "accent",
    IconColorRole.SECONDARY: "secondary",
    IconColorRole.MUTED: "muted",
    IconColorRole.ON_ACCENT: "accent_text",
    IconColorRole.SUCCESS: "success",
    IconColorRole.WARNING: "warning",
    IconColorRole.DANGER: "danger",
    IconColorRole.INFO: "info",
    IconColorRole.DISABLED: "disabled",
}

_FALLBACK_HEX = {
    IconColorRole.PRIMARY: "#2563eb",
    IconColorRole.SECONDARY: "#64748b",
    IconColorRole.MUTED: "#94a3b8",
    IconColorRole.ON_ACCENT: "#ffffff",
    IconColorRole.SUCCESS: "#16a34a",
    IconColorRole.WARNING: "#d97706",
    IconColorRole.DANGER: "#dc2626",
    IconColorRole.INFO: "#0284c7",
    IconColorRole.DISABLED: "#94a3b8",
}


def resolve_color(role: IconColorRole, palette: dict | None) -> str:
    key = _ROLE_TO_PALETTE_KEY.get(role)
    if palette and key and palette.get(key):
        return palette[key]
    return _FALLBACK_HEX.get(role, "#2563eb")
