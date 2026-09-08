from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ActionResult:
    """What the Action Center should do after a handler ran. A user
    cancelling a specialized dialog is a normal result (success=True,
    changed=False), never an exception."""

    success: bool
    changed: bool = False
    refresh_required: bool = False
    close_action_center: bool = True
    message: str = ""
