from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from app.ui.numeric_utils import format_decimal


class FlowRoute(Enum):
    INDEFINIDO = "indefinido"
    PRODUZIR_GALVANIZAR = "produzir_galvanizar"
    PRODUZIR_SEM_GALVANIZAR = "produzir_sem_galvanizar"
    NAO_PRODUZIR = "nao_produzir"
    NAO_PRODUZIR_GALVANIZAR = "nao_produzir_galvanizar"


@dataclass(frozen=True)
class RouteInfo:
    label: str
    produce: str  # "SIM" | "NAO" | "INDEFINIDO" (backend vocabulary)
    galvanize: str
    requires_reason: bool


# Single source of truth mapping the visual "rota" to the two technical backend flags.
# Every combination here is confirmed valid by the backend (no cross-field validation exists
# there beyond "produce == NAO requires a reason"), so all four decided routes are legitimate.
FLOW_ROUTES: dict[FlowRoute, RouteInfo] = {
    FlowRoute.INDEFINIDO: RouteInfo("Nao definido", "INDEFINIDO", "INDEFINIDO", False),
    FlowRoute.PRODUZIR_GALVANIZAR: RouteInfo("Produzir + galvanizar", "SIM", "SIM", False),
    FlowRoute.PRODUZIR_SEM_GALVANIZAR: RouteInfo("Produzir sem galvanizar", "SIM", "NAO", False),
    FlowRoute.NAO_PRODUZIR: RouteInfo("Nao produzir", "NAO", "NAO", True),
    FlowRoute.NAO_PRODUZIR_GALVANIZAR: RouteInfo("Nao produzir, mas galvanizar", "NAO", "SIM", True),
}

# Routes offered as a "fluxo padrao" choice - INDEFINIDO is never a valid default.
DEFAULT_ROUTE_CHOICES = [
    FlowRoute.PRODUZIR_GALVANIZAR,
    FlowRoute.PRODUZIR_SEM_GALVANIZAR,
    FlowRoute.NAO_PRODUZIR,
    FlowRoute.NAO_PRODUZIR_GALVANIZAR,
]

_FLAGS_TO_ROUTE = {(info.produce, info.galvanize): route for route, info in FLOW_ROUTES.items()}
_FLAG_LOWER = {"SIM": "sim", "NAO": "nao", "INDEFINIDO": "indefinido"}


def route_from_flags(produce: Any, galvanize: Any) -> FlowRoute:
    produce_key = str(produce or "INDEFINIDO").strip().upper()
    galvanize_key = str(galvanize or "INDEFINIDO").strip().upper()
    return _FLAGS_TO_ROUTE.get((produce_key, galvanize_key), FlowRoute.INDEFINIDO)


def route_to_flags(route: FlowRoute) -> tuple[str, str]:
    info = FLOW_ROUTES[route]
    return info.produce, info.galvanize


def route_label(route: FlowRoute) -> str:
    return FLOW_ROUTES[route].label


def route_requires_reason(route: FlowRoute) -> bool:
    return FLOW_ROUTES[route].requires_reason


def route_includes_production(route: FlowRoute) -> bool:
    return FLOW_ROUTES[route].produce == "SIM"


class ItemState(Enum):
    PADRAO = "padrao"
    EXCECAO_EXISTENTE = "excecao_existente"
    EXCECAO_CRIADA = "excecao_criada"
    ALTERADO = "alterado"
    NAO_DEFINIDO = "nao_definido"
    BLOQUEADO = "bloqueado"
    COM_PROBLEMA = "com_problema"


ITEM_STATE_LABELS = {
    ItemState.PADRAO: "Padrao",
    ItemState.EXCECAO_EXISTENTE: "Excecao existente",
    ItemState.EXCECAO_CRIADA: "Excecao criada",
    ItemState.ALTERADO: "Alterado",
    ItemState.NAO_DEFINIDO: "Nao definido",
    ItemState.BLOQUEADO: "Bloqueado",
    ItemState.COM_PROBLEMA: "Com problema",
}


@dataclass
class FlowReviewItem:
    proposal_id: int
    item_id: int
    api_version: int
    numero_item: str
    codigo: str
    descricao: str
    quantidade: str
    original_route: FlowRoute
    original_reason: str
    is_editable: bool
    lock_reason: str | None
    proposed_route: FlowRoute = field(init=False)
    proposed_reason: str = field(init=False)
    is_selected: bool = False

    def __post_init__(self) -> None:
        self.proposed_route = self.original_route
        self.proposed_reason = self.original_reason

    @property
    def was_touched(self) -> bool:
        return self.proposed_route != self.original_route or self.proposed_reason != self.original_reason

    def restore_original(self) -> None:
        self.proposed_route = self.original_route
        self.proposed_reason = self.original_reason

    def restore_default(self, default_route: FlowRoute | None) -> None:
        if default_route is None:
            return
        self.proposed_route = default_route
        if not route_requires_reason(default_route):
            self.proposed_reason = ""


