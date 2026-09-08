from __future__ import annotations

from typing import Callable

from app.ui.action_center.context import ProposalActionContext
from app.ui.action_center.descriptor import ActionDescriptor
from app.ui.action_center.result import ActionResult

LegacyCallback = Callable[[ProposalActionContext, ActionDescriptor, object], ActionResult]


class LegacyActionHandler:
    """Compatibility layer for actions not migrated in this phase
    (Galvanizacao/Expedicao). Wraps a callback that opens exactly the dialog
    the old StatusDialog opened - no logic is reimplemented, only re-routed
    through the registry instead of an if/elif chain. Lets callers avoid a
    big-bang migration of domains explicitly out of scope for this phase."""

    def __init__(self, callback: LegacyCallback):
        self._callback = callback

    def execute(self, context: ProposalActionContext, action: ActionDescriptor, dialog) -> ActionResult:
        return self._callback(context, action, dialog)
