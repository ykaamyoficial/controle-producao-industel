from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Stage = Literal["pendente", "cadastro", "solicitada", "nqt", "dispensa", "inloco", "doc", "fim"]

# So referencia (nunca e aberto): URL http(s)/file, caminho UNC ou caminho com letra de unidade.
_LINK_RE = re.compile(r"^(https?://\S+|file://\S+|\\\\[^\\/\s]+\\.+|[A-Za-z]:\\.+)$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _clean_link(value: str) -> str:
    value = value.strip()
    if _CONTROL_RE.search(value) or not _LINK_RE.match(value):
        raise ValueError("Informe um link (http/https/file) ou caminho de rede/disco valido.")
    return value


class InspectionCreate(BaseModel):
    pd_code: str = Field(min_length=1, max_length=120)
    pd_registered: bool = True  # DEPRECATED/ignorado desde 2026-10-21: toda inspecao nasce em "pendente"; a pergunta vai para POST /{id}/request

    @field_validator("pd_code")
    @classmethod
    def _pd(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Informe o PD.")
        return v


class InspectionFromProposal(BaseModel):
    proposal_id: int = Field(gt=0)
    pd_code: str = Field(min_length=1, max_length=120)
    pd_registered: bool = True  # DEPRECATED/ignorado desde 2026-10-21 (ver InspectionCreate)
    confirm_customer_conflict: bool = False  # confirma PD que ja e Pedido de proposta de outro cliente

    @field_validator("pd_code")
    @classmethod
    def _pd(cls, v: str) -> str:
        v = v.strip()
        if not v or _CONTROL_RE.search(v):
            raise ValueError("Informe o PD.")
        return v


class RequestPayload(BaseModel):
    pd_registered: bool  # True -> "solicitada"; False -> "cadastro"


class NqtPayload(BaseModel):
    nqt_code: str = Field(min_length=1, max_length=40)

    @field_validator("nqt_code")
    @classmethod
    def _nqt(cls, v: str) -> str:
        v = v.strip().upper()
        if not v or _CONTROL_RE.search(v):
            raise ValueError("Informe o codigo NQT.")
        return v


class DecisionPayload(BaseModel):
    decision: Literal["dispensa", "inloco"]
    visit_date: date | None = None
    confirm_dates: bool = False  # reenviar com true depois de um 409 DATE_CONFIRMATION_REQUIRED


class PitPayload(BaseModel):
    pit_link: str = Field(min_length=1, max_length=500)

    @field_validator("pit_link")
    @classmethod
    def _link(cls, v: str) -> str:
        return _clean_link(v)


class DocPayload(BaseModel):
    doc_link: str = Field(min_length=1, max_length=500)

    @field_validator("doc_link")
    @classmethod
    def _link(cls, v: str) -> str:
        return _clean_link(v)


class RejectPayload(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Informe o motivo da reprovacao.")
        return v


class InspectionEventOut(BaseModel):
    id: int
    stage: str
    attempt: int
    text: str
    reason: str | None = None
    actor_user_id: int | None = None
    actor_name: str | None = None
    created_at: datetime


class InspectionOut(BaseModel):
    id: int
    pd_code: str
    proposal_numbers: list[str] = []
    nqt_code: str | None = None
    stage: Stage
    attempt: int
    decision_type: str | None = None
    visit_date: date | None = None
    pit_link: str | None = None
    doc_link: str | None = None
    rejection_reason: str | None = None
    stage_since: datetime
    days_in_stage: int
    finished: bool
    created_at: datetime
    updated_at: datetime


class InspectionDetail(InspectionOut):
    events: list[InspectionEventOut] = []


class InspectionCounts(BaseModel):
    open: int
    finished: int
    to_request: int = 0


class InspectionStartResult(InspectionDetail):
    created: bool = True  # False: ja existia inspecao para o PD e ela foi devolvida sem alteracao de etapa


class ToRequestProposalOut(BaseModel):
    id: int
    proposal_number: str
    customer_name: str


class InspectionToRequestOut(BaseModel):
    """Linha "A solicitar": proposta(s) marcada(s) sem inspecao. Nao e uma inspecao (nao tem id)."""

    row_type: Literal["to_request"] = "to_request"
    pd_code: str | None = None  # PD efetivo: Pedido da proposta ou sugestao extraida do Obra/Site; None = digitar
    pd_source: Literal["order_reference", "project_name"] | None = None
    proposal_id: int  # proposta usada para iniciar (a de menor numero entre as marcadas do PD)
    proposal_numbers: list[str]
    customer_name: str
    proposals: list[ToRequestProposalOut]


class PdConflictProposalOut(BaseModel):
    id: int
    proposal_number: str
    customer_name: str


class PdSuggestionOut(BaseModel):
    proposal_id: int
    proposal_number: str
    customer_name: str
    is_cancelled: bool
    order_reference: str | None = None
    project_name: str | None = None
    pd_code: str | None = None
    pd_source: Literal["order_reference", "project_name"] | None = None
    existing_inspection_id: int | None = None
    conflicting_proposals: list[PdConflictProposalOut] = []  # outras propostas com esse PD e cliente diferente


class InspectionList(BaseModel):
    items: list[InspectionOut]
    total: int
    counts: InspectionCounts
    to_request: list[InspectionToRequestOut] = []


class FinishedProposalOut(BaseModel):
    id: int
    proposal_number: str
    customer_name: str


class FinishedInspectionOut(BaseModel):
    pd_code: str
    nqt_code: str | None = None
    doc_link: str | None = None
    finished_at: datetime
    proposals: list[FinishedProposalOut]


class FinishedInspectionList(BaseModel):
    items: list[FinishedInspectionOut]
    total: int
