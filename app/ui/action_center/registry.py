from __future__ import annotations

from app.ui.action_center.handler import ProposalActionHandler


class ActionRegistry:
    """Relates an action_id to the handler responsible for it. Resolves
    actions and finds handlers - nothing else. It does not know about the
    database, the API, widgets, or users.

    Some backend action ids are shared by transitions that mean entirely
    different things in different areas (e.g. "STATUS" covers Producao's
    iniciar/pausar and Controle Geral's liberar/cancelar). Registering a
    handler with `area=` scopes it to that area only; `resolve()` prefers an
    area-scoped handler and falls back to the area-agnostic one."""

    def __init__(self) -> None:
        self._handlers: dict[str, ProposalActionHandler] = {}
        self._area_handlers: dict[tuple[str, str], ProposalActionHandler] = {}

    def register(self, action_id: str, handler: ProposalActionHandler, area: str | None = None) -> None:
        if area is None:
            self._handlers[action_id] = handler
        else:
            self._area_handlers[(area, action_id)] = handler

    def resolve(self, action_id: str, area: str | None = None) -> ProposalActionHandler | None:
        if area is not None:
            handler = self._area_handlers.get((area, action_id))
            if handler is not None:
                return handler
        return self._handlers.get(action_id)

    def __contains__(self, action_id: str) -> bool:
        if action_id in self._handlers:
            return True
        return any(key[1] == action_id for key in self._area_handlers)
