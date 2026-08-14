from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from api.app.modules.proposals.admin_correction import (
    allowed_corrections,
    blockers_for,
    collect_facts,
    preview,
    snapshot,
)
from api.app.modules.proposals.models import (
    FiscalInvoice,
    FiscalItem,
    FiscalRecord,
    ExpeditionItem,
    GalvanizationLoad,
    GalvanizationLoadItem,
    Proposal,
    ProposalEvent,
    ProposalItem,
)
from api.app.modules.proposals.schemas import ProposalAdministrativeCorrectionRequest


def _proposal(*, produced: bool = False, galvanization: str = "NAO") -> Proposal:
    proposal = Proposal(
        id=1,
        proposal_number="CP-ADMIN-1",
        customer_name="Cliente",
        current_area="PRODUCAO",
        current_status="NAO_INICIADO",
        general_status="EM_PRODUCAO",
        production_status="NAO_INICIADO",
        galvanization_status=None,
        shipping_status=None,
        warehouse_status=None,
        flow_situation="NORMAL",
        has_production_pending=False,
        is_cancelled=False,
        is_completed=False,
        version=7,
        active=True,
    )
    item = ProposalItem(
        id=11,
        proposal_id=1,
        item_number="1",
        description="Item",
        quantity=Decimal("10.0000"),
        produce_internally="SIM",
        requires_galvanization=galvanization,
        flow_defined=True,
        produced=produced,
        galvanized=False,
        delivered=False,
        active=True,
        version=1,
    )
    proposal.items = [item]
    proposal.events = [
        ProposalEvent(
            id=1,
            proposal_id=1,
            event_type="PROPOSAL_STATUS_CHANGED",
            to_area="PRODUCAO",
            to_status="LIBERADO_PRODUCAO",
            created_at=datetime.now(UTC),
        )
    ]
    proposal.galvanization_load_items = []
    proposal.expedition_items = []
    return proposal


def test_completed_production_without_galvanization_offers_only_factual_repairs_and_preview_is_read_only():
    proposal = _proposal(produced=True, galvanization="NAO")
    before = snapshot(proposal)

    options = {(row.target_area, row.target_status) for row in allowed_corrections(proposal)}
    result = preview(proposal, "EXPEDICAO", "EM_SEPARACAO")

    assert options == {("PRODUCAO", "FINALIZADO"), ("EXPEDICAO", "EM_SEPARACAO")}
    assert result["allowed"] is True
    assert any(row["field"] == "current_area" for row in result["changes"])
    assert snapshot(proposal) == before


def test_impossible_delivery_production_completion_and_total_return_have_specific_blockers():
    proposal = _proposal(produced=False, galvanization="SIM")

    delivered = blockers_for(proposal, "EXPEDICAO", "ENTREGUE")
    completed = blockers_for(proposal, "PRODUCAO", "FINALIZADO")
    returned = blockers_for(proposal, "GALVANIZACAO", "RETORNOU_GALVANIZACAO")

    assert "DELIVERY_FACTS_MISSING" in {row["code"] for row in delivered}
    assert "PRODUCTION_INCOMPLETE" in {row["code"] for row in completed}
    assert "GALVANIZATION_RETURN_MISSING" in {row["code"] for row in returned}


def test_cancelled_proposal_is_terminal_for_options_and_preview():
    proposal = _proposal()
    proposal.is_cancelled = True
    proposal.current_area = "CONTROLE_GERAL"
    proposal.current_status = "CANCELADA"
    proposal.general_status = "CANCELADA"

    assert allowed_corrections(proposal) == []
    result = preview(proposal, "PRODUCAO", "NAO_INICIADO")
    assert result["allowed"] is False
    assert result["blockers"][0]["code"] == "PROPOSAL_CANCELLED_TERMINAL"


def test_pause_is_supported_only_by_latest_official_production_event():
    proposal = _proposal()
    proposal.events.append(
        ProposalEvent(
            id=2,
            proposal_id=1,
            event_type="PRODUCTION_PAUSED",
            created_at=datetime.now(UTC),
        )
    )

    assert {(row.target_area, row.target_status) for row in allowed_corrections(proposal)} == {
        ("PRODUCAO", "PARADO")
    }
    proposal.events[-1].event_type = "PRODUCTION_STARTED"
    assert "PRODUCTION_PAUSE_FACT_MISSING" in {
        row["code"] for row in blockers_for(proposal, "PRODUCAO", "PARADO")
    }


def test_load_history_blocks_rewind_without_changing_load():
    proposal = _proposal(produced=True, galvanization="SIM")
    load = GalvanizationLoad(id=21, driver_name="Motorista", status="LIBERADA_PARA_ENVIO", active=True, version=1)
    load_item = GalvanizationLoadItem(
        id=22,
        load_id=21,
        proposal_id=1,
        proposal_item_id=11,
        sent_quantity=Decimal("10.0000"),
        returned_quantity=Decimal("0"),
        active=True,
        version=1,
    )
    load_item.load = load
    proposal.galvanization_load_items = [load_item]
    before = (load_item.sent_quantity, load_item.returned_quantity, load.status)

    blockers = blockers_for(proposal, "PRODUCAO", "FINALIZADO")

    assert "LOAD_HISTORY_EXISTS" in {row["code"] for row in blockers}
    assert (load_item.sent_quantity, load_item.returned_quantity, load.status) == before


