"""Catalogo semantico de icones do app (PDF "Sistema de Icones Padronizado",
secao 5). Os valores em minusculo/snake_case correspondem 1:1 aos nomes
legados ja usados em `make_icon(name, ...)` por todo o projeto - isso e
proposital: permite que `make_icon` continue recebendo as mesmas strings de
sempre e resolva internamente para esta mesma chave semantica, sem quebrar
nenhum dos 39 pontos de chamada existentes.
"""

from __future__ import annotations

from enum import Enum


class AppIcons(str, Enum):
    # Navegacao
    DASHBOARD = "dashboard"
    CONTROL = "control"
    PRODUCTION = "production"
    GALVANIZATION = "galvanization"
    EXPEDITION = "expedition"
    STOCK = "stock"
    FISCAL = "fiscal"
    PARTIAL = "partial"
    HISTORY = "history"
    AUDIT = "audit"
    REPORTS = "reports"

    # Admin / sistema
    SETTINGS = "settings"
    USERS = "users"
    BACKUP = "backup"
    RESTORE = "restore"
    WINDOW_RESTORE = "window_restore"
    DATABASE = "database"
    ADMIN_CORRECTION = "admin_correction"

    # Comunicacao
    CHAT = "chat"
    BELL = "bell"
    NOTIFICATION = "notification"
    QUESTION = "question"
    AT = "at"
    MENTION = "mention"
    REPLY = "reply"
    SEND = "send"
    ATTACH = "attach"
    MIC = "mic"
    EMOJI = "emoji"
    ARROW_DOWN = "arrow_down"
    CHECK = "check"
    CHECK_DOUBLE = "check_double"

    # Acoes
    SEARCH = "search"
    CLEAR = "clear"
    CLOSE = "close"
    WINDOW_CLOSE = "window_close"
    NEW = "new"
    EDIT = "edit"
    SAVE = "save"
    STATUS = "status"
    REMOVE = "remove"
    REFRESH = "refresh"
    FILTER = "filter"
    BATCH = "batch"
    LOAD = "load"
    COLLAPSE = "collapse"
    NEXT = "next"
    PREVIOUS = "previous"
    DOWNLOAD = "download"
    PDF = "pdf"
    EXCEL = "excel"

    # Operacao
    PLAY = "play"
    PAUSE = "pause"
    SCALE = "scale"
    CARGO = "cargo"
    FISCAL_PENDING = "fiscal_pending"
    FISCAL_PARTIAL = "fiscal_partial"
    FISCAL_DONE = "fiscal_done"
    FISCAL_CRITICAL = "fiscal_critical"
    FISCAL_BLOCKED = "fiscal_blocked"

    # Status genericos
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    PENDING = "pending"
    INFO = "info"

    # Tema / janela
    MOON = "moon"
    SUN = "sun"
    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"

    # Formas puras (usadas hoje pelo catalogo de status de tabela em
    # status_icons.py, mas nao amarradas a esse uso especifico)
    CIRCLE_ELLIPSIS = "circle_ellipsis"
    CIRCLE_PAUSE = "circle_pause"
    CIRCLE_PLAY = "circle_play"
    CIRCLE_DOT = "circle_dot"
    CIRCLE_DASHED = "circle_dashed"
    CIRCLE_SLASH = "circle_slash"
    CLOCK = "clock_shape"
    PACKAGE_CHECK = "package_check_shape"
    BAN = "ban_shape"
    WORKFLOW = "workflow"

    # Legado sem uso conhecido, mantido por compatibilidade
    GEAR = "gear"
