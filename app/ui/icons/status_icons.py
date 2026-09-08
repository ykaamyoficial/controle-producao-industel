"""Camada semantica para icones de ESTADO/STATUS de proposta ou item numa
linha de tabela - distinta do icone de AREA (ex.: "factory" para Producao).
Um icone de status comunica "em que pe está aquele item" (aguardando,
em andamento, concluido, bloqueado...), nunca em qual modulo ele está.

`AppStatusIcon` cobre os estados visuais possiveis; `STATUS_TO_ICON` mapeia
cada status tecnico REAL do backend (nomes ja existentes em
`app.services.backend_adapter.STATUS_LABELS`/`LOAD_STATUS_LABELS` e
`app.models.fiscal_table_model.FISCAL_STATUS_LABELS`) para um desses
estados - nenhum status de negocio novo e inventado aqui.

A cor nunca e uma tabela hexadecimal paralela: `status_icon()` chama
`app.ui.styles.status_color()`, a MESMA funcao que ja pinta o badge de texto
da linha, garantindo que icone e badge nunca divirjam.
"""

from __future__ import annotations

import logging
from enum import Enum

from PySide6.QtGui import QIcon

from app.services.backend_adapter import legacy

from .icon_provider import get_icon
from .icon_tokens import IconColorRole, IconSize, IconState, resolve_color
from .semantic_icons import AppIcons

log = logging.getLogger(__name__)

_UNKNOWN_STATUS_LOGGED: set[str] = set()


class AppStatusIcon(Enum):
    PENDING = "pending"
    WAITING = "waiting"
    NOT_STARTED = "not_started"
    READY = "ready"
    RELEASED = "released"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    PARTIAL = "partial"
    COMPLETED = "completed"
    DELIVERED = "delivered"
    BLOCKED = "blocked"
    WARNING = "warning"
    ERROR = "error"
    CANCELLED = "cancelled"


class StatusColorRole(Enum):
    """Usado somente como fallback quando `status_icon()` recebe um status
    vazio/desconhecido - nesse caso nao ha categoria valida em
    `STATUS_CATEGORY_BY_STATUS` pra reaproveitar, entao caimos aqui em vez
    de arriscar um KeyError ou uma cor arbitraria."""

    PENDING = "pending"
    READY = "ready"
    PROGRESS = "progress"
    PARTIAL = "partial"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    DISABLED = "disabled"


STATUS_ICON_REGISTRY: dict[AppStatusIcon, AppIcons] = {
    AppStatusIcon.PENDING: AppIcons.CIRCLE_ELLIPSIS,
    AppStatusIcon.WAITING: AppIcons.CLOCK,
    AppStatusIcon.NOT_STARTED: AppIcons.CIRCLE_PAUSE,
    AppStatusIcon.READY: AppIcons.CIRCLE_PLAY,
    AppStatusIcon.RELEASED: AppIcons.CIRCLE_PLAY,
    AppStatusIcon.IN_PROGRESS: AppIcons.CIRCLE_DOT,
    AppStatusIcon.PAUSED: AppIcons.CIRCLE_PAUSE,
    AppStatusIcon.PARTIAL: AppIcons.CIRCLE_DASHED,
    AppStatusIcon.COMPLETED: AppIcons.SUCCESS,
    AppStatusIcon.DELIVERED: AppIcons.PACKAGE_CHECK,
    AppStatusIcon.BLOCKED: AppIcons.CIRCLE_SLASH,
    AppStatusIcon.WARNING: AppIcons.WARNING,
    AppStatusIcon.ERROR: AppIcons.ERROR,
    AppStatusIcon.CANCELLED: AppIcons.BAN,
}

