from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.ui.action_center.descriptor import ActionDescriptor


@dataclass(frozen=True)
class ProposalActionContext:
    """Which proposal, in which area and state, the Action Center is
    operating on. Identity is always the real proposal/process id - never a
    table row index, a QModelIndex, or any other visual position."""

    proposal_id: int
    area: str
    current_status: str | None
    proposal_number: str
    client_name: str | None
    proposal_data: dict[str, Any] = field(default_factory=dict)
    available_actions: tuple[ActionDescriptor, ...] = field(default_factory=tuple)
    can_admin: bool = False
