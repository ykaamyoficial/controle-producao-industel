"""Mapeamento semantico -> arquivo Lucide vendorizado em
app/assets/icons/lucide/<nome>.svg (baixados uma unica vez do repositorio
oficial lucide-icons/lucide, ISC license; nunca baixados em runtime).

Onde o nome exato do PDF nao existe mais na versao atual da biblioteca,
uso o equivalente mais proximo (comentado abaixo), preservando o conceito -
regra explicita da secao 5 do PDF.
"""

from __future__ import annotations

from pathlib import Path

from .semantic_icons import AppIcons

LUCIDE_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons" / "lucide"

ICON_REGISTRY: dict[AppIcons, str] = {
    AppIcons.DASHBOARD: "layout-dashboard",
    AppIcons.CONTROL: "clipboard-check",
    AppIcons.PRODUCTION: "factory",
    AppIcons.GALVANIZATION: "layers",
    AppIcons.EXPEDITION: "truck",
    AppIcons.STOCK: "warehouse",
    AppIcons.FISCAL: "receipt-text",
    AppIcons.PARTIAL: "package-open",
    AppIcons.HISTORY: "file-clock",  # "history" foi removido da lib atual
    AppIcons.AUDIT: "shield-check",
    AppIcons.REPORTS: "chart-column",  # renomeado de "bar-chart-3"

    AppIcons.SETTINGS: "settings",
    AppIcons.USERS: "circle-user",
    AppIcons.BACKUP: "archive",
    AppIcons.RESTORE: "archive-restore",
    AppIcons.WINDOW_RESTORE: "copy",
    AppIcons.DATABASE: "database",
    AppIcons.ADMIN_CORRECTION: "shield-alert",  # "shield-pen" nao existe na lib atual

    AppIcons.CHAT: "message-circle",
    AppIcons.BELL: "bell",
    AppIcons.NOTIFICATION: "bell",
    AppIcons.QUESTION: "circle-question-mark",  # renomeado de "circle-help"
    AppIcons.AT: "at-sign",
    AppIcons.MENTION: "at-sign",
    AppIcons.REPLY: "reply",
    AppIcons.SEND: "send",
    AppIcons.ATTACH: "paperclip",
    AppIcons.MIC: "mic",
    AppIcons.EMOJI: "sticker",  # "smile" nao existe na lib atual
    AppIcons.ARROW_DOWN: "arrow-down",
    AppIcons.CHECK: "check",
    AppIcons.CHECK_DOUBLE: "check-check",

    AppIcons.SEARCH: "search",
    AppIcons.CLEAR: "x",
    AppIcons.CLOSE: "x",
    AppIcons.WINDOW_CLOSE: "x",
    AppIcons.NEW: "plus",
    AppIcons.EDIT: "pencil",
    AppIcons.SAVE: "save",
    AppIcons.STATUS: "circle-check",
    AppIcons.REMOVE: "trash-2",
    AppIcons.REFRESH: "refresh-cw",
    AppIcons.FILTER: "list-filter",  # renomeado de "filter"
    AppIcons.BATCH: "list",
    AppIcons.LOAD: "truck",
    AppIcons.COLLAPSE: "menu",
    AppIcons.NEXT: "chevron-right",
    AppIcons.PREVIOUS: "chevron-left",
    AppIcons.DOWNLOAD: "download",
    AppIcons.PDF: "file-text",
    AppIcons.EXCEL: "file-spreadsheet",

    AppIcons.PLAY: "play",
    AppIcons.PAUSE: "pause",
    AppIcons.SCALE: "scale",
    AppIcons.CARGO: "package",
    AppIcons.FISCAL_PENDING: "clock",
    AppIcons.FISCAL_PARTIAL: "package-open",
    AppIcons.FISCAL_DONE: "package-check",
    AppIcons.FISCAL_CRITICAL: "triangle-alert",
    AppIcons.FISCAL_BLOCKED: "ban",

    AppIcons.SUCCESS: "circle-check",
    AppIcons.WARNING: "triangle-alert",
    AppIcons.ERROR: "circle-x",
    AppIcons.PENDING: "clock",
    AppIcons.INFO: "info",

    AppIcons.MOON: "moon",
    AppIcons.SUN: "sun",
    AppIcons.MINIMIZE: "minus",
    AppIcons.MAXIMIZE: "square",

    AppIcons.GEAR: "settings",

    AppIcons.CIRCLE_ELLIPSIS: "circle-ellipsis",
    AppIcons.CIRCLE_PAUSE: "circle-pause",
    AppIcons.CIRCLE_PLAY: "circle-play",
    AppIcons.CIRCLE_DOT: "circle-dot",
    AppIcons.CIRCLE_DASHED: "circle-dashed",
    AppIcons.CIRCLE_SLASH: "circle-slash",
    AppIcons.CLOCK: "clock",
    AppIcons.PACKAGE_CHECK: "package-check",
    AppIcons.BAN: "ban",
    AppIcons.WORKFLOW: "workflow",
}


def lucide_slug(icon: AppIcons) -> str | None:
    return ICON_REGISTRY.get(icon)


def lucide_path(icon: AppIcons) -> Path | None:
    slug = lucide_slug(icon)
    if slug is None:
        return None
    return LUCIDE_DIR / f"{slug}.svg"
