from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable


STATUS_PRIORITY: dict[str, list[str]] = {
    "CONTROLE GERAL": [
        "NAO_LIBERADO",
        "LIBERADO_PRODUCAO",
        "CANCELADA",
    ],
    "PRODUCAO": [
        "NAO_INICIADO",
        "ITEM_PENDENTE_FABRICACAO",
        "INICIADO",
        "PARADO",
        "FINALIZADO_PARCIAL",
        "FINALIZADO",
    ],
    "GALVANIZACAO": [
        "AGUARDANDO_ENVIO",
        "DISPONIVEL_PARCIAL",
        "EM_CARGA",
        "ENVIADO_GALVANIZACAO",
        "RETORNOU_PARCIAL",
        "RETORNOU_GALVANIZACAO",
    ],
    "EXPEDICAO": [
        "EM_SEPARACAO",
        "AGUARDANDO_SEPARACAO_PARCIAL",
        "SEPARACAO_INICIADA",
        "SEPARADO_COM_PENDENCIA",
        "SEPARADO",
        "ENTREGUE_PARCIAL",
        "ENTREGUE",
    ],
    "ALMOXARIFADO": [
        "NAO_DEFINIDO",
        "AGUARDANDO_CONFIRMACAO",
        "EM_SEPARACAO",
        "SEM_PARAFUSOS",
        "SEPARADO",
        "ALMOXARIFADO_ENTREGUE",
        "ALMOXARIFADO_ENTREGUE_PARCIAL",
    ],
}


AREA_STATUS_COLUMNS = {
    "CONTROLE GERAL": "status_geral",
    "PRODUCAO": "status_producao",
    "GALVANIZACAO": "status_galvanizacao",
    "EXPEDICAO": "status_expedicao",
    "ALMOXARIFADO": "status_almoxarifado",
}


STATUS_DATE_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "PRODUCAO": {
        "FINALIZADO": ("data_final_producao", "atualizado_em", "data_entrada", "data_cadastro"),
        "FINALIZADO_PARCIAL": ("data_final_producao", "atualizado_em", "data_entrada", "data_cadastro"),
    },
    "GALVANIZACAO": {
        "ENVIADO_GALVANIZACAO": ("data_envio_galv", "atualizado_em", "data_cadastro"),
        "EM_CARGA": ("data_envio_galv", "atualizado_em", "data_cadastro"),
        "RETORNOU_PARCIAL": ("data_retorno_galv", "atualizado_em", "data_envio_galv", "data_cadastro"),
        "RETORNOU_GALVANIZACAO": ("data_retorno_galv", "atualizado_em", "data_envio_galv", "data_cadastro"),
    },
    "EXPEDICAO": {
        "EM_SEPARACAO": ("data_separacao", "atualizado_em", "data_cadastro"),
        "AGUARDANDO_SEPARACAO_PARCIAL": ("data_separacao", "atualizado_em", "data_cadastro"),
        "SEPARACAO_INICIADA": ("data_separacao", "atualizado_em", "data_cadastro"),
        "SEPARADO_COM_PENDENCIA": ("data_separacao", "atualizado_em", "data_cadastro"),
        "SEPARADO": ("data_separacao", "atualizado_em", "data_cadastro"),
        "ENTREGUE_PARCIAL": ("data_retirada", "atualizado_em", "data_cadastro"),
        "ENTREGUE": ("data_retirada", "atualizado_em", "data_cadastro"),
    },
    "ALMOXARIFADO": {
        "SEPARADO": ("data_separacao", "atualizado_em", "data_cadastro"),
        "ALMOXARIFADO_ENTREGUE": ("data_retirada", "atualizado_em", "data_cadastro"),
        "ALMOXARIFADO_ENTREGUE_PARCIAL": ("data_retirada", "atualizado_em", "data_cadastro"),
        "SEM_PARAFUSOS": ("data_retirada", "atualizado_em", "data_cadastro"),
    },
}


DEFAULT_DATE_FIELDS = ("atualizado_em", "data_entrada", "data_cadastro", "prazo_entrega")


FISCAL_STATUS_PRIORITY = [
    "PENDENCIA_FISCAL_CRITICA",
    "DISPONIVEL_PARA_EMISSAO",
    "AGUARDANDO_NF",
    "CP_EM_PROCESSAMENTO",
    "NF_EM_PROCESSAMENTO",
    "FALTA_EMITIR_NOTA_FISCAL",
    "NF_PARCIAL",
    "NOTA_FISCAL_PARCIAL",
    "NF_EMITIDA",
    "NOTA_FISCAL_EMITIDA",
    "NF_RETIRADA_CLIENTE",
    "FISCAL_CANCELADO",
]


