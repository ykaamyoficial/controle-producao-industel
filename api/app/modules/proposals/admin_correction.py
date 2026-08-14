from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from api.app.modules.proposals.models import Proposal
from api.app.modules.proposals.remanagement import calculate_item_balance, quantity


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
    "is_cancelled",
)

PROTECTED_OPERATIONAL_FIELDS = (
    "quantidades dos itens",
    "quantidades produzidas",
    "cargas e quantidades enviadas",
    "retornos de galvanizacao",
    "separacoes e entregas",
    "transferencias de remanejamento",
    "notas e quantidades fiscais",
    "historico operacional existente",
)

VALID_TARGETS = {
    "CONTROLE_GERAL": {"AGUARDANDO_LIBERACAO"},
    "PRODUCAO": {
        "NAO_INICIADO",
        "ITEM_PENDENTE_FABRICACAO",
        "INICIADO",
        "PARADO",
        "FINALIZADO_PARCIAL",
        "FINALIZADO",
    },
    "GALVANIZACAO": {
        "AGUARDANDO_ENVIO",
        "EM_CARGA",
        "ENVIADO_GALVANIZACAO",
        "RETORNOU_PARCIAL",
        "RETORNOU_GALVANIZACAO",
    },
    "EXPEDICAO": {
        "EM_SEPARACAO",
        "AGUARDANDO_SEPARACAO_PARCIAL",
        "SEPARACAO_INICIADA",
        "SEPARADO",
        "ENTREGUE_PARCIAL",
        "ENTREGUE",
    },
}


def _decimal(value: Any) -> Decimal:
    return quantity(value or 0)


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value.quantize(Decimal("0.0001")))
    return value


def _state_value(value: Any) -> Any:
    return value.strip().upper() if isinstance(value, str) else value


def normalize_area(value: str | None) -> str:
    return str(value or "").strip().upper().replace(" ", "_")


def normalize_status(value: str | None) -> str:
    return str(value or "").strip().upper().replace(" ", "_")


def _administrative_members(proposal: Proposal) -> list[Proposal]:
    """Retorna os registros que compõem a visão administrativa da proposta.

    A mãe representa o conjunto operacional somente quando ela própria é
    solicitada. Uma filha continua sendo uma unidade independente para ações e
    correções, portanto nunca incorpora a mãe nem as irmãs nesta visão.
    """
    if proposal.parent_proposal_id is not None:
        return [proposal]
    children = proposal.__dict__.get("partial_children")
    if not children:
        return [proposal]
    return [proposal, *[child for child in children if child.active and not child.is_cancelled]]


@dataclass(frozen=True)
class AdministrativeFacts:
    active_items: int
    undefined_flow_items: int
    internal_items: int
    production_pending_items: int
    production_produced_items: int
    production_pending_quantity: Decimal
    production_complete: bool
    production_partial: bool
    production_released: bool
    latest_production_event: str | None
    production_reallocated_pending: Decimal
    production_reallocated_completed: Decimal
    remanagement_transfer_count: int
    galvanization_required_items: int
    galvanization_load_item_count: int
    galvanization_sent_quantity: Decimal
    galvanization_returned_quantity: Decimal
    galvanization_all_returned: bool
    galvanization_load_waiting: bool
    galvanization_load_released: bool
    expedition_item_count: int
    expedition_available_quantity: Decimal
    expedition_separated_quantity: Decimal
    expedition_delivered_quantity: Decimal
    expedition_remanaged_quantity: Decimal
    expedition_pending_quantity: Decimal
    expedition_status: str | None
    expedition_started: bool
    delivery_complete: bool
    fiscal_invoice_count: int
    fiscal_billed_quantity: Decimal

    @property
    def has_remanagement(self) -> bool:
        return bool(
            self.remanagement_transfer_count
            or self.production_reallocated_pending > 0
            or self.production_reallocated_completed > 0
            or self.expedition_remanaged_quantity > 0
        )

    @property
    def has_load_history(self) -> bool:
        return self.galvanization_load_item_count > 0

    @property
    def has_delivery(self) -> bool:
        return self.expedition_delivered_quantity > 0

    @property
    def has_fiscal_emission(self) -> bool:
        return self.fiscal_invoice_count > 0 or self.fiscal_billed_quantity > 0

    def summary(self) -> dict[str, Any]:
        return {key: _json_value(value) for key, value in self.__dict__.items()}