@dataclass
class FlowReviewProposal:
    proposal_id: int
    proposal_number: str
    customer_name: str
    loaded_version: int
    items: list[FlowReviewItem]
    default_route: FlowRoute | None = None


def build_proposal(data: dict[str, Any]) -> FlowReviewProposal:
    """Builds review state from the dict returned by BackendService.flow_review_data()."""
    items = []
    for raw in data.get("itens", []):
        route = route_from_flags(raw.get("produzir_internamente"), raw.get("precisa_galvanizacao"))
        items.append(
            FlowReviewItem(
                proposal_id=int(data["proposal_id"]),
                item_id=int(raw["id"]),
                api_version=int(raw.get("api_version") or raw.get("version") or 1),
                numero_item=str(raw.get("numero_item") or ""),
                codigo=str(raw.get("codigo_produto") or "-"),
                descricao=str(raw.get("descricao") or ""),
                quantidade=format_decimal(raw.get("quantidade")),
                original_route=route,
                original_reason=str(raw.get("motivo_nao_produzir") or ""),
                is_editable=bool(raw.get("editavel", True)),
                lock_reason=raw.get("motivo_bloqueio") or None,
            )
        )
    return FlowReviewProposal(
        proposal_id=int(data["proposal_id"]),
        proposal_number=str(data.get("proposta") or ""),
        customer_name=str(data.get("cliente") or ""),
        loaded_version=int(data.get("version") or 0),
        items=items,
    )


def apply_default(
    proposal: FlowReviewProposal,
    route: FlowRoute,
    *,
    scope: str,
    preserve_exceptions: bool,
    overwrite_exceptions: bool = False,
    global_reason: str = "",
) -> int:
    """Applies a default route to eligible items in memory only. Returns items changed.

    scope: "undefined_only" (default, safest) or "all_editable". A global reason
    is copied only to routes that require one and respects the exception policy.
    """
    proposal.default_route = route
    normalized_reason = str(global_reason or "").strip()
    changed = 0
    for item in proposal.items:
        if not item.is_editable:
            continue
        if scope == "undefined_only" and item.original_route != FlowRoute.INDEFINIDO:
            continue
        is_preexisting_exception = item.original_route != FlowRoute.INDEFINIDO and item.original_route != route
        if is_preexisting_exception and preserve_exceptions and not overwrite_exceptions:
            continue

        route_changed = item.proposed_route != route
        reason_changed = False
        item.proposed_route = route
        if route_requires_reason(route):
            preserve_existing_reason = preserve_exceptions and bool((item.proposed_reason or "").strip())
            if normalized_reason and (overwrite_exceptions or not preserve_existing_reason):
                reason_changed = item.proposed_reason != normalized_reason
                item.proposed_reason = normalized_reason
        elif item.proposed_reason:
            item.proposed_reason = ""
            reason_changed = True
        if route_changed or reason_changed:
            changed += 1
    return changed


def apply_default_to_all(
    proposals: list[FlowReviewProposal],
    route: FlowRoute,
    *,
    scope: str,
    preserve_exceptions: bool,
    overwrite_exceptions: bool = False,
    global_reason: str = "",
) -> int:
    return sum(
        apply_default(
            proposal,
            route,
            scope=scope,
            preserve_exceptions=preserve_exceptions,
            overwrite_exceptions=overwrite_exceptions,
            global_reason=global_reason,
        )
        for proposal in proposals
    )


def count_affected_exceptions(proposal: FlowReviewProposal, route: FlowRoute, scope: str) -> int:
    """How many pre-existing exceptions would be overwritten by applying `route` right now."""
    count = 0
    for item in proposal.items:
        if not item.is_editable:
            continue
        if scope == "undefined_only" and item.original_route != FlowRoute.INDEFINIDO:
            continue
        if item.original_route != FlowRoute.INDEFINIDO and item.original_route != route:
            count += 1
    return count


def count_affected_exceptions_all(proposals: list[FlowReviewProposal], route: FlowRoute, scope: str) -> int:
    return sum(count_affected_exceptions(proposal, route, scope) for proposal in proposals)


def apply_route_to_selected(items: list[FlowReviewItem], route: FlowRoute, reason: str = "") -> tuple[int, int]:
    """Bulk-edit the selected items. Returns (changed_count, skipped_locked_count)."""
    changed = 0
    skipped = 0
    for item in items:
        if not item.is_selected:
            continue
        if not item.is_editable:
            skipped += 1
            continue
        item.proposed_route = route
        item.proposed_reason = reason if route_requires_reason(route) else ""
        changed += 1
    return changed, skipped


