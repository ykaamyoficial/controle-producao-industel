"""Concilia as pecas por estagio de todos os itens (Fase A do plano de remanejamento).

Somente leitura: abre uma sessao, le e imprime. Nao grava nada.

Uso (banco informado por DATABASE_URL, como a API):
    set DATABASE_URL=postgresql+asyncpg://usuario:senha@127.0.0.1:55432/controle_producao_dev
    python scripts/reconcile_item_stages.py
    python scripts/reconcile_item_stages.py --proposta CP05301 --amostras 20
    python scripts/reconcile_item_stages.py --json saida.json

Sai com codigo 1 se houver anomalia de gravidade ERROR (conta que nao fecha), para
poder rodar antes e depois de cada fase do plano e provar que nada mudou nos dados.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from api.app.database.session import dispose_engine, get_sessionmaker  # noqa: E402
from api.app.modules.proposals.models import Proposal  # noqa: E402
from api.app.modules.proposals.stage_ledger import SEVERITY, load_stage_ledger  # noqa: E402


async def run(args) -> int:
    async with get_sessionmaker()() as session:
        proposal_ids = None
        if args.proposta:
            proposal_ids = [int(i) for i in (await session.execute(select(Proposal.id).where(Proposal.proposal_number.in_(args.proposta)))).scalars()]
            if not proposal_ids:
                print("Nenhuma proposta encontrada para:", ", ".join(args.proposta))
                return 2
        ledger = await load_stage_ledger(session, proposal_ids=proposal_ids)
    await dispose_engine()

    by_code = Counter(anomaly.code for anomaly in ledger.anomalies)
    items_with_anomaly = {anomaly.item_id for anomaly in ledger.anomalies}
    errors = [anomaly for anomaly in ledger.anomalies if anomaly.severity == "ERROR"]
    flows = Counter(item.flow for item in ledger.items)

    print(f"Itens conferidos: {len(ledger.items)} ({', '.join(f'{name}: {count}' for name, count in sorted(flows.items()))})")
    print(f"Itens com alguma anomalia: {len(items_with_anomaly)}")
    if not by_code:
        print("Nenhuma anomalia: todas as contas fecham.")
    for code, count in sorted(by_code.items(), key=lambda row: (SEVERITY[row[0]] != "ERROR", -row[1])):
        print(f"  [{SEVERITY[code]:5}] {code}: {count}")

    samples: dict[str, list] = defaultdict(list)
    for anomaly in ledger.anomalies:
        if len(samples[anomaly.code]) < args.amostras:
            samples[anomaly.code].append(anomaly)
    for code, rows in samples.items():
        print(f"\n{code} (primeiros {len(rows)}):")
        for anomaly in rows:
            print(f"  {anomaly.proposal_number} item {anomaly.item_id} {anomaly.product_code or '-'}: {anomaly.detail}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "itens": len(ledger.items),
                    "anomalias": [
                        {"codigo": a.code, "gravidade": a.severity, "item_id": a.item_id, "proposta": a.proposal_number, "produto": a.product_code, "detalhe": a.detail}
                        for a in ledger.anomalies
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nRelatorio salvo em {args.json}")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--proposta", action="append", help="numero da proposta (pode repetir); sem isto, todas")
    parser.add_argument("--amostras", type=int, default=5, help="quantas anomalias mostrar por tipo (padrao 5)")
    parser.add_argument("--json", metavar="ARQUIVO", help="salva todas as anomalias em JSON")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