@dataclass(frozen=True)
class CorrectionCandidate:
    target_area: str
    target_status: str
    label: str
    description: str
    updates: dict[str, Any]


def snapshot(proposal: Proposal, facts: AdministrativeFacts | None = None) -> dict[str, Any]:
    facts = facts or collect_facts(proposal)
    fiscal = proposal.fiscal_record if proposal.fiscal_record and proposal.fiscal_record.active else None
    result = {field: _json_value(getattr(proposal, field)) for field in STATE_FIELDS}
    result.update(
        {
            "fiscal_status": fiscal.status_fiscal if fiscal else None,
            "fiscal_situation": fiscal.fiscal_situation if fiscal else None,
            "version": proposal.version,
            "facts": facts.summary(),
        }
    )
    return result


def collect_facts(proposal: Proposal) -> AdministrativeFacts:
    members = _administrative_members(proposal)
    items = [item for member in members for item in member.items if item.active]
    internal = [item for item in items if item.produce_internally != "NAO"]
    undefined = [
        item
        for item in items
        if item.produce_internally == "INDEFINIDO"
        or item.requires_galvanization == "INDEFINIDO"
        or not item.flow_defined
    ]

    balances = []
    transfer_ids: set[int] = set()
    reallocated_pending = Decimal("0")
    reallocated_completed = Decimal("0")
    for item in internal:
        sent = sum((_decimal(row.quantity) for row in item.production_allocations_sent), Decimal("0"))
        received_pending = sum(
            (
                _decimal(row.quantity - row.completed_quantity)
                for row in item.production_allocations_received
                if row.status != "COMPLETED"
            ),
            Decimal("0"),
        )
        received_completed = sum(
            (_decimal(row.completed_quantity) for row in item.production_allocations_received),
            Decimal("0"),
        )
        transfer_ids.update(int(row.id) for row in item.production_allocations_sent if row.id is not None)
        transfer_ids.update(int(row.id) for row in item.production_allocations_received if row.id is not None)
        expedition = item.expedition_item
        balance = calculate_item_balance(
            requested=item.quantity,
            produced=item.produced,
            produce_internally=item.produce_internally,
            expedition_available=expedition.available_quantity if expedition else 0,
            delivered=expedition.delivered_quantity if expedition else 0,
            remanaged_out=expedition.remanaged_quantity if expedition else 0,
            production_reallocated_out=sent,
            production_reallocated_in_pending=received_pending,
            production_reallocated_in_completed=received_completed,
        )
        balances.append((item, balance))
        reallocated_pending += balance.production_reallocated_in_pending
        reallocated_completed += balance.production_reallocated_in_completed

    production_pending = [(item, balance) for item, balance in balances if balance.production_pending > 0]
    produced_items = [item for item, balance in balances if balance.production_pending <= 0 or item.produced]
    production_complete = bool(items) and not undefined and not production_pending
    production_partial = bool(produced_items or reallocated_completed > 0) and bool(production_pending)

    production_event_types = {
        "PRODUCTION_STARTED",
        "PRODUCTION_PAUSED",
        "PRODUCTION_RESUMED",
        "PRODUCTION_PARTIALLY_COMPLETED",
        "PRODUCTION_COMPLETED",
    }
    production_events = [
        event
        for member in members
        for event in member.events
        if event.event_type in production_event_types
    ]
    production_events.sort(key=lambda event: (event.created_at, event.id or 0))
    latest_production_event = production_events[-1].event_type if production_events else None
    production_released = any(
        event.event_type == "PROPOSAL_STATUS_CHANGED" and normalize_area(event.to_area) == "PRODUCAO"
        for event in proposal.events
    ) or bool(production_events)

    required_galv = [item for item in items if item.requires_galvanization == "SIM"]
    active_load_items = []
    returned_by_item: dict[int, Decimal] = {}
    waiting_load = False
    released_load = False
    galvanization_load_items = [
        load_item
        for member in members
        for load_item in member.galvanization_load_items
    ]
    for load_item in galvanization_load_items:
        load = load_item.load
        if not load_item.active or load is None or not load.active or normalize_status(load.status) == "CANCELADA":
            continue
        active_load_items.append(load_item)
        returned_by_item[int(load_item.proposal_item_id)] = returned_by_item.get(
            int(load_item.proposal_item_id), Decimal("0")
        ) + _decimal(load_item.returned_quantity)
        if normalize_status(load.status) == "AGUARDANDO_LIBERACAO":
            waiting_load = True
        else:
            released_load = True
    galv_all_returned = bool(required_galv) and all(
        returned_by_item.get(int(item.id), Decimal("0")) >= _decimal(item.quantity)
        for item in required_galv
    )

    expedition_items = [
        item
        for member in members
        for item in member.expedition_items
        if item.active
    ]
    relevant_expedition = [item for item in expedition_items if _decimal(item.available_quantity) > 0]
    exp_available = sum((_decimal(item.available_quantity) for item in relevant_expedition), Decimal("0"))
    exp_separated = sum((_decimal(item.separated_quantity) for item in relevant_expedition), Decimal("0"))
    exp_delivered = sum((_decimal(item.delivered_quantity) for item in relevant_expedition), Decimal("0"))
    exp_remanaged = sum((_decimal(item.remanaged_quantity) for item in relevant_expedition), Decimal("0"))
    exp_pending = sum(
        (
            max(
                Decimal("0"),
                _decimal(item.available_quantity)
                - _decimal(item.delivered_quantity)
                - _decimal(item.remanaged_quantity),
            )
            for item in relevant_expedition
        ),
        Decimal("0"),
    )
    remaining = [
        item
        for item in relevant_expedition
        if _decimal(item.delivered_quantity) + _decimal(item.remanaged_quantity)
        < _decimal(item.available_quantity)
    ]
    separated_open = [
        item for item in remaining if _decimal(item.separated_quantity) > _decimal(item.delivered_quantity)
    ]
    any_delivered = any(_decimal(item.delivered_quantity) > 0 for item in relevant_expedition)
    any_separated = any(_decimal(item.separated_quantity) > 0 for item in relevant_expedition)
    expedition_started = any(
        item.separation_started_at is not None
        or normalize_status(item.status) in {"SEPARACAO_INICIADA", "SEPARADO", "ENTREGUE_PARCIAL", "ENTREGUE"}
        for item in relevant_expedition
    )
    all_items_delivered = bool(items) and all(item.delivered for item in items)
    delivery_complete = bool(relevant_expedition) and not remaining and all_items_delivered and reallocated_pending <= 0
    expedition_status = None
    if relevant_expedition:
        if delivery_complete:
            expedition_status = "ENTREGUE"
        elif any_delivered:
            expedition_status = "ENTREGUE_PARCIAL"
        elif remaining and len(separated_open) == len(remaining):
            expedition_status = "SEPARADO"
        elif any_separated or expedition_started:
            expedition_status = "SEPARACAO_INICIADA"
        else:
            expedition_status = "EM_SEPARACAO"

    fiscal_records = [
        member.fiscal_record
        for member in members
        if member.fiscal_record and member.fiscal_record.active
    ]
    fiscal_items = [item for record in fiscal_records for item in record.items if item.active]
    fiscal_invoices = [invoice for record in fiscal_records for invoice in record.invoices if invoice.active]

    return AdministrativeFacts(
        active_items=len(items),
        undefined_flow_items=len(undefined),
        internal_items=len(internal),
        production_pending_items=len(production_pending),
        production_produced_items=len(produced_items),
        production_pending_quantity=sum(
            (balance.production_pending for _, balance in production_pending), Decimal("0")
        ).quantize(Decimal("0.0001")),
        production_complete=production_complete,
        production_partial=production_partial,
        production_released=production_released,
        latest_production_event=latest_production_event,
        production_reallocated_pending=reallocated_pending.quantize(Decimal("0.0001")),
        production_reallocated_completed=reallocated_completed.quantize(Decimal("0.0001")),
        remanagement_transfer_count=len(transfer_ids),
        galvanization_required_items=len(required_galv),
        galvanization_load_item_count=len(active_load_items),
        galvanization_sent_quantity=sum(
            (_decimal(item.sent_quantity) for item in active_load_items), Decimal("0")
        ).quantize(Decimal("0.0001")),
        galvanization_returned_quantity=sum(
            (_decimal(item.returned_quantity) for item in active_load_items), Decimal("0")
        ).quantize(Decimal("0.0001")),
        galvanization_all_returned=galv_all_returned,
        galvanization_load_waiting=waiting_load,
        galvanization_load_released=released_load,
        expedition_item_count=len(relevant_expedition),
        expedition_available_quantity=exp_available.quantize(Decimal("0.0001")),
        expedition_separated_quantity=exp_separated.quantize(Decimal("0.0001")),
        expedition_delivered_quantity=exp_delivered.quantize(Decimal("0.0001")),
        expedition_remanaged_quantity=exp_remanaged.quantize(Decimal("0.0001")),
        expedition_pending_quantity=exp_pending.quantize(Decimal("0.0001")),
        expedition_status=expedition_status,
        expedition_started=expedition_started,
        delivery_complete=delivery_complete,
        fiscal_invoice_count=len(fiscal_invoices),
        fiscal_billed_quantity=sum(
            (_decimal(item.billed_quantity) for item in fiscal_items), Decimal("0")
        ).quantize(Decimal("0.0001")),
    )