# status tecnico (backend, ja normalizado maiusculo) -> estado visual.
STATUS_TO_ICON: dict[str, AppStatusIcon] = {
    # Controle Geral / cascata de localizacao (current_location)
    "NAO_LIBERADO": AppStatusIcon.NOT_STARTED,
    "AGUARDANDO_LIBERACAO": AppStatusIcon.WAITING,
    "LIBERADO_PRODUCAO": AppStatusIcon.RELEASED,
    "EM_PRODUCAO": AppStatusIcon.IN_PROGRESS,
    "EM_GALVANIZACAO": AppStatusIcon.IN_PROGRESS,
    "EM_EXPEDICAO": AppStatusIcon.IN_PROGRESS,
    "ENTREGUE": AppStatusIcon.DELIVERED,
    "CANCELADA": AppStatusIcon.CANCELLED,
    "UNIFICADA_PRINCIPAL": AppStatusIcon.IN_PROGRESS,

    # Producao
    "NAO_INICIADO": AppStatusIcon.NOT_STARTED,
    "ITEM_PENDENTE_FABRICACAO": AppStatusIcon.PENDING,
    "FLUXO_INDEFINIDO": AppStatusIcon.PENDING,
    "INICIADO": AppStatusIcon.IN_PROGRESS,
    "FINALIZADO": AppStatusIcon.COMPLETED,
    "FINALIZADO_PARCIAL": AppStatusIcon.PARTIAL,
    "PARADO": AppStatusIcon.PAUSED,

    # Galvanizacao
    "AGUARDANDO_ENVIO": AppStatusIcon.WAITING,
    "AGUARDANDO_RETORNO": AppStatusIcon.WAITING,
    "DISPONIVEL_PARCIAL": AppStatusIcon.PARTIAL,
    "EM_CARGA": AppStatusIcon.IN_PROGRESS,
    "ENVIADO_GALVANIZACAO": AppStatusIcon.IN_PROGRESS,
    "RETORNOU_GALVANIZACAO": AppStatusIcon.COMPLETED,
    "RETORNADO": AppStatusIcon.COMPLETED,
    "RETORNOU_PARCIAL": AppStatusIcon.PARTIAL,
    "DISPONIVEL": AppStatusIcon.READY,

    # Expedicao
    "EM_SEPARACAO": AppStatusIcon.IN_PROGRESS,
    "AGUARDANDO_SEPARACAO_PARCIAL": AppStatusIcon.PARTIAL,
    "SEPARACAO_INICIADA": AppStatusIcon.IN_PROGRESS,
    "SEPARADO": AppStatusIcon.READY,
    "SEPARADO_COM_PENDENCIA": AppStatusIcon.PARTIAL,
    "ENTREGUE_PARCIAL": AppStatusIcon.PARTIAL,

    # Almoxarifado
    "AGUARDANDO_CONFIRMACAO": AppStatusIcon.WAITING,
    "SEM_PARAFUSOS": AppStatusIcon.BLOCKED,
    "ALMOXARIFADO_ENTREGUE": AppStatusIcon.DELIVERED,
    "ALMOXARIFADO_ENTREGUE_PARCIAL": AppStatusIcon.PARTIAL,
    "NAO_DEFINIDO": AppStatusIcon.NOT_STARTED,

    # Cargas de galvanizacao (LOAD_STATUS_LABELS)
    "LIBERADA_PARA_ENVIO": AppStatusIcon.RELEASED,
    "RETORNO_PARCIAL": AppStatusIcon.PARTIAL,
    "RETORNADA_GALVANIZACAO": AppStatusIcon.COMPLETED,
    # sintetico: usado quando a carga esta atrasada (nao existe como status
    # persistido, so calculado na tela - ver galvanization_load_dialog.py).
    "ATRASADA": AppStatusIcon.WARNING,

    # Fiscal (FISCAL_STATUS_LABELS + set legado curto)
    "FALTA_EMITIR_NOTA_FISCAL": AppStatusIcon.PENDING,
    "AGUARDANDO_NF": AppStatusIcon.WAITING,
    "CP_EM_PROCESSAMENTO": AppStatusIcon.WAITING,
    "NF_EM_PROCESSAMENTO": AppStatusIcon.IN_PROGRESS,
    "DISPONIVEL_PARA_EMISSAO": AppStatusIcon.READY,
    "PENDENCIA_FISCAL_CRITICA": AppStatusIcon.BLOCKED,
    "NOTA_FISCAL_PARCIAL": AppStatusIcon.PARTIAL,
    "NF_PARCIAL": AppStatusIcon.PARTIAL,
    "NOTA_FISCAL_EMITIDA": AppStatusIcon.COMPLETED,
    "NF_EMITIDA": AppStatusIcon.COMPLETED,
    "NF_RETIRADA_CLIENTE": AppStatusIcon.DELIVERED,
    "FISCAL_CANCELADO": AppStatusIcon.CANCELLED,
    "PENDENTE": AppStatusIcon.PENDING,
    "PARCIAL": AppStatusIcon.PARTIAL,
    "FATURADO": AppStatusIcon.COMPLETED,
    "CANCELADO": AppStatusIcon.CANCELLED,

    # Aliases legados de app.models.fiscal_table_model::fiscal_action_icon()
    # (a funcao de negocio nao muda - so passam a resolver visualmente aqui)
    "fiscal_pending": AppStatusIcon.PENDING,
    "fiscal_partial": AppStatusIcon.PARTIAL,
    "fiscal_done": AppStatusIcon.COMPLETED,
    "fiscal_critical": AppStatusIcon.ERROR,
    "fiscal_blocked": AppStatusIcon.BLOCKED,
}

