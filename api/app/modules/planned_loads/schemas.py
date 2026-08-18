from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PlannedLoadItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_item_id: int = Field(gt=0)
    planned_quantity: Decimal = Field(gt=0)
    notes: str | None = Field(default=None, max_length=500)


class PlannedLoadItemsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PlannedLoadItemInput] = Field(min_length=1)


class PlannedLoadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, max_length=40)
    expected_ship_date: date | None = None
    carrier_name: str | None = Field(default=None, max_length=180)
    vehicle_info: str | None = Field(default=None, max_length=180)
    responsible_user_id: int | None = None
    notes: str | None = Field(default=None, max_length=1000)
    items: list[PlannedLoadItemInput] = Field(default_factory=list)


class PlannedLoadUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    expected_ship_date: date | None = None
    carrier_name: str | None = Field(default=None, max_length=180)
    vehicle_info: str | None = Field(default=None, max_length=180)
    responsible_user_id: int | None = None
    notes: str | None = Field(default=None, max_length=1000)


class PlannedLoadItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    planned_quantity: Decimal | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=500)


class PlannedLoadItemSummary(BaseModel):
    id: int
    proposal_id: int
    proposal_number: str
    customer_name: str
    proposal_item_id: int
    item_number: str
    product_code: str | None = None
    description: str
    total_quantity: Decimal
    planned_quantity: Decimal
    # Disponibilidade/divergencia real (FASE_PL2) computada em
    # service._annotate_loads. Defaults abaixo so entram em jogo se algum
    # caminho futuro montar este schema sem passar por la.
    currently_available_quantity: Decimal = Decimal("0")
    missing_quantity: Decimal
    free_for_other_plans_quantity: Decimal = Decimal("0")
    has_divergence: bool = False
    divergence_reason: str | None = None
    current_area: str | None = None
    current_status: str | None = None
    notes: str | None = None
    version: int
    active: bool


class PlannedLoadHistoryEntry(BaseModel):
    id: int
    event_type: str
    from_status: str | None = None
    to_status: str | None = None
    actor_user_id: int | None = None
    actor_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class PlannedLoadSummary(BaseModel):
    id: int
    code: str
    status: str
    expected_ship_date: date | None = None
    carrier_name: str | None = None
    vehicle_info: str | None = None
    responsible_user_id: int | None = None
    responsible_user_name: str | None = None
    notes: str | None = None
    total_planned_quantity: Decimal
    total_available_quantity: Decimal = Decimal("0")
    total_missing_quantity: Decimal
    converted_load_id: int | None = None
    version: int
    active: bool
    created_at: datetime
    updated_at: datetime


class PaginatedPlannedLoadResponse(BaseModel):
    items: list[PlannedLoadSummary]
    total: int
    limit: int
    offset: int


class PlannedLoadDetail(PlannedLoadSummary):
    items: list[PlannedLoadItemSummary] = Field(default_factory=list)
    history: list[PlannedLoadHistoryEntry] = Field(default_factory=list)


class PlannedLoadVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


class PlannedLoadBuildReadyItem(BaseModel):
    proposal_item_id: int
    item_number: str
    description: str
    planned_quantity: Decimal
    available_quantity: Decimal


class PlannedLoadBuildPendingItem(BaseModel):
    proposal_item_id: int
    item_number: str
    description: str
    planned_quantity: Decimal
    available_quantity: Decimal
    missing_quantity: Decimal


class PlannedLoadBuildResult(BaseModel):
    planned_load_id: int
    fully_available: bool
    total_planned_quantity: Decimal
    total_available_quantity: Decimal
    total_missing_quantity: Decimal
    ready_items: list[PlannedLoadBuildReadyItem] = Field(default_factory=list)
    pending_items: list[PlannedLoadBuildPendingItem] = Field(default_factory=list)


class PlannedLoadConvertedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    real_load_id: int = Field(gt=0)