def _derived_production_status(facts: AdministrativeFacts) -> str | None:
    if facts.production_reallocated_pending > 0:
        return "ITEM_PENDENTE_FABRICACAO"
    if facts.production_complete:
        return "FINALIZADO"
    if facts.production_partial:
        return "FINALIZADO_PARCIAL"
    if facts.latest_production_event == "PRODUCTION_PAUSED":
        return "PARADO"
    if facts.latest_production_event in {"PRODUCTION_STARTED", "PRODUCTION_RESUMED"}:
        return "INICIADO"
    if facts.production_released:
        return "NAO_INICIADO"
    return None


def _derived_galvanization_status(facts: AdministrativeFacts) -> str | None:
    if facts.galvanization_all_returned:
        return "RETORNOU_GALVANIZACAO"
    if facts.galvanization_returned_quantity > 0:
        return "RETORNOU_PARCIAL"
    if facts.galvanization_load_released:
        return "ENVIADO_GALVANIZACAO"
    if facts.galvanization_load_waiting:
        return "EM_CARGA"
    if facts.production_complete and facts.galvanization_required_items:
        return "AGUARDANDO_ENVIO"
    return None


def _flow_situation(facts: AdministrativeFacts, shipping_status: str | None) -> str:
    if facts.production_reallocated_pending > 0:
        return "PENDENTE_POR_REMANEJAMENTO"
    if facts.production_partial:
        return "PARCIAL_COM_PENDENCIA"
    if shipping_status == "ENTREGUE_PARCIAL":
        return "PARCIAL_COM_PENDENCIA"
    if _derived_galvanization_status(facts) == "RETORNOU_PARCIAL":
        return "PARCIAL_EM_ANDAMENTO"
    return "NORMAL"