def validate_item(item: FlowReviewItem) -> list[str]:
    if not item.is_editable:
        if item.was_touched:
            return ["Item bloqueado nao pode ser alterado."]
        return []
    issues = []
    if item.proposed_route == FlowRoute.INDEFINIDO:
        issues.append("Item sem rota definida.")
    elif route_requires_reason(item.proposed_route) and not (item.proposed_reason or "").strip():
        issues.append("Motivo obrigatorio para esta rota.")
    return issues


@dataclass
class ValidationIssue:
    proposal_id: int
    item_id: int | None
    message: str


def validate(proposals: list[FlowReviewProposal]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for proposal in proposals:
        if proposal.loaded_version < 1:
            issues.append(ValidationIssue(proposal.proposal_id, None, "Proposta sem versao valida."))
        seen_ids: set[int] = set()
        for item in proposal.items:
            if item.item_id in seen_ids:
                issues.append(ValidationIssue(proposal.proposal_id, item.item_id, "Item duplicado na revisao."))
            seen_ids.add(item.item_id)
            for message in validate_item(item):
                issues.append(ValidationIssue(proposal.proposal_id, item.item_id, message))
    return issues


def classify(item: FlowReviewItem, default_route: FlowRoute | None) -> ItemState:
    if not item.is_editable:
        return ItemState.BLOQUEADO
    if item.proposed_route == FlowRoute.INDEFINIDO:
        return ItemState.NAO_DEFINIDO
    if validate_item(item):
        return ItemState.COM_PROBLEMA
    if not item.was_touched:
        if default_route is not None and item.original_route != default_route:
            return ItemState.EXCECAO_EXISTENTE
        return ItemState.PADRAO
    if default_route is not None and item.proposed_route == default_route:
        return ItemState.ALTERADO
    return ItemState.EXCECAO_CRIADA


@dataclass
class ReviewSummary:
    proposal_count: int
    item_count: int
    default_count: int
    existing_exception_count: int
    created_exception_count: int
    changed_count: int
    undefined_count: int
    locked_count: int
    problem_count: int


def summarize(proposals: list[FlowReviewProposal]) -> ReviewSummary:
    counts = {state: 0 for state in ItemState}
    total_items = 0
    for proposal in proposals:
        for item in proposal.items:
            total_items += 1
            counts[classify(item, proposal.default_route)] += 1
    return ReviewSummary(
        proposal_count=len(proposals),
        item_count=total_items,
        default_count=counts[ItemState.PADRAO],
        existing_exception_count=counts[ItemState.EXCECAO_EXISTENTE],
        created_exception_count=counts[ItemState.EXCECAO_CRIADA],
        changed_count=counts[ItemState.EXCECAO_CRIADA] + counts[ItemState.ALTERADO],
        undefined_count=counts[ItemState.NAO_DEFINIDO],
        locked_count=counts[ItemState.BLOQUEADO],
        problem_count=counts[ItemState.COM_PROBLEMA],
    )


def build_payload(proposal: FlowReviewProposal) -> list[dict[str, Any]] | None:
    """Only the items with a real change vs. what was loaded. None if nothing changed."""
    items = []
    for item in proposal.items:
        if not item.is_editable or not item.was_touched:
            continue
        produce, galvanize = route_to_flags(item.proposed_route)
        items.append(
            {
                "id": item.item_id,
                "api_version": item.api_version,
                "produzir_internamente": _FLAG_LOWER[produce],
                "precisa_galvanizacao": _FLAG_LOWER[galvanize],
                "motivo_nao_produzir": item.proposed_reason if route_requires_reason(item.proposed_route) else "",
                "observacao_fluxo_item": "",
            }
        )
    return items or None


def select_items(items: list[FlowReviewItem], predicate: Callable[[FlowReviewItem], bool]) -> None:
    for item in items:
        item.is_selected = bool(predicate(item))


def reconcile_after_reload(old_proposal: FlowReviewProposal, fresh_proposal: FlowReviewProposal) -> list[int]:
    """After a 409 version conflict, reapplies the user's pending edits from `old_proposal`
    onto the freshly reloaded `fresh_proposal`, but only where the server's original value
    hasn't changed since the old load. Returns the item_ids with a genuine server-side
    conflict (their original value changed on the server AND the user had edited them
    locally) - those keep the fresh server value and are never silently overwritten."""
    old_by_id = {item.item_id: item for item in old_proposal.items}
    conflicted_ids: list[int] = []
    for fresh_item in fresh_proposal.items:
        old_item = old_by_id.get(fresh_item.item_id)
        if old_item is None or not old_item.was_touched:
            continue
        server_changed = fresh_item.original_route != old_item.original_route or fresh_item.original_reason != old_item.original_reason
        if server_changed:
            conflicted_ids.append(fresh_item.item_id)
            continue
        if not fresh_item.is_editable:
            continue
        fresh_item.proposed_route = old_item.proposed_route
        fresh_item.proposed_reason = old_item.proposed_reason
    return conflicted_ids
