from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ActionCategory(str, Enum):
    """Visual classification of an action card. Purely presentational - never
    a substitute for the availability/permission decision the domain already
    made before the action reached the provider."""

    PRIMARY = "primary"
    NORMAL = "normal"
    ATTENTION = "attention"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class ActionDescriptor:
    """Everything the Action Center needs to identify, present and route a
    single action - nothing else. No business rule belongs here: whether the
    action is available at all is decided upstream, by the domain."""

    id: str
    label: str
    description: str
    icon: str | None
    category: ActionCategory
    area: str
    order: int = 0
    status: str = ""
    group: str = "operations"
    raw: dict = field(default_factory=dict, compare=False)