_FALLBACK_HEX = {
    StatusColorRole.PENDING: "#94a3b8",
    StatusColorRole.READY: "#2563eb",
    StatusColorRole.PROGRESS: "#ea580c",
    StatusColorRole.PARTIAL: "#ca8a04",
    StatusColorRole.SUCCESS: "#16a34a",
    StatusColorRole.WARNING: "#ca8a04",
    StatusColorRole.ERROR: "#dc2626",
    StatusColorRole.DISABLED: "#94a3b8",
}


def _normalize(status: str | None) -> str:
    return legacy.normalize_status(status or "")


def status_icon_role(status: str | None) -> AppStatusIcon:
    """Resolve o estado visual (forma do icone) para um status tecnico.
    Status desconhecido cai em PENDING (nunca None, nunca emoji) e loga um
    aviso uma unica vez por status desconhecido."""
    normalized = _normalize(status)
    if not normalized:
        # Sem status ainda (area nao alcancada) e um caso legitimo, nao um
        # status desconhecido - nao loga aviso pra isso.
        return AppStatusIcon.NOT_STARTED
    role = STATUS_TO_ICON.get(normalized)
    if role is not None:
        return role
    if normalized not in _UNKNOWN_STATUS_LOGGED:
        log.warning("status_icon: status desconhecido '%s' sem AppStatusIcon mapeado; usando PENDING.", normalized)
        _UNKNOWN_STATUS_LOGGED.add(normalized)
    return AppStatusIcon.PENDING


def status_icon_tooltip(status: str | None, area: str | None = None) -> str:
    """Texto real do status pra tooltip, quando o icone aparece sozinho."""
    normalized = _normalize(status)
    if not normalized:
        return ""
    if (area or "").strip().upper() == "FISCAL":
        from app.models.fiscal_table_model import fiscal_status_label

        return fiscal_status_label(normalized)
    if area:
        return legacy.area_status_label(area, normalized)
    return legacy.status_label(normalized)


def status_icon(
    status: str | None,
    area: str | None = None,
    palette: dict | None = None,
    size: int = IconSize.TABLE_STATUS,
    state: IconState = IconState.NORMAL,
) -> QIcon:
    """Funcao central: status tecnico -> icone semantico Lucide -> cor
    semantica (a mesma do badge de texto da linha) -> QIcon pronto pra usar.
    Nunca retorna None; nunca cai em PNG/emoji/desenho ad-hoc."""
    role = status_icon_role(status)
    app_icon = STATUS_ICON_REGISTRY[role]

    if state == IconState.DISABLED or not palette:
        color = resolve_color(IconColorRole.DISABLED, palette)
    else:
        from app.ui.styles import status_color

        normalized = _normalize(status)
        color, _text = status_color(normalized, palette, area or "")

    icon = get_icon(app_icon, int(size), color)
    if icon is None:
        # get_icon so retorna None se o AppIcons nao tiver entrada no
        # registro Lucide - nao deveria acontecer pra nenhum AppStatusIcon,
        # mas nunca deixamos a chamada quebrar por causa de um icone.
        icon = QIcon()
    return icon