def _projection(
    facts: AdministrativeFacts,
    area: str,
    status: str,
) -> dict[str, Any]:
    production_status = _derived_production_status(facts)
    galvanization_status = _derived_galvanization_status(facts)
    shipping_status = status if area == "EXPEDICAO" else None
    completed = area == "EXPEDICAO" and status == "ENTREGUE"

    if area == "CONTROLE_GERAL":
        return {
            "current_area": area,
            "current_status": status,
            "general_status": status,
            "production_status": None,
            "galvanization_status": None,
            "shipping_status": None,
            "flow_situation": "NORMAL",
            "has_production_pending": False,
            "is_completed": False,
        }
    if area == "PRODUCAO":
        return {
            "current_area": area,
            "current_status": status,
            "general_status": "EM_PRODUCAO",
            "production_status": status,
            "galvanization_status": None,
            "shipping_status": None,
            "flow_situation": _flow_situation(facts, None),
            "has_production_pending": facts.production_reallocated_pending > 0 or facts.production_partial,
            "is_completed": False,
        }
    if area == "GALVANIZACAO":
        return {
            "current_area": area,
            "current_status": status,
            "general_status": "EM_GALVANIZACAO",
            "production_status": production_status,
            "galvanization_status": status,
            "shipping_status": "AGUARDANDO_SEPARACAO_PARCIAL" if status == "RETORNOU_PARCIAL" else None,
            "flow_situation": _flow_situation(facts, None),
            "has_production_pending": facts.production_reallocated_pending > 0,
            "is_completed": False,
        }
    return {
        "current_area": "FINALIZADO" if completed else "EXPEDICAO",
        "current_status": status,
        "general_status": "ENTREGUE" if completed else "EM_EXPEDICAO",
        "production_status": production_status,
        "galvanization_status": galvanization_status,
        "shipping_status": shipping_status,
        "flow_situation": _flow_situation(facts, shipping_status),
        "has_production_pending": facts.production_reallocated_pending > 0,
        "is_completed": completed,
    }


