"""Cancelar e corrigir NF (sem banco): objetos ORM em memoria + sessao falsa.

Cobre a regra de negocio de `cancel_fiscal_invoice`, `correct_fiscal_invoice`,
`cancel_fiscal_invoice_item` (ultima linha), duplicidade (CANCELADA nao ocupa o
numero) e o resumo da nota cancelada. A parte de banco (indice unico parcial,
reuso do numero, HTTP) fica em test_proposals_integration.py.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from api.app.core import error_codes
from api.app.core.exceptions import ApiError
from api.app.modules.proposals import service
from api.app.modules.proposals.models import FiscalInvoice, FiscalInvoiceItem, FiscalItem, FiscalRecord, ProposalItem
from api.app.modules.proposals.schemas import (
    FiscalCancelInvoiceItemRequest,
    FiscalCancelInvoiceRequest,
    FiscalCorrectInvoiceRequest,
    FiscalEmissionItemInput,
)

ACTOR = SimpleNamespace(id=7)
D = Decimal


class FakeResult:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value

    def scalars(self):
        return self


class FakeSession:
    def __init__(self, execute_value=None):
        self.execute_value = execute_value
        self.statements = []
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return FakeResult(self.execute_value)

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    def expire_all(self):
        pass


def _fiscal_item(item_id: int, total="10", billed="0", status="PENDENTE") -> FiscalItem:
    proposal_item = ProposalItem(id=item_id, item_number=str(item_id), product_code=f"P{item_id}", description=f"Peca {item_id}")
    item = FiscalItem(
        id=item_id, proposal_item_id=item_id, proposal_id=1, total_quantity=D(total), billed_quantity=D(billed),
        total_weight=None, billed_weight=D("0"), status=status, version=1, active=True,
    )
    item.proposal_item = proposal_item
    return item


def _line(line_id: int, item: FiscalItem, qty: str, *, active=True, reason=None) -> FiscalInvoiceItem:
    line = FiscalInvoiceItem(
        id=line_id, fiscal_invoice_id=100, fiscal_item_id=item.id, proposal_id=1, proposal_item_id=item.proposal_item_id,
        quantity=D(qty).quantize(D("0.0001")), weight=None, active=active, cancel_reason=reason,
    )
    line.fiscal_item = item
    return line


def _world(*, second_item_billed: str = "0"):
    """Proposta com 2 itens de 10 pecas; a NF 100 fatura 4 do item 1 (e 10 do item 2 se `second_item_billed`)."""
    item1 = _fiscal_item(1, billed="4", status="PARCIAL")
    item2 = _fiscal_item(2, billed=second_item_billed, status="FATURADO" if second_item_billed == "10" else "PENDENTE")
    record = FiscalRecord(
        id=5, proposal_id=1, status_fiscal="NOTA_FISCAL_PARCIAL", fiscal_situation="NF_PARCIAL",
        entry_date=datetime.now(UTC).date(), version=3, active=True,
    )
    record.items = [item1, item2]
    invoice = FiscalInvoice(
        id=100, fiscal_record_id=5, proposal_id=1, invoice_number="NF-1", series=None, status="REGISTRADA", source="MANUAL",
        issued_at=datetime(2026, 11, 1, tzinfo=UTC), emission_type="PARCIAL", observation="obs antiga", version=1, active=True,
    )
    invoice.items = [_line(1000, item1, "4")] + ([_line(1001, item2, "10")] if second_item_billed == "10" else [])
    record.invoices = [invoice]
    return record, invoice, item1, item2


@pytest.fixture
def patched(monkeypatch):
    """Isola o servico do banco: devolve (nota, controle) fixos e captura eventos."""
    ctx = SimpleNamespace(events=[], record=None, invoice=None)

    async def fake_get_invoice_record(session, invoice_id):
        if ctx.invoice.status == "CANCELADA":
            raise ApiError(error_codes.FISCAL_INVOICE_ALREADY_CANCELLED, "ja cancelada", status_code=409)
        return ctx.invoice, ctx.record

    async def fake_event(session, record, event_type, actor, **kwargs):
        ctx.events.append((event_type, kwargs))

    async def fake_detail(session, record_id):
        return ("detail", record_id)

    monkeypatch.setattr(service, "_get_fiscal_invoice_record", fake_get_invoice_record)
    monkeypatch.setattr(service, "_record_fiscal_event", fake_event)
    monkeypatch.setattr(service, "get_fiscal_detail", fake_detail)
    return ctx


def _run(coro):
    return asyncio.run(coro)


# ---- schemas ---------------------------------------------------------------

def test_cancel_request_requires_reason_between_1_and_1000_chars():
    assert FiscalCancelInvoiceRequest(version=1, reason="  NF digitada errada ").reason == "NF digitada errada"
    for bad in ("", "   ", "x" * 1001):
        with pytest.raises(ValidationError):
            FiscalCancelInvoiceRequest(version=1, reason=bad)
    with pytest.raises(ValidationError):
        FiscalCancelInvoiceRequest(version=1)
    with pytest.raises(ValidationError):
        FiscalCancelInvoiceRequest(version=1, reason="ok", user_id=3)


def test_correct_request_shape():
    request = FiscalCorrectInvoiceRequest(version=2, invoice_number=" 123 ", series=" 1 ", items=[{"fiscal_item_id": 1, "quantity": "2"}])
    assert (request.invoice_number, request.series) == ("123", "1")
    with pytest.raises(ValidationError):
        FiscalCorrectInvoiceRequest(version=2, invoice_number="", items=[])


# ---- cancelar a nota inteira ----------------------------------------------

def test_cancel_invoice_cancels_every_line_reverts_balance_and_frees_record(patched):
    record, invoice, item1, item2 = _world(second_item_billed="10")
    record.status_fiscal, record.fiscal_situation = "NOTA_FISCAL_EMITIDA", "NF_EMITIDA"
    patched.record, patched.invoice = record, invoice
    session = FakeSession()

    result = _run(service.cancel_fiscal_invoice(session, 100, FiscalCancelInvoiceRequest(version=3, reason="Digitada errada"), ACTOR, request_id="r1"))

    assert result == ("detail", 5)
    assert session.commits == 1 and session.rollbacks == 0
    assert invoice.status == "CANCELADA"
    assert (invoice.cancel_reason, invoice.cancelled_by) == ("Digitada errada", 7)
    assert invoice.cancelled_at is not None
    assert all(not line.active and line.cancel_reason == "Digitada errada" and line.cancelled_by == 7 for line in invoice.items)
    assert (item1.billed_quantity, item1.status) == (D("0"), "PENDENTE")
    assert (item2.billed_quantity, item2.status) == (D("0"), "PENDENTE")
    assert (record.status_fiscal, record.fiscal_situation) == ("FALTA_EMITIR_NOTA_FISCAL", "AGUARDANDO_NF")
    assert record.last_emission_at is None
    event_type, kwargs = patched.events[0]
    assert event_type == "FISCAL_INVOICE_CANCELLED"
    assert kwargs["metadata"]["reason"] == "Digitada errada" and kwargs["metadata"]["invoice_number"] == "NF-1"
    assert len(kwargs["metadata"]["items"]) == 2


def test_cancel_invoice_keeps_other_live_invoices_counted(patched):
    record, invoice, item1, item2 = _world()
    other = FiscalInvoice(id=101, fiscal_record_id=5, proposal_id=1, invoice_number="NF-2", status="REGISTRADA", issued_at=datetime(2026, 11, 2, tzinfo=UTC), version=1, active=True)
    other_line = _line(2000, item2, "3")
    other_line.fiscal_invoice_id = 101
    item2.billed_quantity, item2.status = D("3"), "PARCIAL"
    other.items = [other_line]
    record.invoices = [invoice, other]
    patched.record, patched.invoice = record, invoice

    _run(service.cancel_fiscal_invoice(FakeSession(), 100, FiscalCancelInvoiceRequest(version=3, reason="x"), ACTOR, request_id=None))

    assert other.status == "REGISTRADA" and other_line.active
    assert item2.billed_quantity == D("3")
    assert record.status_fiscal == "NOTA_FISCAL_PARCIAL"
    assert service._invoice_numbers(record.invoices) == ["NF-2"]


def test_cancel_invoice_stale_version_changes_nothing(patched):
    record, invoice, item1, _ = _world()
    patched.record, patched.invoice = record, invoice
    session = FakeSession()

    with pytest.raises(ApiError) as caught:
        _run(service.cancel_fiscal_invoice(session, 100, FiscalCancelInvoiceRequest(version=2, reason="x"), ACTOR, request_id=None))

    assert caught.value.code == error_codes.FISCAL_VERSION_CONFLICT and caught.value.status_code == 409
    assert session.commits == 0 and session.rollbacks == 1
    assert invoice.status == "REGISTRADA" and item1.billed_quantity == D("4")


def test_cancel_invoice_already_cancelled_is_409(patched):
    record, invoice, _, _ = _world()
    invoice.status = "CANCELADA"
    patched.record, patched.invoice = record, invoice

    with pytest.raises(ApiError) as caught:
        _run(service.cancel_fiscal_invoice(FakeSession(), 100, FiscalCancelInvoiceRequest(version=3, reason="x"), ACTOR, request_id=None))

    assert caught.value.code == error_codes.FISCAL_INVOICE_ALREADY_CANCELLED


def test_cancelling_withdrawn_invoice_clears_withdrawal(patched):
    record, invoice, _, _ = _world()
    record.status_fiscal, record.fiscal_situation = "NOTA_FISCAL_EMITIDA", "NF_RETIRADA_CLIENTE"
    record.invoice_withdrawn_at, record.withdrawn_by, record.withdrawal_observation = datetime.now(UTC), 9, "Retirada"
    patched.record, patched.invoice = record, invoice

    _run(service.cancel_fiscal_invoice(FakeSession(), 100, FiscalCancelInvoiceRequest(version=3, reason="x"), ACTOR, request_id=None))

    assert record.fiscal_situation == "AGUARDANDO_NF"
    assert (record.invoice_withdrawn_at, record.withdrawn_by, record.withdrawal_observation) == (None, None, None)


# ---- corrigir -------------------------------------------------------------

def _correction(**overrides):
    data = dict(
        version=3, invoice_number="NF-9", series="2", issued_at=datetime(2026, 11, 5, tzinfo=UTC), observation="obs nova",
        items=[FiscalEmissionItemInput(fiscal_item_id=1, quantity=D("6"))],
    )
    data.update(overrides)
    return FiscalCorrectInvoiceRequest(**data)


def test_correct_invoice_keeps_id_changes_everything_and_records_before_after(patched):
    record, invoice, item1, item2 = _world()
    patched.record, patched.invoice = record, invoice
    session = FakeSession(execute_value=None)  # nenhuma outra NF com o numero

    _run(service.correct_fiscal_invoice(session, 100, _correction(), ACTOR, request_id="r2"))

    assert session.commits == 1
    assert invoice.id == 100 and invoice.status == "REGISTRADA"
    assert (invoice.invoice_number, invoice.series, invoice.observation) == ("NF-9", "2", "obs nova")
    assert invoice.issued_at == datetime(2026, 11, 5, tzinfo=UTC)
    old = invoice.items[0]
    assert not old.active and old.cancel_reason == service.CORRECTION_REPLACED_REASON
    (new,) = [row for row in session.added if isinstance(row, FiscalInvoiceItem)]
    assert (new.fiscal_invoice_id, new.fiscal_item_id, new.quantity) == (100, 1, D("6.0000"))
    assert item1.billed_quantity == D("6.0000") and item1.status == "PARCIAL"
    assert item1.version == 2  # reverter + reaplicar = um unico _touch
    assert record.status_fiscal == "NOTA_FISCAL_PARCIAL"
    event_type, kwargs = patched.events[0]
    assert event_type == "FISCAL_INVOICE_CORRECTED"
    metadata = kwargs["metadata"]
    assert metadata["before"]["invoice_number"] == "NF-1" and metadata["before"]["items"][0]["quantity"] == "4.0000"
    assert metadata["after"]["invoice_number"] == "NF-9" and metadata["after"]["series"] == "2"
    assert metadata["after"]["items"][0]["quantity"] == "6.0000"


def test_correct_invoice_can_switch_items_and_complete_the_record(patched):
    record, invoice, item1, item2 = _world()
    patched.record, patched.invoice = record, invoice
    both = [FiscalEmissionItemInput(fiscal_item_id=1), FiscalEmissionItemInput(fiscal_item_id=2)]

    _run(service.correct_fiscal_invoice(FakeSession(), 100, _correction(items=both), ACTOR, request_id=None))

    assert (item1.billed_quantity, item2.billed_quantity) == (D("10.0000"), D("10.0000"))
    assert record.status_fiscal == "NOTA_FISCAL_EMITIDA" and invoice.emission_type == "TOTAL"


def test_correct_invoice_rejects_quantity_above_balance_and_rolls_back(patched):
    record, invoice, _, _ = _world()
    patched.record, patched.invoice = record, invoice
    session = FakeSession()

    with pytest.raises(ApiError) as caught:
        _run(service.correct_fiscal_invoice(session, 100, _correction(items=[FiscalEmissionItemInput(fiscal_item_id=1, quantity=D("11"))]), ACTOR, request_id=None))

    assert caught.value.code == error_codes.FISCAL_QUANTITY_EXCEEDED
    assert session.commits == 0 and session.rollbacks == 1


def test_correct_invoice_requires_items(patched):
    record, invoice, _, _ = _world()
    patched.record, patched.invoice = record, invoice

    with pytest.raises(ApiError) as caught:
        _run(service.correct_fiscal_invoice(FakeSession(), 100, _correction(items=[]), ACTOR, request_id=None))

    assert caught.value.code == error_codes.FISCAL_INVOICE_CORRECTION_INVALID


def test_correct_invoice_blocked_when_withdrawn(patched):
    record, invoice, _, _ = _world()
    record.fiscal_situation = "NF_RETIRADA_CLIENTE"
    patched.record, patched.invoice = record, invoice

    with pytest.raises(ApiError) as caught:
        _run(service.correct_fiscal_invoice(FakeSession(), 100, _correction(), ACTOR, request_id=None))

    assert caught.value.code == error_codes.FISCAL_INVOICE_WITHDRAWN and caught.value.status_code == 409


def test_correct_invoice_blocked_when_cancelled(patched):
    record, invoice, _, _ = _world()
    invoice.status = "CANCELADA"
    patched.record, patched.invoice = record, invoice

    with pytest.raises(ApiError) as caught:
        _run(service.correct_fiscal_invoice(FakeSession(), 100, _correction(), ACTOR, request_id=None))

    assert caught.value.code == error_codes.FISCAL_INVOICE_ALREADY_CANCELLED


def test_correct_invoice_duplicate_number_of_another_invoice_is_409(patched):
    record, invoice, item1, _ = _world()
    patched.record, patched.invoice = record, invoice
    session = FakeSession(execute_value=(999,))  # outra NF ativa com o mesmo numero/serie

    with pytest.raises(ApiError) as caught:
        _run(service.correct_fiscal_invoice(session, 100, _correction(), ACTOR, request_id=None))

    assert caught.value.code == error_codes.FISCAL_INVOICE_DUPLICATED and caught.value.status_code == 409
    assert item1.billed_quantity == D("4")  # nada foi aplicado antes da validacao


# ---- duplicidade ----------------------------------------------------------

def _sql(statement) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True})).replace("\n", " ")


def test_duplicate_filter_ignores_cancelled_and_excludes_own_invoice():
    session = FakeSession()
    _run(service._ensure_invoice_number_free(session, "NF-1", None, except_invoice_id=100))
    sql = _sql(session.statements[0])
    assert "fiscal_invoices.status != 'CANCELADA'" in sql
    assert "fiscal_invoices.id != 100" in sql
    assert "coalesce(fiscal_invoices.series, '') = ''" in sql  # serie NULL == serie vazia (igual ao indice)

    session = FakeSession()
    _run(service._ensure_invoice_number_free(session, "NF-1", "3"))
    sql = _sql(session.statements[0])
    assert "fiscal_invoices.id !=" not in sql and "= '3'" in sql


def test_duplicate_filter_raises_when_another_live_invoice_exists():
    with pytest.raises(ApiError) as caught:
        _run(service._ensure_invoice_number_free(FakeSession(execute_value=(1,)), "NF-1", None))
    assert caught.value.code == error_codes.FISCAL_INVOICE_DUPLICATED


# ---- endpoint antigo: ultima linha cancela a nota -----------------------------

def test_cancel_last_line_marks_invoice_cancelled_and_frees_number(patched, monkeypatch):
    record, invoice, item1, _ = _world()
    line = invoice.items[0]
    line.invoice = invoice

    async def fake_get_record(session, record_id, **kwargs):
        return record

    monkeypatch.setattr(service, "_get_fiscal_record", fake_get_record)
    monkeypatch.setattr(service, "_ensure_proposal_not_cancelled", lambda proposal: None)
    line.fiscal_item.fiscal_record_id = 5
    session = FakeSession(execute_value=line)

    _run(service.cancel_fiscal_invoice_item(session, 1000, FiscalCancelInvoiceItemRequest(version=3, reason="Linha errada"), ACTOR, request_id=None))

    assert not line.active
    assert invoice.status == "CANCELADA" and invoice.cancel_reason == "Linha errada" and invoice.cancelled_by == 7
    assert item1.billed_quantity == D("0.0000")
    assert service._invoice_numbers(record.invoices) == []


def test_cancel_one_of_two_lines_keeps_invoice_live(patched, monkeypatch):
    record, invoice, _, item2 = _world(second_item_billed="10")
    line = invoice.items[0]
    line.invoice = invoice

    async def fake_get_record(session, record_id, **kwargs):
        return record

    monkeypatch.setattr(service, "_get_fiscal_record", fake_get_record)
    monkeypatch.setattr(service, "_ensure_proposal_not_cancelled", lambda proposal: None)
    line.fiscal_item.fiscal_record_id = 5

    _run(service.cancel_fiscal_invoice_item(FakeSession(execute_value=line), 1000, FiscalCancelInvoiceItemRequest(version=3, reason="x"), ACTOR, request_id=None))

    assert invoice.status == "REGISTRADA" and invoice.cancel_reason is None


# ---- resumo ---------------------------------------------------------------

def test_cancelled_summary_exposes_who_why_and_hides_replaced_lines():
    record, invoice, item1, item2 = _world()
    replaced = _line(1002, item1, "9", active=False, reason=service.CORRECTION_REPLACED_REASON)
    invoice.items.append(replaced)
    invoice.status, invoice.cancel_reason, invoice.cancelled_by = "CANCELADA", "Digitada errada", 7
    invoice.cancelled_at = datetime(2026, 11, 6, tzinfo=UTC)
    invoice.items[0].active = False

    summary = service._fiscal_invoice_summary(invoice, {7: "Maria"})

    assert (summary.status, summary.cancel_reason, summary.cancelled_by, summary.cancelled_by_name) == ("CANCELADA", "Digitada errada", 7, "Maria")
    assert summary.item_count == 1 and summary.quantity == D("4.0000")
    assert summary.items[0].product_code == "P1" and summary.items[0].description == "Peca 1"


def test_live_summary_has_no_cancellation_fields():
    _, invoice, _, _ = _world()
    summary = service._fiscal_invoice_summary(invoice, {7: "Maria"})
    assert (summary.cancelled_at, summary.cancelled_by, summary.cancelled_by_name, summary.cancel_reason) == (None, None, None, None)


# ---- timeline -------------------------------------------------------------

def test_timeline_texts():
    cancelled = service.ACTIVITY_TEMPLATES["FISCAL_INVOICE_CANCELLED"]("Ana", {"invoice_number": "123", "reason": "erro"})
    assert cancelled == "Ana cancelou a NF 123 (erro)."
    assert service.ACTIVITY_TEMPLATES["FISCAL_INVOICE_CORRECTED"]("Ana", {"invoice_number": "REGISTRO-9"}) == "Ana corrigiu a nota fiscal."
