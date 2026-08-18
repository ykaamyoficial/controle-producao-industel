from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class ProposalItemSummary(BaseModel):
    id: int
    legacy_id: int | None = None
    item_number: str
    product_code: str | None = None
    description: str | None = None
    quantity: Decimal
    unit: str | None = None
    unit_weight: Decimal | None = None
    total_weight: Decimal | None = None
    weight_source: str = "LEGACY"
    weight_status: str = "LEGACY"
    weight_synced_at: datetime | None = None
    produce_internally: str
    requires_galvanization: str
    flow_defined: bool
    produced: bool
    galvanized: bool
    delivered: bool
    synced_at: datetime
    source_hash: str | None = None
    version: int = 1
    active: bool = True
    notes: str | None = None
    flow_editable: bool = True
    flow_lock_reason: str | None = None


class ProposalItemDetail(ProposalItemSummary):
    proposal_id: int
    legacy_current_process_id: int | None = None
    delivered_at: datetime | None = None
    legacy_updated_at: datetime | None = None


class ProposalListItem(BaseModel):
    id: int
    legacy_id: int | None = None
    proposal_number: str
    customer_name: str
    project_name: str | None = None
    order_reference: str | None = None
    lot: str | None = None
    proposal_date: date | None = None
    deadline_date: date | None = None
    current_area: str | None = None
    current_status: str | None = None
    is_partial: bool
    parent_proposal_id: int | None = None
    is_cancelled: bool
    is_completed: bool
    legacy_updated_at: datetime | None = None
    synced_at: datetime
    version: int = 1
    active: bool = True


class ProposalDetail(ProposalListItem):
    general_status: str | None = None
    production_status: str | None = None
    galvanization_status: str | None = None
    shipping_status: str | None = None
    warehouse_status: str | None = None
    flow_situation: str | None = None
    has_production_pending: bool
    process_type: str | None = None
    parent_legacy_id: int | None = None
    partial_number: int | None = None
    source: str
    source_hash: str | None = None
    legacy_created_at: datetime | None = None
    notes: str | None = None
    cancelled_at: datetime | None = None
    cancelled_by: int | None = None
    cancellation_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    items: list[ProposalItemSummary] = Field(default_factory=list)


class PaginatedProposalResponse(BaseModel):
    items: list[ProposalListItem]
    total: int
    limit: int
    offset: int


class PartialProposalSummary(BaseModel):
    id: int
    proposal_number: str
    customer_name: str
    project_name: str | None = None
    lot: str | None = None
    current_area: str | None = None
    current_status: str | None = None
    production_status: str | None = None
    galvanization_status: str | None = None
    shipping_status: str | None = None
    warehouse_status: str | None = None
    fiscal_status: str | None = None
    flow_situation: str | None = None
    process_type: str | None = None
    partial_number: int | None = None
    total_items: int
    produced_items: int
    production_pending_items: int
    galvanized_items: int
    galvanization_pending_items: int
    delivered_items: int
    expedition_pending_items: int
    billed_items: int
    fiscal_pending_items: int
    total_weight: Decimal
    produced_weight: Decimal
    production_pending_weight: Decimal
    galvanization_sent_weight: Decimal
    galvanization_returned_weight: Decimal
    galvanization_pending_weight: Decimal
    expedition_delivered_weight: Decimal
    expedition_pending_weight: Decimal
    fiscal_billed_weight: Decimal
    fiscal_pending_weight: Decimal
    weight_known_items: int = 0
    weight_total_items: int = 0
    weight_complete: bool = False
    partial_stage: str
    updated_at: datetime | None = None
    version: int = 1


class PaginatedPartialProposalResponse(BaseModel):
    items: list[PartialProposalSummary]
    total: int
    limit: int
    offset: int


class WarehouseProposalSummary(BaseModel):
    id: int
    proposal_number: str
    customer_name: str
    project_name: str | None = None
    lot: str | None = None
    current_area: str | None = None
    current_status: str | None = None
    warehouse_status: str
    warehouse_required: str
    general_status: str | None = None
    shipping_status: str | None = None
    total_items: int
    total_weight: Decimal
    weight_known_items: int = 0
    weight_total_items: int = 0
    weight_complete: bool = False
    updated_at: datetime | None = None
    version: int = 1


class PaginatedWarehouseProposalResponse(BaseModel):
    items: list[WarehouseProposalSummary]
    total: int
    limit: int
    offset: int


class ProposalHistoryItem(BaseModel):
    id: int
    source: str
    proposal_id: int | None = None
    proposal_number: str | None = None
    area: str | None = None
    from_status: str | None = None
    to_status: str | None = None
    event_type: str
    actor_user_id: int | None = None
    actor_name: str | None = None
    observation: str | None = None
    request_id: str | None = None
    created_at: datetime