def _candidate(facts: AdministrativeFacts, area: str, status: str, description: str) -> CorrectionCandidate:
    return CorrectionCandidate(
        target_area=area,
        target_status=status,
        label=f"{area.replace('_', ' ').title()} / {status.replace('_', ' ').title()}",
        description=description,
        updates=_projection(facts, area, status),
    )


def allowed_corrections(
    proposal: Proposal,
    facts: AdministrativeFacts | None = None,
    *,
    include_applied: bool = False,
) -> list[CorrectionCandidate]:
    facts = facts or collect_facts(proposal)
    if proposal.is_cancelled or normalize_status(proposal.current_status) == "CANCELADA" or normalize_status(proposal.general_status) == "CANCELADA":
        return []

    candidates: list[CorrectionCandidate] = []
    if facts.expedition_status and (facts.expedition_started or facts.has_remanagement):
        candidates.append(
            _candidate(
                facts,
                "EXPEDICAO",
                facts.expedition_status,
                "Estado calculado pelas quantidades oficiais da Expedicao.",
            )
        )
    elif facts.galvanization_all_returned:
        candidates.append(
            _candidate(
                facts,
                "EXPEDICAO",
                "EM_SEPARACAO",
                "Todos os retornos de galvanizacao estao registrados; a proposta pode entrar na Expedicao.",
            )
        )
    elif facts.has_load_history:
        galv_status = _derived_galvanization_status(facts)
        if galv_status:
            candidates.append(
                _candidate(
                    facts,
                    "GALVANIZACAO",
                    galv_status,
                    "Estado calculado pelas cargas e retornos oficiais existentes.",
                )
            )
    elif not facts.production_complete:
        if facts.production_reallocated_pending > 0:
            candidates.append(
                _candidate(
                    facts,
                    "PRODUCAO",
                    "ITEM_PENDENTE_FABRICACAO",
                    "Existe saldo produtivo pendente criado pelo remanejamento oficial.",
                )
            )
        elif facts.production_partial:
            candidates.append(
                _candidate(
                    facts,
                    "PRODUCAO",
                    "FINALIZADO_PARCIAL",
                    "Existem itens produzidos e saldo produtivo ainda pendente.",
                )
            )
        elif facts.latest_production_event == "PRODUCTION_PAUSED":
            candidates.append(
                _candidate(facts, "PRODUCAO", "PARADO", "A ultima movimentacao produtiva oficial foi uma pausa.")
            )
        elif facts.latest_production_event in {"PRODUCTION_STARTED", "PRODUCTION_RESUMED"}:
            candidates.append(
                _candidate(facts, "PRODUCAO", "INICIADO", "A ultima movimentacao produtiva oficial iniciou ou retomou a producao.")
            )
        elif facts.production_released:
            candidates.append(
                _candidate(facts, "PRODUCAO", "NAO_INICIADO", "A proposta foi liberada, mas nao possui inicio de producao registrado.")
            )
        else:
            candidates.append(
                _candidate(facts, "CONTROLE_GERAL", "AGUARDANDO_LIBERACAO", "Nao existem fatos operacionais que sustentem uma etapa posterior.")
            )
    elif facts.expedition_status:
        candidates.append(
            _candidate(
                facts,
                "EXPEDICAO",
                facts.expedition_status,
                "Estado calculado pelas quantidades oficiais da Expedicao.",
            )
        )
    elif facts.production_complete:
        candidates.append(
            _candidate(
                facts,
                "PRODUCAO",
                "FINALIZADO",
                "Os saldos produtivos estao integralmente concluidos.",
            )
        )
        if facts.galvanization_required_items:
            candidates.append(
                _candidate(
                    facts,
                    "GALVANIZACAO",
                    "AGUARDANDO_ENVIO",
                    "A producao esta concluida e existem itens que exigem galvanizacao.",
                )
            )
        else:
            candidates.append(
                _candidate(
                    facts,
                    "EXPEDICAO",
                    "EM_SEPARACAO",
                    "A producao esta concluida e nenhum item exige galvanizacao.",
                )
            )
    result: list[CorrectionCandidate] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        key = (candidate.target_area, candidate.target_status)
        if key in seen:
            continue
        seen.add(key)
        if facts.has_fiscal_emission and candidate.target_area != "EXPEDICAO":
            continue
        if facts.has_delivery and candidate.target_area != "EXPEDICAO":
            continue
        if facts.has_load_history and candidate.target_area in {"CONTROLE_GERAL", "PRODUCAO"}:
            continue
        if facts.has_remanagement and candidate.target_area == "CONTROLE_GERAL":
            continue
        if include_applied or any(
            _state_value(getattr(proposal, field)) != _state_value(value)
            for field, value in candidate.updates.items()
        ):
            result.append(candidate)
    return result


