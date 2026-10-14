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
class ProposalLine:
    proposal_number: str
    customer_name: str
    quantity: Decimal = Decimal("0")
    weight: Decimal | None = None
    note: str | None = None


@dataclass(frozen=True)
class LoadLine:
    code: str
    driver_name: str | None
    status: str
    happened: str  # "liberada", "retornou", ...


@dataclass(frozen=True)
class TransitionLine:
    from_status: str | None
    to_status: str | None
    count: int


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

    # Producao
    produced_pieces: Decimal = Decimal("0")
    produced_weight: Decimal = Decimal("0")
    produced_lines: list[ProposalLine] = field(default_factory=list)
    production_started: int = 0
    production_completed: int = 0

    # Galvanizacao
    galv_sent_pieces: Decimal = Decimal("0")
    galv_returned_pieces: Decimal = Decimal("0")
    galv_returned_lines: list[ProposalLine] = field(default_factory=list)
    galv_loads: list[LoadLine] = field(default_factory=list)

    # Expedicao
    separated_pieces: Decimal = Decimal("0")
    delivered_pieces: Decimal = Decimal("0")
    delivered_weight: Decimal = Decimal("0")
    delivered_lines: list[ProposalLine] = field(default_factory=list)

    # Propostas
    proposals_created: int = 0
    proposals_cancelled: int = 0
    transitions: list[TransitionLine] = field(default_factory=list)

    # Atencao
    overdue_total: int = 0
    overdue: list[ProposalLine] = field(default_factory=list)
    due_soon_total: int = 0
    loads_waiting_return: int = 0

    # Sistema
    syncs: list[SyncLine] = field(default_factory=list)

    @property
    def has_activity(self) -> bool:
        """Dia 'vazio' (decisao do produto): nao envia. Pendencias sozinhas
        nao contam como movimento."""
        return any(
            (
                self.produced_pieces,
                self.production_started,
                self.production_completed,
                self.galv_sent_pieces,
                self.galv_returned_pieces,
                self.galv_loads,
                self.separated_pieces,
                self.delivered_pieces,
                self.proposals_created,
                self.proposals_cancelled,
                self.transitions,
                self.syncs,
            )
        )
