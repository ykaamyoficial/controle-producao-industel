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
    confirm_inspection: bool = False  # reenviar com true depois de um 409 LOGISTICS_INSPECTION_CONFIRMATION_REQUIRED

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


def _clean_note(v: str | None) -> str | None:
    return (v or "").strip() or None


class StageDatePayload(BaseModel):
    """Andamento com data real: sem occurred_on vale hoje. Avisos de data pedem confirm_dates (409 DATE_CONFIRMATION_REQUIRED)."""

    occurred_on: date | None = None
    note: str | None = Field(default=None, max_length=1000)
    confirm_dates: bool = False

    @field_validator("note")
    @classmethod
    def _note(cls, v: str | None) -> str | None:
        return _clean_note(v)


class ApprovePayload(StageDatePayload):
    pass


class DocsPayload(StageDatePayload):
    nf_link: str = Field(min_length=1, max_length=500)
    xml_link: str = Field(min_length=1, max_length=500)
    bim_link: str = Field(min_length=1, max_length=500)

    @field_validator("nf_link", "xml_link", "bim_link")
    @classmethod
    def _link(cls, v: str) -> str:
        return _clean_link(v)


class AddProposalsPayload(BaseModel):
    proposal_ids: list[int] = Field(min_length=1)
    confirm_inspection: bool = False  # reenviar com true depois de um 409 LOGISTICS_INSPECTION_CONFIRMATION_REQUIRED


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


class LoadDepartedPayload(BaseModel):
    """Saida REAL da carga ("Saiu em"). O motivo e obrigatorio so ao mudar uma data ja registrada."""

    departed_on: date
    reason: str | None = Field(default=None, max_length=1000)


class LogDeliveryPayload(BaseModel):
    """Entrega REAL no CD. `delivery_proof_link` so muda se vier no corpo (null apaga). Motivo obrigatorio so ao mudar delivered_on ja registrada."""

    delivered_on: date
    delivery_proof_link: str | None = Field(default=None, max_length=500)
    reason: str | None = Field(default=None, max_length=1000)
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("delivery_proof_link")
    @classmethod
    def _link(cls, v: str | None) -> str | None:
        return _clean_link(v) if v is not None and v.strip() else None

    @field_validator("note")
    @classmethod
    def _note(cls, v: str | None) -> str | None:
        return _clean_note(v)


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
    occurred_on: date  # dia do andamento (sem data gravada: dia do registro)
    note: str | None = None
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
    inspection_stage: str | None = None  # etapa da inspecao do PD; None: PD sem inspecao
    inspection_finished: bool


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
    stage_since_date: date  # "desde": dia em que a etapa aconteceu
    days_in_stage: int  # dias corridos
    business_days_in_stage: int  # dias uteis da fabrica (seg-sex, sem feriado GO/Goiania)
    nf_link: str | None = None
    xml_link: str | None = None
    bim_link: str | None = None
    delivered_on: date | None = None
    delivery_proof_link: str | None = None
    load_id: int | None = None
    load_code: str | None = None
    proposal_count: int
    without_doc_count: int  # propostas ativas cuja inspecao do PD ainda nao esta finalizada (sem DOC BIM)
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
    inspection_stage: str
    inspection_finished: bool


class EligibleProposalList(BaseModel):
    items: list[EligibleProposalOut]
    total: int


class LoadLogOut(LogOut):
    """LOG dentro do detalhe da carga: logistica completa e propostas ativas."""

    items: list[LogItemOut] = []


class LoadOut(BaseModel):
    id: int
    code: str
    departure_date: date  # prevista
    departed_on: date | None = None  # real ("Saiu em")
    log_count: int
    logs_total: int
    logs_delivered: int  # LOGs da carga com delivered_on preenchida
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