def blockers_for(
    proposal: Proposal,
    target_area: str,
    target_status: str,
    facts: AdministrativeFacts | None = None,
) -> list[dict[str, str]]:
    facts = facts or collect_facts(proposal)
    area = normalize_area(target_area)
    status = normalize_status(target_status)
    blockers: list[dict[str, str]] = []

    def add(code: str, message: str) -> None:
        if code not in {row["code"] for row in blockers}:
            blockers.append({"code": code, "message": message})

    if proposal.is_cancelled or normalize_status(proposal.current_status) == "CANCELADA" or normalize_status(proposal.general_status) == "CANCELADA":
        add("PROPOSAL_CANCELLED_TERMINAL", "A proposta esta cancelada e nao pode ser reativada por uma correcao generica.")
        return blockers
    if area not in VALID_TARGETS or status not in VALID_TARGETS.get(area, set()):
        add("ADMIN_CORRECTION_TARGET_INVALID", "A combinacao de area e status nao pertence a correcao administrativa de estado.")
        return blockers

    all_candidates = allowed_corrections(proposal, facts, include_applied=True)
    factual_matches = [row for row in all_candidates if (row.target_area, row.target_status) == (area, status)]
    if factual_matches:
        candidate = factual_matches[0]
        if all(
            _state_value(getattr(proposal, field)) == _state_value(value)
            for field, value in candidate.updates.items()
        ):
            add("ADMIN_CORRECTION_NO_CHANGES", "A projecao solicitada ja esta integralmente aplicada.")
            return blockers
        return []

    if area == "EXPEDICAO" and status == "ENTREGUE":
        if not facts.has_delivery:
            add("DELIVERY_FACTS_MISSING", "Nao existem quantidades entregues que sustentem o estado ENTREGUE.")
        elif not facts.delivery_complete:
            add("DELIVERY_INCOMPLETE", f"A entrega possui saldo operacional de {facts.expedition_pending_quantity}.")
    if area == "PRODUCAO" and status == "FINALIZADO" and not facts.production_complete:
        add("PRODUCTION_INCOMPLETE", f"A producao possui {facts.production_pending_items} item(ns) e saldo {facts.production_pending_quantity} pendente.")
    if area == "PRODUCAO" and status == "PARADO":
        if facts.production_complete:
            add("PRODUCTION_ALREADY_COMPLETE", "Uma producao concluida nao pode ser corrigida para PARADO.")
        elif facts.latest_production_event != "PRODUCTION_PAUSED":
            add("PRODUCTION_PAUSE_FACT_MISSING", "Nao existe pausa produtiva oficial que sustente o estado PARADO.")
    if area == "PRODUCAO" and status == "INICIADO" and facts.latest_production_event not in {"PRODUCTION_STARTED", "PRODUCTION_RESUMED"}:
        add("PRODUCTION_START_FACT_MISSING", "Nao existe inicio ou retomada oficial que sustente o estado INICIADO.")
    if area == "GALVANIZACAO" and status == "RETORNOU_GALVANIZACAO":
        if facts.galvanization_returned_quantity <= 0:
            add("GALVANIZATION_RETURN_MISSING", "Nao existem retornos de galvanizacao registrados.")
        elif not facts.galvanization_all_returned:
            add("GALVANIZATION_RETURN_INCOMPLETE", "Os retornos registrados nao cobrem todos os itens que exigem galvanizacao.")
    if facts.has_delivery and not (area == "EXPEDICAO" and status in {facts.expedition_status, "ENTREGUE"}):
        add("DELIVERY_EXISTS", "Existem entregas registradas que impedem o retorno para o estado solicitado.")
    if facts.has_fiscal_emission and area != "EXPEDICAO":
        add("FISCAL_EMISSION_EXISTS", "Existem emissoes fiscais ativas que impedem o retorno para a etapa solicitada.")
    if facts.has_load_history and area in {"CONTROLE_GERAL", "PRODUCAO"}:
        add("LOAD_HISTORY_EXISTS", "Existem cargas de galvanizacao que impedem o retorno para a etapa solicitada.")
    if facts.has_remanagement and area == "CONTROLE_GERAL":
        add("REMANAGEMENT_EXISTS", "Existem remanejamentos oficiais que impedem o retorno ao Controle Geral.")
    if area in {"GALVANIZACAO", "EXPEDICAO"} and not facts.production_complete and facts.production_reallocated_pending <= 0:
        add("PRODUCTION_INCOMPLETE", "Os fatos produtivos ainda nao permitem avancar para a etapa solicitada.")
    if area == "GALVANIZACAO" and status in {"EM_CARGA", "ENVIADO_GALVANIZACAO", "RETORNOU_PARCIAL"} and not facts.has_load_history:
        add("LOAD_HISTORY_MISSING", "Nao existe carga oficial que sustente o estado de galvanizacao solicitado.")
    if not blockers:
        add("FACTS_REQUIRE_DIFFERENT_STATE", "Os fatos operacionais da proposta sustentam um estado diferente do solicitado.")
    return blockers


