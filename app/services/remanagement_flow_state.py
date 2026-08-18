from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import uuid4


@dataclass(frozen=True)
class RemanagementItemSelection:
    """Um item da proposta destino que o usuario pediu para remanejar (Fase 2).

    `current_need` viaja junto apenas para revalidacao/exibicao nas fases
    seguintes - a Fase 3+ deve tratar o servico/API como fonte de verdade,
    nao este valor congelado no momento da selecao.
    """

    destination_item_id: int
    product_code: str
    description: str
    unit: str | None
    remanage_quantity: Decimal
    current_need: Decimal


@dataclass(frozen=True)
class RemanagementSourceCandidate:
    """Uma proposta de origem com saldo pronto compativel (Fase 3). Somente
    leitura - nenhuma quantidade e alocada ainda, isso e trabalho da Fase 4."""

    source_proposal_id: int
    source_proposal_number: str
    source_item_id: int
    source_item_version: int
    client: str
    site: str | None
    available_quantity: Decimal
    unit: str | None
    operational_status: str | None


@dataclass(frozen=True)
class RemanagementItemAvailability:
    """Resultado da busca automatica (Fase 3) para um item do destino."""

    destination_item_id: int
    product_code: str
    description: str
    unit: str | None
    requested_quantity: Decimal
    total_available: Decimal
    coverage_status: str
    candidates: list[RemanagementSourceCandidate]


def availability_from_api(groups: list[dict]) -> list[RemanagementItemAvailability]:
    """Converte a resposta crua de `service.remanagement_availability` (Fase 3)
    nos dataclasses do estado compartilhado - usada tanto pela Etapa 3 quanto
    pela Etapa 4 (que tambem pode refazer a busca via 'Atualizar
    disponibilidade'), para as duas nunca divergirem na forma de ler o payload."""
    from app.ui.numeric_utils import parse_decimal

    result = []
    for group in groups:
        candidates = [
            RemanagementSourceCandidate(
                source_proposal_id=int(candidate["source_proposal_id"]),
                source_proposal_number=str(candidate.get("source_proposal_number") or ""),
                source_item_id=int(candidate["source_item_id"]),
                source_item_version=int(candidate.get("source_item_version") or 0),
                client=str(candidate.get("client") or ""),
                site=candidate.get("site"),
                available_quantity=parse_decimal(candidate.get("available_quantity"), "0"),
                unit=candidate.get("unit"),
                operational_status=candidate.get("operational_status"),
            )
            for candidate in group.get("candidates") or []
        ]
        result.append(RemanagementItemAvailability(
            destination_item_id=int(group["destination_item_id"]),
            product_code=str(group.get("product_code") or ""),
            description=str(group.get("description") or ""),
            unit=group.get("unit"),
            requested_quantity=parse_decimal(group.get("requested_quantity"), "0"),
            total_available=parse_decimal(group.get("total_available"), "0"),
            coverage_status=str(group.get("coverage_status") or "SEM_DISPONIBILIDADE"),
            candidates=candidates,
        ))
    return result


@dataclass(frozen=True)
class RemanagementSourceAllocation:
    """Quanto o usuario decidiu retirar de uma origem especifica (Fase 4).

    `available_snapshot` e apenas evidencia da revisao (o saldo visto no
    momento da alocacao) - nunca fonte de verdade para a compensacao real."""

    source_proposal_id: int
    source_item_id: int
    available_snapshot: Decimal
    allocated_quantity: Decimal


@dataclass(frozen=True)
class RemanagementItemAllocation:
    """Plano de alocacao de um item do destino entre uma ou mais origens (Fase 4)."""

    destination_item_id: int
    product_code: str
    unit: str | None
    requested_quantity: Decimal
    allocations: list[RemanagementSourceAllocation]

    @property
    def allocated_quantity(self) -> Decimal:
        return sum((row.allocated_quantity for row in self.allocations), Decimal("0"))

    @property
    def remaining_quantity(self) -> Decimal:
        return max(self.requested_quantity - self.allocated_quantity, Decimal("0"))

    @property
    def status(self) -> str:
        allocated = self.allocated_quantity
        if allocated <= 0:
            return "NAO_ALOCADO"
        if allocated >= self.requested_quantity:
            return "COMPLETO"
        return "PARCIAL"


