from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from api.app.modules.inspection.schemas import _CONTROL_RE, _clean_link

LogStage = Literal["reservada", "docs", "aprovada"]
ItemStatus = Literal["ok", "pendente", "reprovada"]

_LOG_RE = re.compile(r"^LOG\d+$")


def _required_text(value: str, message: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(message)
    return value


class LogCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    state: str = Field(min_length=1, max_length=40)  # estado da Equatorial, ex.: EQT-MA
    requested_date: date
    reserved_date: date | None = None  # None: a data pedida estava disponivel e ficou reservada
    loading_date: date
    delivery_date: date
    proposal_ids: list[int] = Field(min_length=1)
    confirm_dates: bool = False  # reenviar com true depois de um 409 DATE_CONFIRMATION_REQUIRED

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        v = v.strip().upper()
        if not _LOG_RE.match(v):
            raise ValueError("O codigo deve ser LOG seguido de numeros, ex.: LOG103.")
        return v

    @field_validator("state")
    @classmethod
    def _state(cls, v: str) -> str:
        v = _required_text(v, "Informe o estado da Equatorial.").upper()
        if _CONTROL_RE.search(v):
            raise ValueError("Estado invalido.")
        return v


class DocsPayload(BaseModel):
    nf_link: str = Field(min_length=1, max_length=500)
    xml_link: str = Field(min_length=1, max_length=500)
    bim_link: str = Field(min_length=1, max_length=500)

    @field_validator("nf_link", "xml_link", "bim_link")
    @classmethod
    def _link(cls, v: str) -> str:
        return _clean_link(v)


class AddProposalsPayload(BaseModel):
    proposal_ids: list[int] = Field(min_length=1)


class ReasonPayload(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        return _required_text(v, "Informe o motivo.")


class ResolveItemPayload(BaseModel):
    result: Literal["ok", "reprovada"]


class LoadCreate(BaseModel):
    departure_date: date
    log_ids: list[int] = Field(min_length=1)
    confirm_dates: bool = False


class LoadUpdate(BaseModel):
    departure_date: date
    reason: str = Field(min_length=1, max_length=1000)  # motivo da mudanca (obrigatorio)
    confirm_dates: bool = False

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        return _required_text(v, "Informe o motivo.")


class LogDatesPayload(BaseModel):
    """Edita datas do LOG: so os campos enviados (e diferentes) mudam; um evento por campo."""

    requested_date: date | None = None
    reserved_date: date | None = None
    loading_date: date | None = None
    delivery_date: date | None = None
    reason: str = Field(min_length=1, max_length=1000)
    confirm_dates: bool = False

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        return _required_text(v, "Informe o motivo.")


class LogIdPayload(BaseModel):
    log_id: int
    confirm_dates: bool = False


class EventOut(BaseModel):
    id: int
    text: str
    reason: str | None = None
    actor_user_id: int | None = None
    actor_name: str | None = None
    created_at: datetime


class LogItemOut(BaseModel):
    id: int
    proposal_id: int
    proposal_number: str
    customer_name: str
    project_name: str | None = None
    pd_code: str | None = None
    status: ItemStatus
    added_at: datetime
    removed_at: datetime | None = None
    removal_reason: str | None = None
    removed_by_name: str | None = None


class LogOut(BaseModel):
    id: int
    code: str
    state: str
    requested_date: date
    reserved_date: date
    loading_date: date
    delivery_date: date
    stage: LogStage
    stage_since: datetime
    days_in_stage: int  # dias corridos
    business_days_in_stage: int  # dias uteis da fabrica (seg-sex, sem feriado GO/Goiania)
    nf_link: str | None = None
    xml_link: str | None = None
    bim_link: str | None = None
    load_id: int | None = None
    load_code: str | None = None
    proposal_count: int
    created_at: datetime
    updated_at: datetime


class LogDetail(LogOut):
    items: list[LogItemOut] = []  # vinculos ativos
    removed_items: list[LogItemOut] = []  # historico de remocoes (removed_at, removal_reason)
    events: list[EventOut] = []


class LogList(BaseModel):
    items: list[LogOut]
    total: int


class RemoveResult(BaseModel):
    log_deleted: bool  # True: era a ultima proposta, o LOG deixou de existir
    log: LogDetail | None = None


class EligibleProposalOut(BaseModel):
    id: int
    proposal_number: str
    customer_name: str
    project_name: str | None = None
    pd_code: str
    nqt_code: str | None = None
    state: str | None = None  # derivado do cliente (ex.: EQT-MA); None se nao for deduzivel


class EligibleProposalList(BaseModel):
    items: list[EligibleProposalOut]
    total: int


class LoadLogOut(LogOut):
    """LOG dentro do detalhe da carga: logistica completa e propostas ativas."""

    items: list[LogItemOut] = []


class LoadOut(BaseModel):
    id: int
    code: str
    departure_date: date
    log_count: int
    proposal_count: int
    log_codes: list[str]
    states: list[str]
    created_at: datetime
    updated_at: datetime


class LoadDetail(LoadOut):
    logs: list[LoadLogOut] = []
    events: list[EventOut] = []


class LoadList(BaseModel):
    items: list[LoadOut]
    total: int