class ProposalActivityItem(BaseModel):
    id: int
    proposal_id: int
    event_type: str
    area: str | None = None
    actor_name: str | None = None
    headline: str
    item_code: str | None = None
    correlation_id: str | None = None
    occurred_at: datetime


class ProposalItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_number: str = Field(min_length=1, max_length=80)
    product_code: str | None = Field(default=None, max_length=120)
    description: str = Field(min_length=1)
    quantity: Decimal = Field(gt=0)
    unit: str | None = Field(default="UN", max_length=40)
    unit_weight: Decimal | None = Field(default=None, ge=0)
    total_weight: Decimal | None = Field(default=None, ge=0)
    produce_internally: bool | None = None
    non_production_reason: str | None = None
    requires_galvanization: bool | None = None
    notes: str | None = None

    @field_validator("item_number", "product_code", "unit", mode="before")
    @classmethod
    def strip_short_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class ProposalItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    item_number: str | None = Field(default=None, min_length=1, max_length=80)
    product_code: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, min_length=1)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=40)
    unit_weight: Decimal | None = Field(default=None, ge=0)
    total_weight: Decimal | None = Field(default=None, ge=0)
    produce_internally: bool | None = None
    non_production_reason: str | None = None
    requires_galvanization: bool | None = None
    notes: str | None = None


class ProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_number: str = Field(min_length=1, max_length=80)
    customer_name: str = Field(min_length=1, max_length=180)
    project_name: str | None = Field(default=None, max_length=180)
    purchase_order: str | None = Field(default=None, max_length=120)
    batch_reference: str | None = Field(default=None, max_length=80)
    proposal_date: date | None = None
    deadline_date: date | None = None
    source: str = Field(default="MANUAL", max_length=80)
    warehouse_status: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    import_metadata: dict[str, Any] | None = None
    items: list[ProposalItemCreate] = Field(min_length=1)

    @field_validator("proposal_number", "customer_name", "project_name", "purchase_order", "batch_reference", "source", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"MANUAL", "NOMUS_API", "NOMUS_PDF", "IMPORT", "SYSTEM"}:
            raise ValueError("origem invalida")
        return normalized

    @field_validator("import_metadata")
    @classmethod
    def validate_import_metadata(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        allowed = {
            "origem",
            "batch_id",
            "extraction_method",
            "template_id",
            "parser_version",
            "requires_human_review",
            "warning_codes",
            "nome_arquivo",
            "hash_sha256",
            "observacao",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError("metadados de importacao invalidos")
        blocked = {"price", "valor", "discount", "desconto", "margin", "margem", "token", "password", "secret"}
        for key, item in value.items():
            normalized = "".join(char for char in str(key).lower() if char.isalnum())
            if any(term in normalized for term in blocked):
                raise ValueError("metadados de importacao contem campo bloqueado")
            if isinstance(item, (dict, tuple, set)):
                raise ValueError("metadados de importacao devem ser simples")
            if isinstance(item, list) and (len(item) > 50 or any(not isinstance(entry, str) for entry in item)):
                raise ValueError("lista de metadados de importacao invalida")
        return value


class ProposalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    customer_name: str | None = Field(default=None, min_length=1, max_length=180)
    project_name: str | None = Field(default=None, max_length=180)
    purchase_order: str | None = Field(default=None, max_length=120)
    batch_reference: str | None = Field(default=None, max_length=80)
    proposal_date: date | None = None
    deadline_date: date | None = None
    warehouse_status: str | None = Field(default=None, max_length=120)
    notes: str | None = None


class WarehouseStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    status: str = Field(max_length=120)
    observation: str | None = Field(default=None, max_length=500)

    @field_validator("status", mode="before")
    @classmethod
    def strip_status(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


class ProposalCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class ProposalStatusChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    to_area: str = Field(max_length=80)
    to_status: str = Field(max_length=120)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("to_area", "to_status", mode="before")
    @classmethod
    def strip_state(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


class ProposalAdministrativeCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    correction_type: Literal["STATE"] = "STATE"
    to_area: str = Field(max_length=80)
    to_status: str = Field(max_length=120)
    reason: str = Field(
        min_length=1,
        max_length=1000,
        validation_alias=AliasChoices("reason", "justification"),
    )
    idempotency_key: str = Field(min_length=8, max_length=100)

    @field_validator("to_area", "to_status", mode="before")
    @classmethod
    def strip_state(cls, value):
        return value.strip().upper().replace(" ", "_") if isinstance(value, str) else value

    @field_validator("reason", "idempotency_key", mode="before")
    @classmethod
    def strip_administrative_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class ProposalAdministrativeCorrectionPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    correction_type: Literal["STATE"] = "STATE"
    to_area: str = Field(max_length=80)
    to_status: str = Field(max_length=120)

    @field_validator("to_area", "to_status", mode="before")
    @classmethod
    def strip_state(cls, value):
        return value.strip().upper().replace(" ", "_") if isinstance(value, str) else value


class ProposalAdministrativeCorrectionBlocker(BaseModel):
    code: str
    message: str


class ProposalAdministrativeCorrectionChange(BaseModel):
    field: str
    before: Any = None
    after: Any = None


class ProposalAdministrativeCorrectionOption(BaseModel):
    target_area: str
    target_status: str
    label: str
    description: str
    changed_fields: list[str] = Field(default_factory=list)


class ProposalAdministrativeCorrectionOptionsResponse(BaseModel):
    proposal_id: int
    proposal_number: str
    version: int
    correction_type: Literal["STATE"] = "STATE"
    current_state: dict[str, Any]
    facts: dict[str, Any]
    options: list[ProposalAdministrativeCorrectionOption] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProposalAdministrativeCorrectionPreviewResponse(BaseModel):
    allowed: bool
    correction_type: Literal["STATE"] = "STATE"
    expected_version: int
    current_state: dict[str, Any]
    requested_state: dict[str, Any]
    changes: list[ProposalAdministrativeCorrectionChange] = Field(default_factory=list)
    effects: list[str] = Field(default_factory=list)
    unchanged_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[ProposalAdministrativeCorrectionBlocker] = Field(default_factory=list)


class ProposalStatusResponse(BaseModel):
    id: int
    current_area: str
    current_status: str
    version: int
    active: bool


class ProductionProgress(BaseModel):
    total_items: int
    internal_items: int
    produced_items: int
    pending_items: int
    undefined_flow_items: int
    missing_weight_items: int
    needs_galvanization_items: int
    no_galvanization_items: int
    total_weight: Decimal
    produced_weight: Decimal
    pending_weight: Decimal
    reallocated_production_pending: Decimal = Decimal("0")
    reallocated_production_completed: Decimal = Decimal("0")
    weight_known_items: int = 0
    weight_total_items: int = 0
    weight_complete: bool = False
    next_destination: str | None = None
    summary_status: str


class ProductionAction(BaseModel):
    id: str
    label: str
    enabled: bool = True
    reason: str | None = None


class ProductionProposalListItem(ProposalListItem):
    production_status: str | None = None
    general_status: str | None = None
    progress: ProductionProgress
    actions: list[ProductionAction] = Field(default_factory=list)


class PaginatedProductionResponse(BaseModel):
    items: list[ProductionProposalListItem]
    total: int
    limit: int
    offset: int


class ProductionProposalDetail(ProposalDetail):
    progress: ProductionProgress
    actions: list[ProductionAction] = Field(default_factory=list)


class ProductionItemRow(BaseModel):
    proposal_id: int
    proposal_number: str
    customer_name: str
    project_name: str | None = None
    lot: str | None = None
    proposal_version: int
    proposal_status: str
    item_id: int
    item_number: str
    product_code: str | None = None
    description: str | None = None
    quantity: Decimal
    unit: str | None = None
    unit_weight: Decimal | None = None
    total_weight: Decimal | None = None
    produce_internally: str
    requires_galvanization: str
    flow_defined: bool
    produced: bool
    production_pending_quantity: Decimal = Decimal("0")
    reallocated_production_pending: Decimal = Decimal("0")
    notes: str | None = None
    version: int


class PaginatedProductionItemResponse(BaseModel):
    items: list[ProductionItemRow]
    total: int
    limit: int
    offset: int


class ProductionStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    observation: str | None = Field(default=None, max_length=500)


class ProductionPauseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class ProductionResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    observation: str | None = Field(default=None, max_length=500)

    @field_validator("observation", mode="before")
    @classmethod
    def strip_observation(cls, value):
        if not isinstance(value, str):
            return value
        return value.strip() or None


class ProductionItemFlowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: int = Field(gt=0)
    version: int | None = Field(default=None, ge=1)
    produce_internally: bool | None = None
    non_production_reason: str | None = Field(default=None, max_length=500)
    requires_galvanization: bool | None = None
    notes: str | None = None


class ProductionItemFlowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    origin: str = Field(default="Producao", max_length=80)
    items: list[ProductionItemFlowDefinition] = Field(min_length=1)


class ProductionItemWeightUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: int = Field(gt=0)
    version: int | None = Field(default=None, ge=1)
    unit_weight: Decimal = Field(ge=0)


class ProductionItemWeightsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    items: list[ProductionItemWeightUpdate] = Field(min_length=1)


class ProductionCompleteItemsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    item_ids: list[int] | None = None
    observation: str | None = Field(default=None, max_length=500)


class GalvanizationCandidateItem(BaseModel):
    proposal_id: int
    parent_proposal_id: int | None = None
    partial_number: int | None = None
    proposal_number: str
    customer_name: str
    project_name: str | None = None
    lot: str | None = None
    item_id: int
    item_number: str
    product_code: str | None = None
    description: str
    quantity: Decimal
    available_quantity: Decimal
    unit_weight: Decimal | None = None
    available_weight: Decimal | None = None
    sent_quantity: Decimal
    sent_weight: Decimal | None = None
    production_completed_at: datetime | None = None
    priority: str | None = None
    notes: str | None = None
    version: int
    situation: str


class PaginatedGalvanizationCandidateResponse(BaseModel):
    items: list[GalvanizationCandidateItem]
    total: int
    limit: int
    offset: int


class GalvanizationLoadItemSummary(BaseModel):
    id: int
    load_id: int
    proposal_id: int
    parent_proposal_id: int | None = None
    partial_number: int | None = None
    proposal_number: str
    customer_name: str
    proposal_item_id: int
    item_number: str
    product_code: str | None = None
    description: str
    sent_quantity: Decimal
    returned_quantity: Decimal
    pending_quantity: Decimal
    unit_weight: Decimal | None = None
    sent_weight: Decimal | None = None
    returned_weight: Decimal | None = None
    pending_weight: Decimal | None = None
    status: str
    version: int
    returned_at: datetime | None = None
    active: bool = True


class GalvanizationLoadProposalSummary(BaseModel):
    proposal_id: int
    proposal_number: str
    customer_name: str
    project_name: str | None = None
    sent_weight: Decimal
    returned_weight: Decimal
    pending_weight: Decimal
    weight_known_items: int = 0
    weight_total_items: int = 0
    item_count: int
    pending_item_count: int
    status: str


class GalvanizationLoadHistoryEntry(BaseModel):
    id: int
    event_type: str
    load_item_id: int | None = None
    proposal_id: int | None = None
    proposal_item_id: int | None = None
    actor_user_id: int | None = None
    actor_name: str | None = None
    request_id: str | None = None
    from_status: str | None = None
    to_status: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class GalvanizationLoadReturnItemSummary(BaseModel):
    event_id: int
    load_item_id: int | None = None
    proposal_id: int | None = None
    proposal_number: str | None = None
    proposal_item_id: int | None = None
    item_number: str | None = None
    product_code: str | None = None
    description: str | None = None
    returned_quantity: Decimal
    unit_weight: Decimal | None = None
    returned_weight: Decimal | None = None


class GalvanizationLoadReturnSummary(BaseModel):
    id: int
    request_id: str | None = None
    occurred_at: datetime
    actor_user_id: int | None = None
    actor_name: str | None = None
    from_status: str | None = None
    to_status: str | None = None
    observation: str | None = None
    return_type: str
    returned_weight: Decimal | None = None
    weight_known_items: int = 0
    weight_total_items: int = 0
    items: list[GalvanizationLoadReturnItemSummary] = Field(default_factory=list)


class GalvanizationLoadSummary(BaseModel):
    id: int
    code: str | None = None
    driver_name: str
    max_weight: Decimal | None = None
    load_weight: Decimal | None = None
    load_weight_source: str | None = None
    load_weight_updated_at: datetime | None = None
    total_weight: Decimal
    known_items_weight: Decimal = Decimal("0")
    weight_known_items: int = 0
    weight_total_items: int = 0
    weight_complete: bool = False
    status: str
    expected_return_date: date | None = None
    sent_at: datetime | None = None
    returned_at: datetime | None = None
    closed_at: datetime | None = None
    notes: str | None = None
    version: int
    active: bool
    created_at: datetime
    updated_at: datetime
    proposal_count: int
    item_count: int
    returned_item_count: int
    pending_item_count: int
    pending_weight: Decimal
    overdue: bool = False


class PaginatedGalvanizationLoadResponse(BaseModel):
    items: list[GalvanizationLoadSummary]
    total: int
    limit: int
    offset: int


class GalvanizationLoadDetail(GalvanizationLoadSummary):
    created_by_user_id: int | None = None
    created_by_name: str | None = None
    updated_by_user_id: int | None = None
    updated_by_name: str | None = None
    proposals: list[GalvanizationLoadProposalSummary] = Field(default_factory=list)
    items: list[GalvanizationLoadItemSummary] = Field(default_factory=list)
    returns: list[GalvanizationLoadReturnSummary] = Field(default_factory=list)
    history: list[GalvanizationLoadHistoryEntry] = Field(default_factory=list)


class GalvanizationLoadItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_item_id: int = Field(gt=0)
    version: int | None = Field(default=None, ge=1)
    sent_quantity: Decimal | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=500)


class GalvanizationLoadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver_name: str = Field(min_length=1, max_length=180)
    max_weight: Decimal | None = Field(default=None, gt=0)
    load_weight: Decimal | None = Field(default=None, gt=0)
    load_weight_source: str | None = Field(default="MANUAL", max_length=20)
    expected_return_date: date | None = None
    notes: str | None = Field(default=None, max_length=1000)
    items: list[GalvanizationLoadItemInput] = Field(min_length=1)

    @field_validator("driver_name", mode="before")
    @classmethod
    def strip_driver(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("load_weight_source")
    @classmethod
    def validate_load_weight_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if normalized not in {"MANUAL", "BALANCA", "GALVANIZADOR", "OUTRO"}:
            raise ValueError("origem do peso da carga invalida")
        return normalized


class GalvanizationLoadUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    driver_name: str | None = Field(default=None, min_length=1, max_length=180)
    max_weight: Decimal | None = Field(default=None, gt=0)
    load_weight: Decimal | None = Field(default=None, gt=0)
    load_weight_source: str | None = Field(default=None, max_length=20)
    expected_return_date: date | None = None
    notes: str | None = Field(default=None, max_length=1000)
    items: list[GalvanizationLoadItemInput] | None = None

    @field_validator("load_weight_source")
    @classmethod
    def validate_load_weight_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if normalized not in {"MANUAL", "BALANCA", "GALVANIZADOR", "OUTRO"}:
            raise ValueError("origem do peso da carga invalida")
        return normalized


class GalvanizationLoadVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    observation: str | None = Field(default=None, max_length=1000)


class GalvanizationReturnItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    load_item_id: int | None = Field(default=None, gt=0)
    proposal_item_id: int | None = Field(default=None, gt=0)
    quantity_returned: Decimal | None = Field(default=None, gt=0)


class GalvanizationReturnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    proposal_ids: list[int] | None = None
    items: list[GalvanizationReturnItemInput] | None = None
    observation: str | None = Field(default=None, max_length=1000)


class ExpeditionItemSummary(BaseModel):
    id: int
    proposal_id: int
    proposal_item_id: int
    item_number: str
    product_code: str | None = None
    description: str
    available_quantity: Decimal
    separated_quantity: Decimal
    delivered_quantity: Decimal
    remanaged_quantity: Decimal
    pending_quantity: Decimal
    unit_weight: Decimal | None = None
    total_weight: Decimal | None = None
    origin: str
    status: str
    version: int


class ExpeditionProposalSummary(BaseModel):
    id: int
    parent_proposal_id: int | None = None
    partial_number: int | None = None
    proposal_number: str
    customer_name: str
    project_name: str | None = None
    lot: str | None = None
    shipping_status: str | None = None
    general_status: str | None = None
    version: int
    item_count: int
    available_quantity: Decimal
    separated_quantity: Decimal
    delivered_quantity: Decimal
    pending_quantity: Decimal
    origins: list[str] = Field(default_factory=list)
    actions: list[ProductionAction] = Field(default_factory=list)


class PaginatedExpeditionResponse(BaseModel):
    items: list[ExpeditionProposalSummary]
    total: int
    limit: int
    offset: int


class ExpeditionProposalDetail(ExpeditionProposalSummary):
    items: list[ExpeditionItemSummary] = Field(default_factory=list)


class ExpeditionVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    observation: str | None = Field(default=None, max_length=1000)


class ExpeditionItemQuantityInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expedition_item_id: int | None = Field(default=None, gt=0)
    proposal_item_id: int | None = Field(default=None, gt=0)
    version: int | None = Field(default=None, ge=1)
    quantity: Decimal | None = Field(default=None, gt=0)


class ExpeditionItemsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    items: list[ExpeditionItemQuantityInput] | None = None
    observation: str | None = Field(default=None, max_length=1000)


class ExpeditionRemanageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    items: list[ExpeditionItemQuantityInput] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=1000)


class RemanagementItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_item_id: int = Field(gt=0)
    destination_item_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0)
    source_item_version: int | None = Field(default=None, ge=1)
    destination_item_version: int | None = Field(default=None, ge=1)


class ExpeditionRemanagementDeliveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_proposal_id: int = Field(gt=0)
    destination_proposal_id: int = Field(gt=0)
    source_version: int = Field(ge=1)
    destination_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=100)
    items: list[RemanagementItemInput] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason", "idempotency_key", mode="before")
    @classmethod
    def strip_remanagement_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class RemanagementItemBalance(BaseModel):
    source_item_id: int
    destination_item_id: int
    product_code: str | None = None
    unit: str | None = None
    quantity: Decimal
    max_remanageable: Decimal
    source_ready_before: Decimal
    source_ready_after: Decimal
    destination_ready_before: Decimal
    destination_ready_after: Decimal
    destination_need_before: Decimal
    destination_need_after: Decimal
    destination_reallocatable_production_before: Decimal
    destination_reallocatable_production_after: Decimal
    production_reallocated_quantity: Decimal
    weight_snapshot: Decimal | None = None


class RemanagementPreview(BaseModel):
    source_proposal_id: int
    destination_proposal_id: int
    source_version: int
    destination_version: int
    total_quantity: Decimal
    items: list[RemanagementItemBalance]


class RemanagementSummary(RemanagementPreview):
    id: int
    code: str
    status: str
    reason: str
    idempotency_key: str
    request_id: str | None = None
    correlation_id: str | None = None
    created_by: int | None = None
    created_at: datetime


class PaginatedRemanagementResponse(BaseModel):
    items: list[RemanagementSummary]
    total: int
    limit: int
    offset: int


class RemanagementCompatibleItem(BaseModel):
    source_item_id: int
    destination_item_id: int
    source_item_number: str
    destination_item_number: str
    product_code: str | None = None
    description: str
    unit: str | None = None
    source_item_version: int
    destination_item_version: int
    source_ready_available: Decimal
    destination_need: Decimal
    destination_reallocatable_production: Decimal
    max_remanageable: Decimal
    weight_snapshot: Decimal | None = None


class RemanagementDestinationItem(BaseModel):
    item_id: int
    item_version: int
    item_number: str
    product_code: str | None = None
    description: str
    unit: str | None = None
    total_quantity: Decimal
    already_attended: Decimal
    remanageable_need: Decimal
    selectable: bool
    block_reason: str | None = None


class RemanagementAvailabilityItemRequest(BaseModel):
    destination_item_id: int
    requested_quantity: Decimal = Field(gt=0)


class RemanagementAvailabilityRequest(BaseModel):
    destination_proposal_id: int
    items: list[RemanagementAvailabilityItemRequest] = Field(min_length=1)


class RemanagementSourceCandidate(BaseModel):
    source_proposal_id: int
    source_proposal_number: str
    source_item_id: int
    source_item_version: int
    client: str
    site: str | None = None
    available_quantity: Decimal
    unit: str | None = None
    operational_status: str | None = None


class RemanagementDestinationItemAvailability(BaseModel):
    destination_item_id: int
    product_code: str
    description: str
    unit: str | None = None
    requested_quantity: Decimal
    total_available: Decimal
    coverage_status: str
    candidates: list[RemanagementSourceCandidate]


class RemanagementAvailabilityResponse(BaseModel):
    destination_proposal_id: int
    items: list[RemanagementDestinationItemAvailability]


class RemanagementCompensationItemRequest(BaseModel):
    destination_item_id: int
    requested_quantity: Decimal = Field(gt=0)


class RemanagementCompensationAllocationRequest(BaseModel):
    destination_item_id: int
    source_proposal_id: int
    source_item_id: int
    allocated_quantity: Decimal = Field(gt=0)


class RemanagementCompensationRequest(BaseModel):
    destination_proposal_id: int
    items: list[RemanagementCompensationItemRequest] = Field(min_length=1)
    allocations: list[RemanagementCompensationAllocationRequest] = Field(min_length=1)


class CompensationTransfer(BaseModel):
    source_proposal_id: int
    source_item_id: int
    ready_quantity_to_destination: Decimal
    obligation_quantity_to_source: Decimal


class CompensationProductPlan(BaseModel):
    product_code: str
    destination_item_id: int
    total_to_receive: Decimal
    allocated_quantity: Decimal
    remaining_quantity: Decimal
    coverage: str
    transfers: list[CompensationTransfer]


class CompensationPlanError(BaseModel):
    code: str
    message: str
    destination_item_id: int | None = None
    source_item_id: int | None = None


class FutureMutationPlanOut(BaseModel):
    expedition_ready_transfers: list[dict]
    production_obligation_transfers: list[dict]
    status_recalculations: list[dict]
    movement_records: list[dict]


class RemanagementCompensationPlanResponse(BaseModel):
    destination_proposal_id: int
    products: list[CompensationProductPlan]
    affected_proposals: list[int]
    total_ready_transferred: Decimal
    total_obligation_transferred: Decimal
    future_mutations: FutureMutationPlanOut
    warnings: list[str]
    errors: list[CompensationPlanError]
    valid: bool


class RemanagementReviewRequest(BaseModel):
    destination_proposal_id: int
    items: list[RemanagementCompensationItemRequest] = Field(min_length=1)
    allocations: list[RemanagementCompensationAllocationRequest] = Field(min_length=1)
    # Sem min_length de proposito: "Revalidar" pode ser chamado antes do
    # usuario preencher o motivo. A ausencia vira um CompensationPlanError
    # estruturado (REASON_REQUIRED) em vez de um 422 cru.
    reason: str = Field(default="", max_length=1000)


class RemanagementReviewSource(BaseModel):
    source_proposal_id: int
    source_item_id: int
    ready_transfer: Decimal
    production_compensation: Decimal
    source_before: Decimal
    source_after_simulated: Decimal


class RemanagementReviewItem(BaseModel):
    destination_item_id: int
    product_code: str
    requested: Decimal
    allocated: Decimal
    remaining: Decimal
    status: str
    sources: list[RemanagementReviewSource]


class RemanagementReviewSummary(BaseModel):
    product_count: int
    source_proposal_count: int
    source_item_count: int
    total_quantity: Decimal | None = None
    total_unit: str | None = None
    complete_items: int
    partial_items: int
    not_allocated_items: int
    invalid_items: int


class RemanagementReviewResult(BaseModel):
    destination_proposal_id: int
    valid: bool
    warnings: list[str]
    errors: list[CompensationPlanError]
    summary: RemanagementReviewSummary
    items: list[RemanagementReviewItem]


class RemanagementConfirmRequest(BaseModel):
    operation_id: str = Field(min_length=8, max_length=100)
    destination_proposal_id: int
    items: list[RemanagementCompensationItemRequest] = Field(min_length=1)
    allocations: list[RemanagementCompensationAllocationRequest] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason", "operation_id", mode="before")
    @classmethod
    def strip_confirm_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class RemanagementConfirmSourceSummary(BaseModel):
    source_proposal_id: int
    remanagement_id: int
    code: str


class RemanagementConfirmResult(BaseModel):
    operation_id: str
    status: str
    destination_proposal_id: int
    source_proposals: list[int]
    products: int
    allocations: int
    confirmed_at: datetime
    remanagements: list[RemanagementConfirmSourceSummary]


class FiscalAction(BaseModel):
    id: str
    label: str
    enabled: bool = True
    reason: str | None = None


class FiscalItemSummary(BaseModel):
    id: int
    fiscal_record_id: int
    proposal_id: int
    proposal_item_id: int
    item_number: str
    product_code: str | None = None
    description: str
    total_quantity: Decimal
    billed_quantity: Decimal
    pending_quantity: Decimal
    total_weight: Decimal | None = None
    billed_weight: Decimal
    pending_weight: Decimal | None = None
    status: str
    version: int


class FiscalInvoiceItemSummary(BaseModel):
    id: int
    fiscal_invoice_id: int
    fiscal_item_id: int
    proposal_item_id: int
    item_number: str
    quantity: Decimal
    weight: Decimal | None = None
    active: bool
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None


class FiscalInvoiceSummary(BaseModel):
    id: int
    fiscal_record_id: int
    proposal_id: int
    invoice_number: str
    series: str | None = None
    access_key: str | None = None
    issued_at: datetime
    emission_type: str
    status: str
    source: str
    observation: str | None = None
    version: int
    item_count: int
    quantity: Decimal
    weight: Decimal
    items: list[FiscalInvoiceItemSummary] = Field(default_factory=list)


class FiscalEventSummary(BaseModel):
    id: int
    event_type: str
    from_status: str | None = None
    to_status: str | None = None
    actor_user_id: int | None = None
    created_at: datetime
    metadata: dict | None = None


class FiscalRecordSummary(BaseModel):
    id: int
    proposal_id: int
    parent_proposal_id: int | None = None
    partial_number: int | None = None
    proposal_number: str
    customer_name: str
    project_name: str | None = None
    lot: str | None = None
    current_area: str | None = None
    current_status: str | None = None
    shipping_status: str | None = None
    status_fiscal: str
    fiscal_situation: str
    entry_date: date
    last_emission_at: datetime | None = None
    invoice_withdrawn_at: datetime | None = None
    version: int
    item_count: int
    pending_items: int
    billed_items: int
    total_weight: Decimal
    billed_weight: Decimal
    pending_weight: Decimal
    weight_known_items: int = 0
    weight_total_items: int = 0
    weight_complete: bool = False
    critical_pending: bool = False
    older_than_7_days: bool = False
    actions: list[FiscalAction] = Field(default_factory=list)


class FiscalRecordDetail(FiscalRecordSummary):
    items: list[FiscalItemSummary] = Field(default_factory=list)
    invoices: list[FiscalInvoiceSummary] = Field(default_factory=list)
    events: list[FiscalEventSummary] = Field(default_factory=list)


class PaginatedFiscalResponse(BaseModel):
    items: list[FiscalRecordSummary]
    total: int
    limit: int
    offset: int


class FiscalIndicators(BaseModel):
    falta_emitir: int
    nf_parcial: int
    nf_emitida: int
    pendencia_critica: int
    entregues_sem_nf: int
    peso_pendente: Decimal
    peso_faturado: Decimal
    mais_7_dias_sem_emissao: int


class FiscalEmissionItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fiscal_item_id: int | None = Field(default=None, gt=0)
    proposal_item_id: int | None = Field(default=None, gt=0)
    version: int | None = Field(default=None, ge=1)
    quantity: Decimal | None = Field(default=None, gt=0)
    weight: Decimal | None = Field(default=None, ge=0)


class FiscalRegisterInvoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    invoice_number: str = Field(min_length=1, max_length=80)
    series: str | None = Field(default=None, max_length=40)
    access_key: str | None = Field(default=None, max_length=80)
    issued_at: datetime | None = None
    source: str = Field(default="MANUAL", max_length=40)
    observation: str | None = Field(default=None, max_length=1000)
    items: list[FiscalEmissionItemInput] | None = None

    @field_validator("invoice_number", "series", "access_key", "source", mode="before")
    @classmethod
    def strip_fiscal_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("source")
    @classmethod
    def validate_fiscal_source(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"MANUAL", "NOMUS", "SYSTEM"}:
            raise ValueError("origem fiscal invalida")
        return normalized


class FiscalBatchProposalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fiscal_record_id: int = Field(gt=0)
    version: int = Field(ge=1)
    selection_type: str = Field(default="TOTAL", max_length=20)
    invoice_number: str = Field(min_length=1, max_length=80)
    series: str | None = Field(default=None, max_length=40)
    issued_at: datetime | None = None
    source: str = Field(default="MANUAL", max_length=40)
    observation: str | None = Field(default=None, max_length=1000)
    items: list[FiscalEmissionItemInput] | None = None

    @field_validator("invoice_number", "series", "source", mode="before")
    @classmethod
    def strip_batch_fiscal_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("selection_type")
    @classmethod
    def validate_selection_type(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"TOTAL", "PARCIAL"}:
            raise ValueError("tipo de selecao fiscal invalido")
        return normalized

    @field_validator("source")
    @classmethod
    def validate_batch_source(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"MANUAL", "NOMUS", "SYSTEM"}:
            raise ValueError("origem fiscal invalida")
        return normalized


class FiscalBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str | None = Field(default=None, max_length=120)
    proposals: list[FiscalBatchProposalInput] = Field(min_length=1, max_length=200)


class FiscalBatchProposalResult(BaseModel):
    fiscal_record_id: int
    emission_id: int
    invoice_number: str
    series: str | None = None
    final_status: str


class FiscalBatchResponse(BaseModel):
    operation_id: str
    status: str
    proposals: list[FiscalBatchProposalResult]


class FiscalCancelInvoiceItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class FiscalWithdrawalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    observation: str | None = Field(default=None, max_length=1000)


class ProposalItemSyncPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legacy_id: int = Field(gt=0)
    legacy_current_process_id: int | None = Field(default=None, gt=0)
    item_number: str = Field(min_length=1, max_length=80)
    product_code: str | None = Field(default=None, max_length=120)
    description: str | None = None
    quantity: Decimal = Field(ge=0)
    unit: str | None = Field(default=None, max_length=40)
    unit_weight: Decimal = Field(ge=0)
    total_weight: Decimal = Field(ge=0)
    produce_internally: str = Field(max_length=20)
    requires_galvanization: str = Field(max_length=20)
    flow_defined: bool = False
    produced: bool = False
    galvanized: bool = False
    delivered: bool = False
    delivered_at: datetime | None = None
    legacy_created_at: datetime | None = None
    legacy_updated_at: datetime | None = None
    source_hash: str = Field(min_length=64, max_length=64)

    @field_validator("item_number", "product_code", "unit", "produce_internally", "requires_galvanization", mode="before")
    @classmethod
    def strip_short_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class ProposalSyncPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legacy_id: int = Field(gt=0)
    proposal_number: str = Field(min_length=1, max_length=80)
    customer_name: str = Field(min_length=1, max_length=180)
    project_name: str | None = Field(default=None, max_length=180)
    order_reference: str | None = Field(default=None, max_length=120)
    lot: str | None = Field(default=None, max_length=80)
    proposal_date: date | None = None
    deadline_date: date | None = None
    current_area: str | None = Field(default=None, max_length=80)
    current_status: str | None = Field(default=None, max_length=120)
    general_status: str | None = Field(default=None, max_length=120)
    production_status: str | None = Field(default=None, max_length=120)
    galvanization_status: str | None = Field(default=None, max_length=120)
    shipping_status: str | None = Field(default=None, max_length=120)
    warehouse_status: str | None = Field(default=None, max_length=120)
    flow_situation: str | None = Field(default=None, max_length=120)
    has_production_pending: bool = False
    process_type: str | None = Field(default=None, max_length=80)
    parent_legacy_id: int | None = None
    partial_number: int | None = None
    is_partial: bool = False
    is_cancelled: bool = False
    is_completed: bool = False
    source: str = Field(default="sqlite", max_length=80)
    legacy_created_at: datetime | None = None
    legacy_updated_at: datetime | None = None
    source_hash: str = Field(min_length=64, max_length=64)
    items: list[ProposalItemSyncPayload] = Field(default_factory=list)

    @field_validator("proposal_number", "customer_name", "project_name", "order_reference", "lot", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class ProposalSyncBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_identifier: str = Field(min_length=1, max_length=300)
    dry_run: bool = False
    batch_number: int = Field(default=1, ge=1)
    batch_total: int = Field(default=1, ge=1)
    proposals: list[ProposalSyncPayload] = Field(default_factory=list, max_length=200)


class SyncSummary(BaseModel):
    received: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: int = 0
    errors: list[str] = Field(default_factory=list)
    dry_run: bool = False
    sync_run_id: int | None = None
    item_created: int = 0
    item_updated: int = 0
    item_unchanged: int = 0