@dataclass(frozen=True)
class RemanagementReviewSource:
    """Uma linha de compensacao revisada (Fase 6): quanto muda de pronto para
    o destino e de obrigacao para a origem (sempre iguais - regra 1:1), com o
    saldo da origem antes/depois simulados."""

    source_proposal_id: int
    source_item_id: int
    ready_transfer: Decimal
    production_compensation: Decimal
    source_before: Decimal
    source_after_simulated: Decimal


@dataclass(frozen=True)
class RemanagementReviewItem:
    destination_item_id: int
    product_code: str
    requested: Decimal
    allocated: Decimal
    remaining: Decimal
    status: str  # COMPLETO | PARCIAL | NAO_ALOCADO | INVALIDO
    sources: list[RemanagementReviewSource]


@dataclass(frozen=True)
class RemanagementReviewSummary:
    product_count: int
    source_proposal_count: int
    source_item_count: int
    total_quantity: Decimal | None
    total_unit: str | None
    complete_items: int
    partial_items: int
    not_allocated_items: int
    invalid_items: int


@dataclass(frozen=True)
class RemanagementReviewError:
    code: str
    message: str
    destination_item_id: int | None
    source_item_id: int | None


@dataclass(frozen=True)
class RemanagementReviewResult:
    """Resultado da revisao/simulacao (Fase 6) - somente leitura, nada aqui
    foi persistido. `valid` so e True quando nao ha `errors` e ha ao menos um
    item com alocacao (mesma regra do motor de compensacao)."""

    destination_proposal_id: int
    valid: bool
    warnings: list[str]
    errors: list[RemanagementReviewError]
    summary: RemanagementReviewSummary
    items: list[RemanagementReviewItem]


def review_from_api(payload: dict) -> RemanagementReviewResult:
    """Converte a resposta crua de `service.remanagement_review` (Fase 6) nos
    dataclasses do estado compartilhado."""
    from app.ui.numeric_utils import parse_decimal

    summary_payload = payload.get("summary") or {}
    total_quantity = summary_payload.get("total_quantity")
    summary = RemanagementReviewSummary(
        product_count=int(summary_payload.get("product_count") or 0),
        source_proposal_count=int(summary_payload.get("source_proposal_count") or 0),
        source_item_count=int(summary_payload.get("source_item_count") or 0),
        total_quantity=parse_decimal(total_quantity, "0") if total_quantity is not None else None,
        total_unit=summary_payload.get("total_unit"),
        complete_items=int(summary_payload.get("complete_items") or 0),
        partial_items=int(summary_payload.get("partial_items") or 0),
        not_allocated_items=int(summary_payload.get("not_allocated_items") or 0),
        invalid_items=int(summary_payload.get("invalid_items") or 0),
    )
    items = [
        RemanagementReviewItem(
            destination_item_id=int(item["destination_item_id"]),
            product_code=str(item.get("product_code") or ""),
            requested=parse_decimal(item.get("requested"), "0"),
            allocated=parse_decimal(item.get("allocated"), "0"),
            remaining=parse_decimal(item.get("remaining"), "0"),
            status=str(item.get("status") or "NAO_ALOCADO"),
            sources=[
                RemanagementReviewSource(
                    source_proposal_id=int(source["source_proposal_id"]),
                    source_item_id=int(source["source_item_id"]),
                    ready_transfer=parse_decimal(source.get("ready_transfer"), "0"),
                    production_compensation=parse_decimal(source.get("production_compensation"), "0"),
                    source_before=parse_decimal(source.get("source_before"), "0"),
                    source_after_simulated=parse_decimal(source.get("source_after_simulated"), "0"),
                )
                for source in item.get("sources") or []
            ],
        )
        for item in payload.get("items") or []
    ]
    errors = [
        RemanagementReviewError(
            code=str(error.get("code") or ""),
            message=str(error.get("message") or ""),
            destination_item_id=error.get("destination_item_id"),
            source_item_id=error.get("source_item_id"),
        )
        for error in payload.get("errors") or []
    ]
    return RemanagementReviewResult(
        destination_proposal_id=int(payload["destination_proposal_id"]),
        valid=bool(payload.get("valid")),
        warnings=list(payload.get("warnings") or []),
        errors=errors,
        summary=summary,
        items=items,
    )


