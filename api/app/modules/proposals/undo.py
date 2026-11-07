"""Desfazer a ultima acao de uma proposta (v1).

Regras de produto (aprovadas pelo Henrique):

* so a ultima acao da proposta, em pilha: o grupo de eventos de um mesmo ``request_id`` e uma
  "acao"; grupos ja desfeitos e grupos que sao um proprio ``ACTION_UNDONE`` nao entram na pilha;
* quem desfaz: o autor da acao ou um superusuario, sempre com a permissao da acao original;
* sem migration e sem permissao nova: o desfazer e um evento ``ACTION_UNDONE`` em ``proposal_events``
  que aponta para o ``request_id`` desfeito (``metadata.undone_request_id``);
* o Almox+ nao e avisado ao desfazer a liberacao (``almox_integration`` nao foi alterado: sair de
  LIBERADA para "sem estado" nunca gera webhook; a conciliacao horaria acerta).

Este modulo tem duas partes: regras puras (grupos, classificacao, avaliacao dos handlers, sem
banco) e a orquestracao assincrona usada pelo router.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.app.core import error_codes
from api.app.core.exceptions import ApiError, PermissionDeniedError
from api.app.modules.auth.dependencies import user_has_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import EXPEDITION_UPDATE, PRODUCTION_UPDATE, PROPOSALS_CHANGE_STATUS
from api.app.modules.proposals.domain import (
    CANCELLED_STATUS,
    INITIAL_AREA,
    INITIAL_STATUS,
    ProductionStateMachine,
)
from api.app.modules.proposals.models import (
    ExpeditionEvent,
    ExpeditionItem,
    FiscalEvent,
    GalvanizationLoadEvent,
    Proposal,
    ProposalEvent,
)
from api.app.modules.proposals.schemas import (
    ProposalDetail,
    ProposalUndoAction,
    ProposalUndoBlocker,
    ProposalUndoCandidateResponse,
    ProposalUndoChange,
    ProposalUndoRequest,
    ProposalUndoSideEffect,
)
from api.app.shared.formatting import format_quantity

ACTION_UNDONE = "ACTION_UNDONE"

# Campos de estado da proposta que as acoes v1 mexem; gravados em ``metadata.previous_state`` do evento
# original para que o inverso restaure o valor exato (e nao um valor deduzido).
STATE_FIELDS = (
    "current_area",
    "current_status",
    "general_status",
    "production_status",
    "galvanization_status",
    "shipping_status",
    "warehouse_status",
    "flow_situation",
    "has_production_pending",
    "is_completed",
)

FIELD_LABELS = {
    "current_area": "Area atual",
    "current_status": "Status atual",
    "general_status": "Status geral",
    "production_status": "Status da producao",
    "galvanization_status": "Status da galvanizacao",
    "shipping_status": "Status da expedicao",
    "warehouse_status": "Status do almoxarifado",
    "flow_situation": "Situacao do fluxo",
    "has_production_pending": "Pendencia de producao",
    "is_completed": "Proposta concluida",
}
ITEM_FIELD_LABELS = {
    "status": "Status do item na expedicao",
    "separated_quantity": "Quantidade separada",
    "separation_started_at": "Inicio da separacao",
    "separated_at": "Data da separacao",
}

NO_SNAPSHOT_REASON = (
    "Esta acao foi registrada antes do recurso de desfazer e nao guardou o estado anterior; "
    "nao e possivel desfaze-la com seguranca."
)


def proposal_state_snapshot(proposal: Any) -> dict[str, Any]:
    return {name: getattr(proposal, name, None) for name in STATE_FIELDS}


# ---------------------------------------------------------------- grupos de eventos


@dataclass(frozen=True)
class EventRef:
    source: str  # proposal | expedition | galvanization | fiscal
    id: int
    event_type: str
    request_id: str | None
    actor_user_id: int | None
    created_at: datetime
    from_area: str | None = None
    from_status: str | None = None
    to_area: str | None = None
    to_status: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    expedition_item_id: int | None = None


@dataclass
class ActionGroup:
    key: str
    request_id: str | None
    events: list[EventRef]
    undone: bool = False

    @property
    def types(self) -> set[str]:
        return {event.event_type for event in self.events}

    @property
    def is_undo(self) -> bool:
        return ACTION_UNDONE in self.types

    @property
    def sort_key(self) -> tuple[datetime, int]:
        return max((event.created_at, event.id) for event in self.events)

    def of(self, event_type: str, source: str | None = None) -> list[EventRef]:
        return [
            event for event in self.events
            if event.event_type == event_type and (source is None or event.source == source)
        ]

    def first(self, event_type: str, source: str | None = None) -> EventRef | None:
        found = self.of(event_type, source)
        return found[0] if found else None


def build_groups(events: list[EventRef]) -> list[ActionGroup]:
    """Agrupa por request_id (evento sem request_id vira um grupo proprio) e marca os ja desfeitos."""
    by_key: dict[str, list[EventRef]] = defaultdict(list)
    for event in events:
        by_key[event.request_id or f"{event.source}:{event.id}"].append(event)
    undone_ids = {
        str(event.metadata.get("undone_request_id"))
        for event in events
        if event.event_type == ACTION_UNDONE and event.metadata.get("undone_request_id")
    }
    return [
        ActionGroup(key=key, request_id=members[0].request_id, events=members, undone=bool(members[0].request_id) and key in undone_ids)
        for key, members in by_key.items()
    ]


def pick_latest(groups: list[ActionGroup]) -> ActionGroup | None:
    """Topo da pilha: o grupo mais recente que nao foi desfeito nem e, ele mesmo, um desfazer."""
    live = [group for group in groups if not group.undone and not group.is_undo]
    return max(live, key=lambda group: group.sort_key) if live else None


def undone_event_map(events: list[tuple[int, int | None, str | None, dict | None]]) -> dict[tuple[int, str], int]:
    """(proposal_id, request_id desfeito) -> id do ACTION_UNDONE. Entrada: (id, proposal_id, event_type, metadata)."""
    result: dict[tuple[int, str], int] = {}
    for event_id, proposal_id, event_type, metadata in events:
        if event_type != ACTION_UNDONE or proposal_id is None or not isinstance(metadata, dict):
            continue
        target = metadata.get("undone_request_id")
        if target:
            key = (int(proposal_id), str(target))
            result[key] = min(event_id, result.get(key, event_id))
    return result


# ---------------------------------------------------------------- avaliacao dos handlers


@dataclass
class ItemRestore:
    item: Any
    item_number: str
    values: dict[str, Any]


@dataclass
class Evaluation:
    unsupported: str | None = None
    blockers: list[tuple[str, str]] = field(default_factory=list)
    side_effects: list[tuple[str, str]] = field(default_factory=list)
    proposal_restore: dict[str, Any] = field(default_factory=dict)
    item_restores: list[ItemRestore] = field(default_factory=list)


@dataclass
class UndoContext:
    proposal: Any
    group: ActionGroup
    exp_items: dict[int, Any]


@dataclass(frozen=True)
class UndoHandler:
    name: str
    label: str
    required: frozenset[str]
    allowed: frozenset[str]
    permission: str
    undo_class: str  # A: so estado da proposta; B: tambem linhas/itens; C: com efeito externo
    evaluate: Callable[[UndoContext], Evaluation]


def _is_cancelled(proposal: Any) -> bool:
    return bool(getattr(proposal, "is_cancelled", False)) or getattr(proposal, "current_status", None) == CANCELLED_STATUS


def _base(ctx: UndoContext) -> Evaluation:
    ev = Evaluation()
    if _is_cancelled(ctx.proposal):
        ev.blockers.append(("PROPOSAL_CANCELLED", "A proposta foi cancelada; nao e possivel desfazer acoes nela."))
    return ev


def _restore_keys(snapshot: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: snapshot.get(key) for key in keys}


def _parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value if value not in (None, "") else "0")).quantize(Decimal("0.0001"))


def _eval_release(ctx: UndoContext) -> Evaluation:
    ev = _base(ctx)
    event = ctx.group.first("PROPOSAL_STATUS_CHANGED")
    snapshot = event.metadata.get("previous_state") if event else None
    if event is None or (event.from_area, event.from_status) != (INITIAL_AREA, INITIAL_STATUS):
        ev.unsupported = "Esta mudanca de status nao e uma liberacao desfazivel."
        return ev
    if not isinstance(snapshot, dict):
        ev.unsupported = NO_SNAPSHOT_REASON
        return ev
    proposal = ctx.proposal
    if (proposal.current_area, proposal.current_status) != (event.to_area, event.to_status):
        ev.blockers.append(("STATE_CHANGED", f"A proposta mudou depois da liberacao (agora: {proposal.current_area} / {proposal.current_status})."))
    if ProductionStateMachine.normalize(proposal.production_status) != ProductionStateMachine.WAITING:
        ev.blockers.append(("PRODUCTION_ALREADY_STARTED", "A producao desta proposta ja foi iniciada."))
    ev.proposal_restore = _restore_keys(snapshot, STATE_FIELDS)
    ev.side_effects.append(("ALMOX_NOT_NOTIFIED", "O Almox+ nao e avisado; a conciliacao horaria acerta."))
    return ev


def _eval_warehouse(ctx: UndoContext) -> Evaluation:
    ev = _base(ctx)
    event = ctx.group.first("WAREHOUSE_STATUS_CHANGED")
    if event is None or not event.from_status:
        ev.unsupported = "O registro desta acao nao guardou o status anterior do Almoxarifado."
        return ev
    current = ctx.proposal.warehouse_status or "AGUARDANDO_CONFIRMACAO"
    if current != event.to_status:
        ev.blockers.append(("STATE_CHANGED", f"O status do Almoxarifado mudou depois desta acao (agora: {current})."))
    # previous_warehouse_status guarda o valor exato (None = "nao definido", diferente de AGUARDANDO_CONFIRMACAO);
    # eventos antigos so tem from_status.
    previous = event.metadata["previous_warehouse_status"] if "previous_warehouse_status" in event.metadata else event.from_status
    ev.proposal_restore = {"warehouse_status": previous}
    return ev


_PRODUCTION_RESTORE_FIELDS = ("production_status", "current_status", "general_status")
# event_type -> (status normalizado que a proposta deve ter agora, exige snapshot)
_PRODUCTION_RULES = {
    "PRODUCTION_STARTED": (ProductionStateMachine.STARTED, True),
    "PRODUCTION_PAUSED": (ProductionStateMachine.PAUSED, False),
    "PRODUCTION_RESUMED": (ProductionStateMachine.STARTED, False),
}


def _eval_production(ctx: UndoContext, event_type: str) -> Evaluation:
    ev = _base(ctx)
    event = ctx.group.first(event_type)
    expected_now, needs_snapshot = _PRODUCTION_RULES[event_type]
    snapshot = event.metadata.get("previous_state") if event else None
    if event is None:
        ev.unsupported = "Evento da acao nao encontrado."
        return ev
    if isinstance(snapshot, dict):
        ev.proposal_restore = _restore_keys(snapshot, _PRODUCTION_RESTORE_FIELDS)
    elif needs_snapshot or not event.from_status:
        ev.unsupported = NO_SNAPSHOT_REASON
        return ev
    else:
        # pausar/retomar guardam o status anterior em from_status e a area em metadata.current_area.
        ev.proposal_restore = {"production_status": event.from_status}
        if event.metadata.get("current_area") == "PRODUCAO":
            ev.proposal_restore["current_status"] = event.from_status
    current = ProductionStateMachine.normalize(ctx.proposal.production_status or ctx.proposal.current_status)
    if current != expected_now:
        ev.blockers.append(("STATE_CHANGED", f"A producao mudou depois desta acao (status atual: {current})."))
    return ev


_SEPARATION_START_RESTORE = ("current_area", "current_status", "general_status", "shipping_status")


def _eval_start_separation(ctx: UndoContext) -> Evaluation:
    ev = _base(ctx)
    proposal_event = ctx.group.first("EXPEDITION_SEPARATION_STARTED", "proposal")
    snapshot = proposal_event.metadata.get("previous_state") if proposal_event else None
    item_events = ctx.group.of("EXPEDITION_SEPARATION_STARTED", "expedition")
    if proposal_event is None or not isinstance(snapshot, dict) or any("previous_separation_started_at" not in e.metadata for e in item_events):
        ev.unsupported = NO_SNAPSHOT_REASON
        return ev
    proposal = ctx.proposal
    if proposal.current_status != proposal_event.to_status or proposal.shipping_status != proposal_event.to_status:
        ev.blockers.append(("STATE_CHANGED", f"A expedicao mudou depois do inicio da separacao (status atual: {proposal.current_status})."))
    ev.proposal_restore = _restore_keys(snapshot, _SEPARATION_START_RESTORE)
    for event in item_events:
        item = ctx.exp_items.get(event.expedition_item_id or 0)
        if item is None or item.status != event.to_status:
            ev.blockers.append(("ITEM_CHANGED", "Um item da expedicao mudou depois do inicio da separacao."))
            continue
        ev.item_restores.append(ItemRestore(
            item=item,
            item_number=item.proposal_item.item_number,
            values={"status": event.from_status, "separation_started_at": _parse_dt(event.metadata.get("previous_separation_started_at"))},
        ))
    return ev


_SEPARATE_ITEMS_RESTORE = ("current_area", "current_status", "general_status", "shipping_status", "is_completed", "flow_situation")


def _eval_separate_items(ctx: UndoContext) -> Evaluation:
    ev = _base(ctx)
    proposal_event = ctx.group.first("EXPEDITION_SEPARATION_RECALCULATED", "proposal")
    snapshot = proposal_event.metadata.get("previous_state") if proposal_event else None
    item_events = ctx.group.of("EXPEDITION_ITEM_SEPARATED", "expedition")
    needed = ("quantity", "previous_separated_quantity", "previous_separated_at")
    if proposal_event is None or not isinstance(snapshot, dict) or any(key not in e.metadata for e in item_events for key in needed):
        ev.unsupported = NO_SNAPSHOT_REASON
        return ev
    proposal = ctx.proposal
    if proposal.current_status != proposal_event.to_status:
        ev.blockers.append(("STATE_CHANGED", f"A expedicao mudou depois da separacao (status atual: {proposal.current_status})."))
    ev.proposal_restore = _restore_keys(snapshot, _SEPARATE_ITEMS_RESTORE)
    for event in item_events:
        item = ctx.exp_items.get(event.expedition_item_id or 0)
        previous = _decimal(event.metadata["previous_separated_quantity"])
        if (
            item is None
            or item.status != event.to_status
            or _decimal(item.separated_quantity) != (previous + _decimal(event.metadata["quantity"])).quantize(Decimal("0.0001"))
        ):
            ev.blockers.append(("ITEM_CHANGED", "Um item da expedicao mudou depois da separacao."))
            continue
        ev.item_restores.append(ItemRestore(
            item=item,
            item_number=item.proposal_item.item_number,
            values={
                "status": event.from_status,
                "separated_quantity": previous,
                "separated_at": _parse_dt(event.metadata["previous_separated_at"]),
            },
        ))
    return ev


def _handler(name, label, required, allowed, permission, undo_class, evaluate) -> UndoHandler:
    return UndoHandler(name, label, frozenset(required), frozenset(allowed), permission, undo_class, evaluate)


HANDLERS: tuple[UndoHandler, ...] = (
    _handler("RELEASE_PROPOSAL", "Liberacao da proposta", {"PROPOSAL_STATUS_CHANGED"}, {"PROPOSAL_STATUS_CHANGED"}, PROPOSALS_CHANGE_STATUS, "C", _eval_release),
    _handler("WAREHOUSE_STATUS", "Status do Almoxarifado", {"WAREHOUSE_STATUS_CHANGED"}, {"WAREHOUSE_STATUS_CHANGED"}, PROPOSALS_CHANGE_STATUS, "A", _eval_warehouse),
    _handler("START_PRODUCTION", "Inicio da producao", {"PRODUCTION_STARTED"}, {"PRODUCTION_STARTED"}, PRODUCTION_UPDATE, "A", lambda ctx: _eval_production(ctx, "PRODUCTION_STARTED")),
    _handler("PAUSE_PRODUCTION", "Pausa da producao", {"PRODUCTION_PAUSED"}, {"PRODUCTION_PAUSED"}, PRODUCTION_UPDATE, "A", lambda ctx: _eval_production(ctx, "PRODUCTION_PAUSED")),
    _handler("RESUME_PRODUCTION", "Retomada da producao", {"PRODUCTION_RESUMED"}, {"PRODUCTION_RESUMED"}, PRODUCTION_UPDATE, "A", lambda ctx: _eval_production(ctx, "PRODUCTION_RESUMED")),
    _handler("START_SEPARATION", "Inicio da separacao", {"EXPEDITION_SEPARATION_STARTED"}, {"EXPEDITION_SEPARATION_STARTED"}, EXPEDITION_UPDATE, "B", _eval_start_separation),
    _handler(
        "SEPARATE_ITEMS", "Separacao de itens", {"EXPEDITION_SEPARATION_RECALCULATED"},
        {"EXPEDITION_SEPARATION_RECALCULATED", "EXPEDITION_ITEM_SEPARATED"}, EXPEDITION_UPDATE, "B", _eval_separate_items,
    ),
)


def classify(group: ActionGroup) -> UndoHandler | None:
    types = group.types
    for handler in HANDLERS:
        if handler.required <= types and types <= handler.allowed:
            return handler
    return None


# (tipos de evento, rotulo da acao, motivo + alternativa). A primeira linha que casa vence.
_NOT_UNDOABLE: tuple[tuple[frozenset[str], str, str], ...] = (
    (frozenset({"PROPOSAL_CANCELLED", "PROPOSAL_CANCELLED_TERMINAL"}), "Cancelamento da proposta",
     "O cancelamento e definitivo: a proposta cancelada nao pode ser reativada. Para seguir com o trabalho, crie uma nova proposta."),
    (frozenset({
        "COMPENSATED_REMANAGEMENT_APPLIED", "COMPENSATED_REMANAGEMENT_RECEIVED", "COMPENSATED_REMANAGEMENT_READY_SENT",
        "COMPENSATED_REMANAGEMENT_READY_RECEIVED", "GALVANIZATION_ITEM_OWNER_CHANGED", "EXPEDITION_ITEM_REMANAGED",
        "EXPEDITION_REMANAGEMENT_TO_PRODUCTION", "EXPEDITION_ITEM_REMANAGED_TO_EARLY_DELIVERY",
        "EXPEDITION_EARLY_DELIVERY_BY_REMANAGEMENT", "EXPEDITION_RETURN_TO_PRODUCTION", "EXPEDITION_ITEM_RETURNED_TO_PRODUCTION",
    }), "Remanejamento",
     "Remanejamento nao pode ser desfeito por aqui. Use o assistente de remanejamento para ajustar as pecas."),
    (frozenset({
        "PRODUCTION_ITEM_COMPLETED", "PRODUCTION_COMPLETED", "PRODUCTION_PARTIALLY_COMPLETED", "REALLOCATED_PRODUCTION_COMPLETED",
        "PROPOSAL_PARTIAL_CHILD_CREATED", "PROPOSAL_PARTIAL_CHILD_MERGED", "PROPOSAL_PARTIAL_CHILD_GROUPED",
        "PARENT_PROPOSAL_REBORN", "PARENT_PROPOSAL_OPERATIONAL_DEATH",
    }), "Conclusao de itens de producao",
     "A conclusao de itens de producao nao pode ser desfeita por aqui (ela gera pecas, parciais e a proxima etapa). Peca a correcao administrativa a um superusuario."),
    (frozenset({
        "GALVANIZATION_LOAD_CREATED", "GALVANIZATION_LOAD_UPDATED", "GALVANIZATION_LOAD_RELEASED", "GALVANIZATION_ITEM_SENT",
        "GALVANIZATION_ITEM_RETURNED", "GALVANIZATION_RETURN_REGISTERED", "GALVANIZATION_LOAD_CLOSED",
        "GALVANIZATION_PROPOSAL_RETURN_RECALCULATED", "GALVANIZATION_RETURN_RECORDED_AFTER_CANCELLATION",
    }), "Carga ou retorno de galvanizacao",
     "Cargas e retornos de galvanizacao nao podem ser desfeitos por aqui. Ajuste pela tela de Galvanizacao."),
    (frozenset({"EXPEDITION_ITEM_DELIVERED", "EXPEDITION_DELIVERY_RECALCULATED"}), "Entrega",
     "A entrega nao pode ser desfeita por aqui. Se foi registrada por engano, peca a correcao administrativa a um superusuario."),
    (frozenset({
        "FISCAL_INVOICE_REGISTERED", "FISCAL_BATCH_CONFIRMED", "FISCAL_INVOICE_ITEM_CANCELLED", "FISCAL_INVOICE_CANCELLED",
        "FISCAL_INVOICE_CORRECTED", "FISCAL_INVOICE_WITHDRAWN",
    }), "Nota fiscal",
     "Acoes fiscais nao podem ser desfeitas por aqui. Cancele ou corrija a nota fiscal na aba Fiscal."),
    (frozenset({"PROPOSAL_UPDATED", "PROPOSAL_ITEM_UPDATED", "PROPOSAL_ITEM_CREATED", "PROPOSAL_ITEM_DELETED"}), "Atualizacao da proposta",
     "Edicoes da proposta e dos itens nao podem ser desfeitas por aqui. Edite os dados novamente."),
    (frozenset({
        "PRODUCTION_ITEM_FLOW_UPDATED", "PRODUCTION_ITEM_FLOW_BATCH_UPDATED", "PRODUCTION_ITEM_WEIGHT_UPDATED", "PRODUCTION_WEIGHTS_UPDATED",
    }), "Fluxo ou peso de itens",
     "O fluxo e o peso dos itens nao podem ser desfeitos por aqui. Defina os valores novamente na Producao."),
    (frozenset({"PROPOSAL_ADMINISTRATIVE_CORRECTION"}), "Correcao administrativa",
     "Uma correcao administrativa nao pode ser desfeita por aqui. Faca uma nova correcao administrativa."),
    (frozenset({"PROPOSAL_REACTIVATED", "PROPOSAL_DEACTIVATED"}), "Ativacao da proposta",
     "Use as acoes Ativar e Desativar proposta."),
    (frozenset({"PROPOSAL_CREATED"}), "Criacao da proposta",
     "A criacao da proposta nao pode ser desfeita. Se foi engano, desative a proposta."),
)
_GENERIC_LABEL = "Acao"
_GENERIC_REASON = "Esta acao nao pode ser desfeita por aqui."
_NO_REQUEST_REASON = "Este registro e antigo (sem identificador da requisicao) e nao pode ser desfeito."
_COMPOSITE_REASON = "Esta acao tambem alterou outras partes da proposta e nao pode ser desfeita automaticamente."


def describe_unsupported(group: ActionGroup) -> tuple[str, str]:
    """(rotulo, motivo+alternativa) de uma acao que nao tem inverso na v1."""
    types = group.types
    for handler in HANDLERS:
        if handler.required & types:  # reconhece a acao, mas ha eventos extras que o inverso nao cobre
            return handler.label, _COMPOSITE_REASON
    for row_types, label, reason in _NOT_UNDOABLE:
        if types & row_types:
            return label, reason
    if group.request_id is None:
        return _GENERIC_LABEL, _NO_REQUEST_REASON
    return _GENERIC_LABEL, _GENERIC_REASON


# ---------------------------------------------------------------- formatacao e aplicacao


def _fmt(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "Sim" if value else "Nao"
    if isinstance(value, Decimal):
        return format_quantity(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def build_changes(proposal: Any, ev: Evaluation) -> list[ProposalUndoChange]:
    changes: list[ProposalUndoChange] = []
    for name, restored in ev.proposal_restore.items():
        current = getattr(proposal, name, None)
        if _fmt(current) != _fmt(restored):
            # warehouse_status nulo e exibido como NAO_DEFINIDO, o mesmo rotulo que o resto do sistema usa.
            show = (lambda v: _fmt(v) or "NAO_DEFINIDO") if name == "warehouse_status" else _fmt
            changes.append(ProposalUndoChange(field=name, label=FIELD_LABELS.get(name, name), current_value=show(current), restored_value=show(restored)))
    for row in ev.item_restores:
        for name, restored in row.values.items():
            current = getattr(row.item, name, None)
            if _fmt(current) != _fmt(restored):
                changes.append(ProposalUndoChange(
                    field=f"items[{row.item_number}].{name}",
                    label=f"Item {row.item_number} - {ITEM_FIELD_LABELS.get(name, name)}",
                    current_value=_fmt(current),
                    restored_value=_fmt(restored),
                ))
    return changes


def _bump(row: Any, actor_id: int) -> None:
    row.version += 1
    row.updated_by = actor_id
    row.updated_at = datetime.now(UTC)


def apply_evaluation(proposal: Any, ev: Evaluation, actor_id: int) -> dict[str, Any]:
    """Aplica o inverso nos objetos ORM (sincrono) e devolve {before, after} para a auditoria."""
    before = {
        "proposal": {name: _json(getattr(proposal, name, None)) for name in ev.proposal_restore},
        "items": {row.item_number: {name: _json(getattr(row.item, name, None)) for name in row.values} for row in ev.item_restores},
    }
    for name, value in ev.proposal_restore.items():
        setattr(proposal, name, value)
    for row in ev.item_restores:
        for name, value in row.values.items():
            setattr(row.item, name, value)
        _bump(row.item, actor_id)
    _bump(proposal, actor_id)
    after = {
        "proposal": {name: _json(getattr(proposal, name, None)) for name in ev.proposal_restore},
        "items": {row.item_number: {name: _json(getattr(row.item, name, None)) for name in row.values} for row in ev.item_restores},
    }
    return {"before": before, "after": after}


def permission_problem(actor: Any, handler: UndoHandler, group: ActionGroup) -> str | None:
    if not user_has_permission(actor, handler.permission):
        return "Voce nao tem a permissao necessaria para desfazer esta acao."
    author = next((event.actor_user_id for event in group.events if event.actor_user_id is not None), None)
    if not actor.is_superuser and author != actor.id:
        return "Somente quem fez a acao ou um superusuario pode desfaze-la."
    return None


# ---------------------------------------------------------------- orquestracao (banco)


async def _load_proposal(session: AsyncSession, proposal_id: int, *, for_update: bool) -> Proposal:
    stmt = (
        select(Proposal)
        .options(selectinload(Proposal.items), selectinload(Proposal.expedition_items).selectinload(ExpeditionItem.proposal_item))
        .where(Proposal.id == proposal_id)
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    proposal = (await session.execute(stmt)).scalars().unique().first()
    if proposal is None:
        raise ApiError(error_codes.PROPOSAL_NOT_FOUND, "Proposta nao encontrada.", status_code=404)
    return proposal


async def load_events(session: AsyncSession, proposal_id: int) -> list[EventRef]:
    refs: list[EventRef] = []
    for row in (await session.execute(select(ProposalEvent).where(ProposalEvent.proposal_id == proposal_id))).scalars():
        refs.append(EventRef(
            "proposal", int(row.id), row.event_type, row.request_id, row.actor_user_id, row.created_at,
            row.from_area, row.from_status, row.to_area, row.to_status, dict(row.metadata_ or {}),
        ))
    for row in (await session.execute(select(ExpeditionEvent).where(ExpeditionEvent.proposal_id == proposal_id))).scalars():
        refs.append(EventRef(
            "expedition", int(row.id), row.event_type, row.request_id, row.actor_user_id, row.created_at,
            None, row.from_status, None, row.to_status, dict(row.metadata_ or {}), row.expedition_item_id,
        ))
    for source, model in (("galvanization", GalvanizationLoadEvent), ("fiscal", FiscalEvent)):
        for row in (await session.execute(select(model).where(model.proposal_id == proposal_id))).scalars():
            refs.append(EventRef(
                source, int(row.id), row.event_type, row.request_id, row.actor_user_id, row.created_at,
                None, row.from_status, None, row.to_status, dict(row.metadata_ or {}),
            ))
    return refs


def _primary_event(group: ActionGroup, handler: UndoHandler | None) -> EventRef:
    if handler is not None:
        for event_type in sorted(handler.required):
            found = group.first(event_type, "proposal") or group.first(event_type)
            if found is not None:
                return found
    proposal_events = [event for event in group.events if event.source == "proposal"]
    return min(proposal_events or group.events, key=lambda event: event.id)


def _analyze(proposal: Any, group: ActionGroup, handler: UndoHandler | None) -> Evaluation | None:
    if handler is None:
        return None
    exp_items = {int(item.id): item for item in getattr(proposal, "expedition_items", [])}
    return handler.evaluate(UndoContext(proposal=proposal, group=group, exp_items=exp_items))


async def get_candidate(session: AsyncSession, proposal_id: int, actor: User) -> ProposalUndoCandidateResponse:
    from api.app.modules.proposals import service

    proposal = await _load_proposal(session, proposal_id, for_update=False)
    group = pick_latest(build_groups(await load_events(session, proposal_id)))
    response = ProposalUndoCandidateResponse(proposal_id=proposal.id, proposal_version=proposal.version)
    if group is None:
        response.cannot_undo_reason = "Nao ha nenhuma acao para desfazer nesta proposta."
        return response

    handler = classify(group)
    ev = _analyze(proposal, group, handler)
    primary = _primary_event(group, handler)
    author = (await session.execute(select(User).where(User.id == primary.actor_user_id))).scalar_one_or_none() if primary.actor_user_id else None
    actor_name = author.display_name if author else None

    reason: str | None = None
    if handler is None:
        label, reason = describe_unsupported(group)
    else:
        label = handler.label
        response.handler = handler.name
        response.undo_class = handler.undo_class  # type: ignore[assignment]
        if group.request_id is None:
            reason = _NO_REQUEST_REASON
        elif ev is not None and ev.unsupported:
            reason = ev.unsupported
        else:
            response.undoable = True

    response.action = ProposalUndoAction(
        request_id=group.request_id,
        event_type=primary.event_type,
        label=label,
        title=service._activity_headline(primary.event_type, actor_name, primary.metadata, primary.from_status, primary.to_status),
        actor_user_id=primary.actor_user_id,
        actor_name=actor_name,
        created_at=group.sort_key[0],
        event_count=len(group.events),
    )
    if response.undoable and ev is not None and handler is not None:
        response.blockers = [ProposalUndoBlocker(code=code, message=message) for code, message in ev.blockers]
        response.changes = build_changes(proposal, ev)
        response.side_effects = [ProposalUndoSideEffect(code=code, message=message) for code, message in ev.side_effects]
        reason = permission_problem(actor, handler, group) or (ev.blockers[0][1] if ev.blockers else None)
    response.can_undo = response.undoable and reason is None
    response.cannot_undo_reason = reason
    return response


async def undo_action(
    session: AsyncSession,
    proposal_id: int,
    payload: ProposalUndoRequest,
    actor: User,
    *,
    request_id: str | None,
) -> ProposalDetail:
    from api.app.modules.proposals import service

    try:
        proposal = await _load_proposal(session, proposal_id, for_update=True)
        events = await load_events(session, proposal_id)

        # 1. idempotencia: a mesma chave com o mesmo alvo e motivo devolve o estado atual.
        for event in events:
            metadata = event.metadata
            if event.event_type == ACTION_UNDONE and metadata.get("idempotency_key") == payload.idempotency_key:
                if metadata.get("undone_request_id") != payload.target_request_id or metadata.get("reason") != payload.reason:
                    raise ApiError(
                        error_codes.UNDO_IDEMPOTENCY_CONFLICT,
                        "A chave de idempotencia ja foi usada por outro desfazer nesta proposta.",
                        status_code=409,
                    )
                await session.rollback()
                return service.proposal_detail(await service.get_proposal(session, proposal_id))

        groups = build_groups(events)
        target = next((group for group in groups if group.request_id == payload.target_request_id), None)
        if target is None:
            raise ApiError(error_codes.UNDO_ACTION_NOT_FOUND, "Acao nao encontrada nesta proposta.", status_code=404)
        if target.undone:
            raise ApiError(error_codes.UNDO_ALREADY_UNDONE, "Esta acao ja foi desfeita.", status_code=409)
        if target.is_undo:
            raise ApiError(error_codes.UNDO_NOT_SUPPORTED, "Um desfazer nao pode ser desfeito.", status_code=409)
        latest = pick_latest(groups)
        if latest is not target:
            raise ApiError(
                error_codes.UNDO_NOT_LATEST,
                "Existe uma acao mais recente nesta proposta; desfaca primeiro a ultima.",
                status_code=409,
                details={"latest_request_id": latest.request_id if latest else None},
            )
        service._ensure_version(proposal.version, payload.expected_version)

        handler = classify(target)
        if handler is None:
            raise ApiError(error_codes.UNDO_NOT_SUPPORTED, describe_unsupported(target)[1], status_code=409)
        problem = permission_problem(actor, handler, target)
        if problem:
            raise PermissionDeniedError(problem)
        ev = _analyze(proposal, target, handler)
        assert ev is not None
        if ev.unsupported:
            raise ApiError(error_codes.UNDO_NOT_SUPPORTED, ev.unsupported, status_code=409)
        if ev.blockers:
            raise ApiError(
                error_codes.UNDO_BLOCKED,
                ev.blockers[0][1],
                status_code=409,
                details={"blockers": [{"code": code, "message": message} for code, message in ev.blockers]},
            )

        from_area, from_status = proposal.current_area, proposal.current_status
        snapshots = apply_evaluation(proposal, ev, actor.id)
        await service._record_event(
            session,
            proposal,
            ACTION_UNDONE,
            actor,
            request_id=request_id,
            from_area=from_area,
            from_status=from_status,
            to_area=proposal.current_area,
            to_status=proposal.current_status,
            metadata={
                "undone_request_id": target.request_id,
                "undone_events": [{"source": e.source, "id": e.id, "event_type": e.event_type} for e in target.events],
                "undone_label": handler.label,
                "handler": handler.name,
                "reason": payload.reason,
                "idempotency_key": payload.idempotency_key,
                "expected_version": payload.expected_version,
                "resulting_version": proposal.version,
                "before_snapshot": snapshots["before"],
                "after_snapshot": snapshots["after"],
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return service.proposal_detail(await service.get_proposal(session, proposal_id))