FISCAL_STATUS_DATE_FIELDS = {
    "FALTA_EMITIR_NOTA_FISCAL": ("data_entrada_fiscal", "updated_at", "created_at"),
    "AGUARDANDO_NF": ("data_entrada_fiscal", "updated_at", "created_at"),
    "CP_EM_PROCESSAMENTO": ("data_entrada_fiscal", "updated_at", "created_at"),
    "NF_EM_PROCESSAMENTO": ("updated_at", "data_entrada_fiscal", "created_at"),
    "DISPONIVEL_PARA_EMISSAO": ("updated_at", "data_entrada_fiscal", "created_at"),
    "PENDENCIA_FISCAL_CRITICA": ("data_retirada", "updated_at", "data_entrada_fiscal", "created_at"),
    "NOTA_FISCAL_PARCIAL": ("data_ultima_emissao", "updated_at", "data_entrada_fiscal", "created_at"),
    "NF_PARCIAL": ("data_ultima_emissao", "updated_at", "data_entrada_fiscal", "created_at"),
    "NOTA_FISCAL_EMITIDA": ("data_ultima_emissao", "updated_at", "data_entrada_fiscal", "created_at"),
    "NF_EMITIDA": ("data_ultima_emissao", "updated_at", "data_entrada_fiscal", "created_at"),
    "NF_RETIRADA_CLIENTE": ("data_retirada_nf", "data_ultima_emissao", "updated_at", "data_entrada_fiscal", "created_at"),
    "FISCAL_CANCELADO": ("updated_at", "data_ultima_emissao", "data_entrada_fiscal", "created_at"),
}


def sort_process_rows(area: str | None, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    area_key = _normalize_area(area)
    return sorted(rows, key=lambda row: _process_sort_key(area_key, row))


def sort_fiscal_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=_fiscal_sort_key)


def status_priority(area: str | None, status: str | None) -> int:
    priority = STATUS_PRIORITY.get(_normalize_area(area), [])
    status_key = _normalize_status(status)
    try:
        return priority.index(status_key)
    except ValueError:
        return len(priority) + 100


def fiscal_status_priority(status: str | None) -> int:
    status_key = _normalize_status(status)
    try:
        return FISCAL_STATUS_PRIORITY.index(status_key)
    except ValueError:
        return len(FISCAL_STATUS_PRIORITY) + 100


def status_date_value(area: str | None, row: dict[str, Any], status: str | None = None) -> datetime | None:
    area_key = _normalize_area(area)
    status_key = _normalize_status(status) or _status_for_area(row, area_key)
    fields = STATUS_DATE_FIELDS.get(area_key, {}).get(status_key, DEFAULT_DATE_FIELDS)
    return _first_date(row, fields) or _first_date(row, DEFAULT_DATE_FIELDS)


def fiscal_status_date_value(row: dict[str, Any]) -> datetime | None:
    status_key = _normalize_status(row.get("situacao_fiscal") or row.get("status_fiscal"))
    fields = FISCAL_STATUS_DATE_FIELDS.get(status_key, ("updated_at", "data_entrada_fiscal", "created_at"))
    return _first_date(row, fields)


def _process_sort_key(area: str, row: dict[str, Any]) -> tuple[int, int, str, int]:
    status = _status_for_area(row, area)
    date_value = status_date_value(area, row, status)
    return (
        status_priority(area, status),
        -_date_number(date_value),
        str(row.get("proposta") or "").lower(),
        _safe_int(row.get("id")),
    )


def _fiscal_sort_key(row: dict[str, Any]) -> tuple[int, int, str, int]:
    return (
        fiscal_status_priority(row.get("situacao_fiscal") or row.get("status_fiscal")),
        -_date_number(fiscal_status_date_value(row)),
        str(row.get("proposta") or "").lower(),
        _safe_int(row.get("fiscal_processo_id") or row.get("id")),
    )


def _status_for_area(row: dict[str, Any], area: str) -> str:
    column = AREA_STATUS_COLUMNS.get(area, "status_geral")
    return _normalize_status(row.get(column) or row.get("status_geral"))


def _first_date(row: dict[str, Any], fields: Iterable[str]) -> datetime | None:
    for field in fields:
        value = row.get(field)
        parsed = _parse_date(value)
        if parsed is not None:
            return parsed
    return None


def _parse_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in (
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _date_number(value: datetime | None) -> int:
    if value is None:
        return 0
    return int(value.strftime("%Y%m%d%H%M%S"))


def _normalize_area(area: str | None) -> str:
    return str(area or "").strip().upper()


def _normalize_status(status: Any) -> str:
    return str(status or "").strip().upper().replace(" ", "_").replace("-", "_")


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
