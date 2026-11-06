"""Corrige quantidades de itens importadas errado (1.800 lido como 1.8) usando a API do Nomus.

Por padrao NAO grava nada (dry-run): so gera o relatorio CSV. Candidatos: itens ativos com
quantidade fracionada, em propostas ativas, nao canceladas, que nao sao parciais nem maes de
parciais (nessas a quantidade do item e um pedaco do pedido, nao o total do Nomus).

Classificacao de cada item comparado com o pedido do Nomus:
    OK         quantidade ja igual a do Nomus.
    SEGURO     sem faturamento e sem progresso de producao/galvanizacao/expedicao/remanejamento.
    RISCO      ja faturado (NF) ou com progresso: so grava com --include-risky.
    BLOQUEADO  quantidade nova menor que a ja faturada: nunca grava.
    SEM_NOMUS  proposta ou item nao encontrado no Nomus: nunca grava.

Ao gravar, por item: ProposalItem.quantity/total_weight, FiscalItem.total_quantity/total_weight
(+ status do item e do registro fiscal) e um ProposalEvent de auditoria. ExpeditionItem e
reconciliado pelo hook pre-commit da API. Uma transacao por proposta.

Uso (banco por DATABASE_URL, como a API; a chave do Nomus vem da config local do Desktop):
    set DATABASE_URL=postgresql+asyncpg://usuario:senha@127.0.0.1:55432/controle_producao_dev
    python scripts/corrigir_quantidades_nomus.py                      # dry-run
    python scripts/corrigir_quantidades_nomus.py --proposta CP05763   # dry-run de uma proposta
    python scripts/corrigir_quantidades_nomus.py --apply              # grava so os SEGUROS
    python scripts/corrigir_quantidades_nomus.py --apply --include-risky

Faca backup do banco antes de qualquer --apply (scripts/run_predeployment_backup.py).
Nunca rode --apply na API oficial (8000) sem autorizacao explicita.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OK, SEGURO, RISCO, BLOQUEADO, SEM_NOMUS = "OK", "SEGURO", "RISCO", "BLOQUEADO", "SEM_NOMUS"
EVENT_TYPE = "ITEM_QUANTITY_CORRECTED_FROM_NOMUS"
ZERO = Decimal("0")


@dataclass(frozen=True)
class ItemFacts:
    db_quantity: Decimal
    billed_quantity: Decimal = ZERO
    has_progress: bool = False


def classify(facts: ItemFacts, nomus_quantity: Decimal | None) -> tuple[str, list[str]]:
    if nomus_quantity is None:
        return SEM_NOMUS, ["ITEM_NAO_ENCONTRADO_NO_NOMUS"]
    if nomus_quantity == facts.db_quantity:
        return OK, []
    if nomus_quantity < facts.billed_quantity:
        return BLOQUEADO, ["NOVA_MENOR_QUE_FATURADA"]
    reasons = []
    if facts.billed_quantity > ZERO:
        reasons.append("FATURADO")
    if facts.has_progress:
        reasons.append("COM_PROGRESSO")
    return (RISCO if reasons else SEGURO), reasons


def item_key(item_number: object) -> int | None:
    digits = re.sub(r"\D", "", str(item_number or ""))
    return int(digits) if digits else None


def may_apply(status: str, include_risky: bool) -> bool:
    return status == SEGURO or (status == RISCO and include_risky)


@dataclass
class Row:
    proposal: str
    item_number: str
    product_code: str
    db_quantity: str
    nomus_quantity: str
    status: str
    reasons: str
    action: str = "dry-run"


@dataclass
class Report:
    rows: list[Row] = field(default_factory=list)

    def write_csv(self, path: Path) -> None:
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["proposta", "item", "produto", "qtd_sistema", "qtd_nomus", "classe", "motivos", "acao"])
            for row in self.rows:
                writer.writerow([row.proposal, row.item_number, row.product_code, row.db_quantity,
                                 row.nomus_quantity, row.status, row.reasons, row.action])


def fetch_nomus_quantities(proposal_number: str) -> dict[int, Decimal] | None:
    """Quantidades do pedido no Nomus por numero do item; None se a proposta nao for achada."""
    from app.services.nomus_api_client import NomusApiClient
    from app.services.nomus_api_config import NomusApiConfigStore
    from app.services.nomus_api_importer import NomusApiImporter, NomusApiImportError

    importer = NomusApiImporter(NomusApiClient(config_store=NomusApiConfigStore()))
    try:
        result = importer.fetch_proposal(proposal_number)
    except NomusApiImportError as exc:
        print(f"  {proposal_number}: Nomus nao respondeu o pedido ({exc})")
        return None
    return {
        key: Decimal(str(item.quantity))
        for item in result.items
        if item.quantity is not None and (key := item_key(item.item_number)) is not None
    }


async def run(args) -> int:
    from sqlalchemy import exists, func, or_, select
    from sqlalchemy.orm import aliased

    from api.app.database.session import dispose_engine, get_sessionmaker
    from api.app.modules.proposals import derived_sync  # noqa: F401  (registra o hook pre-commit)
    from api.app.modules.proposals.models import (
        ExpeditionItem, FiscalInvoiceItem, FiscalItem, FiscalRecord, GalvanizationLoadItem,
        ProductionAllocationTransfer, Proposal, ProposalEvent, ProposalItem,
        ProposalRemanagementItem, RemanagementStageTransfer,
    )
    from api.app.modules.proposals.service import _recalculate_fiscal_item_status, _recalculate_fiscal_record
    from api.app.modules.proposals.weights import calculate_known_weight

    report = Report()
    child = aliased(Proposal)
    factory = get_sessionmaker()
    async with factory() as session:
        query = (
            select(Proposal)
            .where(Proposal.active.is_(True), Proposal.is_cancelled.is_(False), Proposal.is_partial.is_(False))
            .where(Proposal.parent_proposal_id.is_(None))
            .where(~exists().where(child.parent_proposal_id == Proposal.id))
            .where(exists().where(
                ProposalItem.proposal_id == Proposal.id, ProposalItem.active.is_(True),
                ProposalItem.quantity != func.trunc(ProposalItem.quantity),
            ))
            .order_by(Proposal.proposal_number)
        )
        if args.proposta:
            query = query.where(Proposal.proposal_number.in_(args.proposta))
        proposals = (await session.execute(query)).scalars().all()
        print(f"Propostas candidatas: {len(proposals)}")

        for proposal in proposals:
            nomus = fetch_nomus_quantities(proposal.proposal_number)
            items = (await session.execute(
                select(ProposalItem).where(ProposalItem.proposal_id == proposal.id, ProposalItem.active.is_(True))
                .order_by(ProposalItem.item_number, ProposalItem.id)
            )).scalars().all()
            applied = 0
            for item in items:
                if item.quantity == item.quantity.to_integral_value():
                    continue
                key = item_key(item.item_number)
                nomus_qty = nomus.get(key) if nomus is not None and key is not None else None
                fiscal = (await session.execute(
                    select(FiscalItem).where(FiscalItem.proposal_item_id == item.id, FiscalItem.active.is_(True))
                )).scalar_one_or_none()
                progress = bool(item.produced or item.galvanized or item.delivered) or any([
                    (await session.execute(select(exists().where(GalvanizationLoadItem.proposal_item_id == item.id)))).scalar_one(),
                    (await session.execute(select(exists().where(
                        ExpeditionItem.proposal_item_id == item.id,
                        or_(ExpeditionItem.separated_quantity > 0, ExpeditionItem.delivered_quantity > 0, ExpeditionItem.remanaged_quantity > 0),
                    )))).scalar_one(),
                    (await session.execute(select(exists().where(or_(
                        ProposalRemanagementItem.source_item_id == item.id, ProposalRemanagementItem.destination_item_id == item.id,
                    ))))).scalar_one(),
                    (await session.execute(select(exists().where(or_(
                        ProductionAllocationTransfer.from_item_id == item.id, ProductionAllocationTransfer.to_item_id == item.id,
                    ))))).scalar_one(),
                    (await session.execute(select(exists().where(or_(
                        RemanagementStageTransfer.from_item_id == item.id, RemanagementStageTransfer.to_item_id == item.id,
                    ))))).scalar_one(),
                    (await session.execute(select(exists().where(FiscalInvoiceItem.proposal_item_id == item.id)))).scalar_one(),
                ])
                facts = ItemFacts(item.quantity, fiscal.billed_quantity if fiscal else ZERO, progress)
                status, reasons = classify(facts, nomus_qty)
                row = Row(proposal.proposal_number, str(item.item_number), item.product_code or "",
                          str(item.quantity), "" if nomus_qty is None else str(nomus_qty), status, ",".join(reasons))
                if args.apply and may_apply(status, args.include_risky):
                    old_quantity, old_weight = item.quantity, item.total_weight
                    item.quantity = nomus_qty.quantize(Decimal("0.0001"))
                    item.total_weight = calculate_known_weight(item.quantity, item.unit_weight)
                    item.version += 1
                    item.updated_at = datetime.now(timezone.utc)
                    if fiscal is not None:
                        fiscal.total_quantity = item.quantity
                        fiscal.total_weight = item.total_weight
                        fiscal.version += 1
                        _recalculate_fiscal_item_status(fiscal)
                    session.add(ProposalEvent(
                        proposal_id=proposal.id, item_id=item.id, event_type=EVENT_TYPE,
                        metadata_={"fonte": "Nomus API", "quantidade_anterior": str(old_quantity), "quantidade_nova": str(item.quantity),
                                   "peso_anterior": None if old_weight is None else str(old_weight),
                                   "peso_novo": None if item.total_weight is None else str(item.total_weight), "classe": status},
                    ))
                    row.action = "APLICADO"
                    applied += 1
                elif args.apply:
                    row.action = "PULADO"
                report.rows.append(row)
            if applied:
                await session.flush()
                record = (await session.execute(
                    select(FiscalRecord).where(FiscalRecord.proposal_id == proposal.id)
                )).scalar_one_or_none()
                if record is not None:
                    _recalculate_fiscal_record(record)
                await session.commit()
            else:
                await session.rollback()
    await dispose_engine()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = Path(args.csv) if args.csv else Path(f"corrigir_quantidades_nomus_{stamp}.csv")
    report.write_csv(path)
    counts: dict[str, int] = {}
    for row in report.rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    print("Itens por classe:", ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "nenhum")
    print("Aplicados:", sum(1 for row in report.rows if row.action == "APLICADO"))
    print(f"Relatorio: {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--proposta", action="append", help="numero da proposta (pode repetir); sem isto, todas as candidatas")
    parser.add_argument("--apply", action="store_true", help="grava no banco (sem isto e dry-run)")
    parser.add_argument("--include-risky", action="store_true", help="com --apply, grava tambem itens faturados ou com progresso")
    parser.add_argument("--csv", metavar="ARQUIVO", help="caminho do relatorio CSV")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
