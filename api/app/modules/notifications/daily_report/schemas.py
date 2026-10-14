from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal


@dataclass(frozen=True)
class ReportWindow:
    """Intervalo [start, end) coberto pelo relatorio. Sempre dias fechados
    (00:00 -> 00:00), para o resultado ser reproduzivel."""

    start: datetime
    end: datetime

    @property
    def label(self) -> str:
        last_day = (self.end - timedelta(seconds=1)).date()
        first_day = self.start.date()
        if first_day == last_day:
            return _format_date(first_day)
        return f"{_format_date(first_day)} a {_format_date(last_day)}"


def _format_date(value: date) -> str:
    weekdays = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    return f"{weekdays[value.weekday()]}, {value:%d/%m/%Y}"


def report_window_for(today: date, *, last_sent: date | None = None, tzinfo=None) -> ReportWindow:
    """Janela padrao: desde o ultimo relatorio enviado (ou do ultimo dia util)
    ate 00:00 de hoje. Na segunda-feira cobre sexta, sabado e domingo."""
    end = datetime.combine(today, time.min, tzinfo=tzinfo)
    if last_sent is not None and last_sent < today:
        start_day = last_sent
    else:
        start_day = today - timedelta(days=1)
        while start_day.weekday() >= 5:  # pula sabado/domingo para tras
            start_day -= timedelta(days=1)
        if today.weekday() == 0:
            start_day = today - timedelta(days=3)
    return ReportWindow(start=datetime.combine(start_day, time.min, tzinfo=tzinfo), end=end)


@dataclass(frozen=True)
class ProposalRow:
    """Uma proposta no relatorio. Pecas sao so apoio: `pieces_moved` do dia e
    `pieces_total` da proposta ("12 de 30 pecas")."""

    proposal_number: str
    customer_name: str
    current_status: str | None = None  # "Expedicao - Em separacao"
    from_state: str | None = None
    to_state: str | None = None
    pieces_moved: Decimal | None = None
    pieces_total: Decimal | None = None
    note: str | None = None


@dataclass(frozen=True)
class StageSummary:
    """Propostas abertas hoje em uma etapa (Producao, Galvanizacao, ...)."""

    label: str
    total: int
    statuses: list[tuple[str, int]] = field(default_factory=list)
    note: str | None = None


@dataclass(frozen=True)
class MovementGroup:
    """Propostas que mudaram de status no periodo, agrupadas pelo estado final."""

    key: str
    title: str
    total: int
    proposals: list[ProposalRow] = field(default_factory=list)


@dataclass(frozen=True)
class AttentionList:
    title: str
    total: int
    rows: list[ProposalRow] = field(default_factory=list)


@dataclass(frozen=True)
class SyncLine:
    sync_type: str
    status: str
    created: int
    updated: int
    rejected: int
    errors: int


@dataclass
class DailyReport:
    window: ReportWindow
    recipient_name: str
    scope_label: str  # "Fábrica inteira" | "Suas propostas"
    is_global: bool

    # Resumo
    open_total: int = 0
    changed_total: int = 0  # propostas que mudaram de status no periodo
    delivered_total: int = 0  # propostas entregues no periodo
    proposals_created: int = 0
    proposals_cancelled: int = 0

    # Panorama atual por etapa e movimentos do periodo
    stages: list[StageSummary] = field(default_factory=list)
    movements: list[MovementGroup] = field(default_factory=list)

    # Atencao
    overdue: AttentionList = field(default_factory=lambda: AttentionList("Atrasadas", 0))
    due_soon: AttentionList = field(default_factory=lambda: AttentionList("Vencem em até 3 dias", 0))
    stale: AttentionList = field(default_factory=lambda: AttentionList("Paradas há muito tempo", 0))
    pending_partials: AttentionList = field(default_factory=lambda: AttentionList("Parciais pendentes", 0))

    # Sistema (so visao global)
    syncs: list[SyncLine] = field(default_factory=list)

    @property
    def has_activity(self) -> bool:
        """Dia 'vazio' (decisao do produto): nao envia. Pendencias e atrasos
        sozinhos nao contam como movimento."""
        return bool(self.movements or self.syncs or self.proposals_created or self.proposals_cancelled)