@dataclass
class RemanagementFlowState:
    """Estado do novo fluxo de Remanejamento Compensado (Destino -> Itens ->
    Busca automatica -> Origens -> Compensacao -> Revisao -> Confirmar).

    Um unico objeto e compartilhado por todas as telas do fluxo (Fase 1, 2, ...)
    para que voltar uma etapa preserve o que ja foi escolhido nas etapas
    anteriores, sem recriar estado do zero a cada dialogo aberto.
    """

    destination_proposal_id: int | None = None
    destination_version: int | None = None
    selected_item_ids: list[int] = field(default_factory=list)  # Fase 2
    item_selections: list[RemanagementItemSelection] = field(default_factory=list)  # Fase 2
    availability: list[RemanagementItemAvailability] = field(default_factory=list)  # Fase 3
    allocations: list[RemanagementItemAllocation] = field(default_factory=list)  # Fase 4
    reason: str = ""  # Fase 6
    simulation: RemanagementReviewResult | None = None  # Fase 6
    # Fase 7: chave de idempotencia da operacao inteira (pode abranger varias
    # origens), gerada uma vez por tentativa de remanejamento - reenviar a
    # confirmacao (retry/duplo clique) com o MESMO id nunca duplica a gravacao.
    operation_id: str = field(default_factory=lambda: str(uuid4()))

    def set_destination(self, proposal_id: int | None, version: int | None = None) -> None:
        """Trocar o destino descarta qualquer selecao de itens/alocacao feita
        para o destino anterior - nunca reaproveitar item_id de outra proposta."""
        if proposal_id != self.destination_proposal_id:
            self.selected_item_ids = []
            self.item_selections = []
            self.availability = []
            self.allocations = []
            self.reason = ""
            self.simulation = None
            self.operation_id = str(uuid4())
        self.destination_proposal_id = proposal_id
        self.destination_version = version

    def is_destination_selected(self) -> bool:
        return self.destination_proposal_id is not None

    def set_item_selections(self, selections: list[RemanagementItemSelection]) -> None:
        # Mudar quais itens/quantidades foram pedidos invalida qualquer busca
        # de disponibilidade e alocacao anterior (Fase 3/4 devem ser refeitas).
        # O motivo digitado e preservado - o contexto continua o mesmo destino.
        self.item_selections = list(selections)
        self.selected_item_ids = [row.destination_item_id for row in selections]
        self.availability = []
        self.allocations = []
        self.simulation = None

    def set_availability(self, items: list[RemanagementItemAvailability]) -> None:
        # Nao limpa `allocations` de proposito: reabrir a Etapa 4 deve
        # revalidar o plano existente contra a disponibilidade nova, nao
        # descarta-lo de cara (secao 30 da Fase 4 / secao 23 revalidacao).
        self.availability = list(items)
        self.simulation = None

    def set_allocations(self, allocations: list[RemanagementItemAllocation]) -> None:
        # Alterar a alocacao sempre invalida uma simulacao/revisao anterior -
        # a Fase 6 deve recalcular a compensacao do zero (secao 27 da Fase 6).
        self.allocations = list(allocations)
        self.simulation = None

    def set_reason(self, reason: str) -> None:
        self.reason = reason

    def set_simulation(self, result: RemanagementReviewResult | None) -> None:
        self.simulation = result
