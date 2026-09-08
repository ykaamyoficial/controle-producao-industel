from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from app.ui.action_center.context import ProposalActionContext
from app.ui.action_center.descriptor import ActionDescriptor
from app.ui.action_center.result import ActionResult

if TYPE_CHECKING:
    from app.ui.action_center.proposal_action_center import ProposalActionCenter


class ProposalActionHandler(Protocol):
    """Routes one action to its specialized dialog/service call. A handler
    prepares context, opens the specialized dialog, delegates the operation
    and returns a result - it never recalculates a rule the domain already
    owns."""

    def execute(
        self,
        context: ProposalActionContext,
        action: ActionDescriptor,
        dialog: "ProposalActionCenter",
    ) -> ActionResult: ...