def preview(
    proposal: Proposal,
    target_area: str,
    target_status: str,
    facts: AdministrativeFacts | None = None,
) -> dict[str, Any]:
    facts = facts or collect_facts(proposal)
    area = normalize_area(target_area)
    status = normalize_status(target_status)
    candidates = allowed_corrections(proposal, facts)
    candidate = next(
        (row for row in candidates if (row.target_area, row.target_status) == (area, status)),
        None,
    )
    blockers = [] if candidate else blockers_for(proposal, area, status, facts)
    changes = []
    effects: list[str] = []
    if candidate:
        for field, after in candidate.updates.items():
            before = getattr(proposal, field)
            if _state_value(before) != _state_value(after):
                changes.append({"field": field, "before": _json_value(before), "after": _json_value(after)})
        if normalize_area(proposal.current_area) != normalize_area(candidate.updates["current_area"]):
            effects.append(
                f"A proposta deixara a fila {normalize_area(proposal.current_area) or '-'} e passara para {candidate.updates['current_area']}."
            )
        effects.append("As filas serao atualizadas apenas pelos campos de projecao listados.")

    changed_names = {row["field"] for row in changes}
    unchanged = list(PROTECTED_OPERATIONAL_FIELDS)
    unchanged.extend(field for field in STATE_FIELDS if field not in changed_names)
    return {
        "allowed": candidate is not None and bool(changes),
        "correction_type": "STATE",
        "expected_version": proposal.version,
        "current_state": snapshot(proposal, facts),
        "requested_state": {"area": area, "status": status},
        "changes": changes,
        "effects": effects,
        "unchanged_fields": unchanged,
        "warnings": [
            "Esta operacao e administrativa e auditada.",
            "Nenhum fato operacional sera criado, apagado ou alterado.",
        ],
        "blockers": blockers,
    }


def option_payload(candidate: CorrectionCandidate, proposal: Proposal) -> dict[str, Any]:
    changes = [
        field
        for field, value in candidate.updates.items()
        if _state_value(getattr(proposal, field)) != _state_value(value)
    ]
    return {
        "target_area": candidate.target_area,
        "target_status": candidate.target_status,
        "label": candidate.label,
        "description": candidate.description,
        "changed_fields": changes,
    }