def test_available_partial_quantity_does_not_hide_the_still_active_production_or_galvanization_stage():
    production = _proposal(produced=True, galvanization="NAO")
    pending_item = ProposalItem(
        id=12,
        proposal_id=1,
        item_number="2",
        description="Item pendente",
        quantity=Decimal("10"),
        produce_internally="SIM",
        requires_galvanization="NAO",
        flow_defined=True,
        produced=False,
        galvanized=False,
        delivered=False,
        active=True,
        version=1,
    )
    production.items.append(pending_item)
    ready = ExpeditionItem(
        id=41,
        proposal_id=1,
        proposal_item_id=11,
        available_quantity=Decimal("10"),
        separated_quantity=Decimal("0"),
        delivered_quantity=Decimal("0"),
        remanaged_quantity=Decimal("0"),
        origin="PRODUCAO",
        status="EM_SEPARACAO",
        active=True,
        version=1,
    )
    production.expedition_items = [ready]
    production.items[0].expedition_item = ready
    assert {(row.target_area, row.target_status) for row in allowed_corrections(production)} == {
        ("PRODUCAO", "FINALIZADO_PARCIAL")
    }

    galvanization = _proposal(produced=True, galvanization="SIM")
    load = GalvanizationLoad(id=51, driver_name="Motorista", status="RETORNO_PARCIAL", active=True, version=1)
    load_item = GalvanizationLoadItem(
        id=52,
        load_id=51,
        proposal_id=1,
        proposal_item_id=11,
        sent_quantity=Decimal("10"),
        returned_quantity=Decimal("5"),
        active=True,
        version=1,
    )
    load_item.load = load
    galvanization.galvanization_load_items = [load_item]
    partial_ready = ExpeditionItem(
        id=53,
        proposal_id=1,
        proposal_item_id=11,
        available_quantity=Decimal("5"),
        separated_quantity=Decimal("0"),
        delivered_quantity=Decimal("0"),
        remanaged_quantity=Decimal("0"),
        origin="GALVANIZACAO",
        status="EM_SEPARACAO",
        active=True,
        version=1,
    )
    galvanization.expedition_items = [partial_ready]
    galvanization.items[0].expedition_item = partial_ready
    assert {(row.target_area, row.target_status) for row in allowed_corrections(galvanization)} == {
        ("GALVANIZACAO", "RETORNOU_PARCIAL")
    }


def test_mother_administrative_facts_consolidate_direct_children_without_mixing_child_actions():
    mother = _proposal(produced=True, galvanization="NAO")
    child = _proposal(produced=False, galvanization="NAO")
    child.id = 2
    child.parent_proposal_id = mother.id
    child.is_partial = True
    child.items[0].id = 22
    child.items[0].proposal_id = child.id
    mother.partial_children = [child]

    mother_facts = collect_facts(mother)
    child_facts = collect_facts(child)

    assert mother_facts.active_items == 2
    assert mother_facts.production_produced_items == 1
    assert mother_facts.production_pending_items == 1
    assert mother_facts.production_partial is True
    assert child_facts.active_items == 1
    assert child_facts.production_pending_items == 1


def test_fiscal_emission_blocks_rewind_and_is_part_of_snapshot():
    proposal = _proposal(produced=True)
    record = FiscalRecord(
        id=31,
        proposal_id=1,
        status_fiscal="NOTA_FISCAL_PARCIAL",
        fiscal_situation="EMITIDA",
        entry_date=datetime.now(UTC).date(),
        active=True,
        version=1,
    )
    record.items = [
        FiscalItem(
            id=32,
            fiscal_record_id=31,
            proposal_id=1,
            proposal_item_id=11,
            total_quantity=Decimal("10"),
            billed_quantity=Decimal("2"),
            billed_weight=Decimal("0"),
            status="PARCIAL",
            active=True,
            version=1,
        )
    ]
    record.invoices = [
        FiscalInvoice(
            id=33,
            fiscal_record_id=31,
            proposal_id=1,
            invoice_number="NF-1",
            issued_at=datetime.now(UTC),
            status="REGISTRADA",
            active=True,
            version=1,
        )
    ]
    proposal.fiscal_record = record

    facts = collect_facts(proposal)
    blockers = blockers_for(proposal, "PRODUCAO", "FINALIZADO", facts)

    assert facts.fiscal_invoice_count == 1
    assert facts.fiscal_billed_quantity == Decimal("2.0000")
    assert "FISCAL_EMISSION_EXISTS" in {row["code"] for row in blockers}
    assert snapshot(proposal, facts)["fiscal_status"] == "NOTA_FISCAL_PARCIAL"


def test_apply_schema_requires_reason_version_and_idempotency_key():
    with pytest.raises(ValidationError):
        ProposalAdministrativeCorrectionRequest(
            to_area="EXPEDICAO",
            to_status="EM_SEPARACAO",
            reason="Motivo",
            idempotency_key="admin-test-1",
        )
    with pytest.raises(ValidationError):
        ProposalAdministrativeCorrectionRequest(
            expected_version=7,
            to_area="EXPEDICAO",
            to_status="EM_SEPARACAO",
            reason="   ",
            idempotency_key="admin-test-1",
        )
