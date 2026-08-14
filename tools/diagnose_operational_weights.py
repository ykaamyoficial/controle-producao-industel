"""Diagnostico somente leitura para pesos operacionais historicos.

Uso: python tools/diagnose_operational_weights.py
Requer DATABASE_URL configurada. A transacao e explicitamente READ ONLY e
sempre revertida; nenhuma linha e corrigida por esta ferramenta.
"""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import text

from api.app.database.session import dispose_engine, get_engine


COUNT_QUERIES = {
    "proposal_items_weight_zero": "SELECT count(*) FROM proposal_items WHERE unit_weight = 0",
    "proposal_items_weight_null": "SELECT count(*) FROM proposal_items WHERE unit_weight IS NULL",
    "proposals_with_weight_zero": "SELECT count(DISTINCT proposal_id) FROM proposal_items WHERE unit_weight = 0",
    "proposals_with_weight_null": "SELECT count(DISTINCT proposal_id) FROM proposal_items WHERE unit_weight IS NULL",
    "load_items_weight_zero": "SELECT count(*) FROM galvanization_load_items WHERE unit_weight = 0 OR sent_weight = 0",
    "load_items_weight_null": "SELECT count(*) FROM galvanization_load_items WHERE unit_weight IS NULL OR sent_weight IS NULL",
    "loads_own_weight_zero": "SELECT count(*) FROM galvanization_loads WHERE load_weight = 0",
    "loads_own_weight_null": "SELECT count(*) FROM galvanization_loads WHERE load_weight IS NULL",
    "galvanization_loads_with_unknown_item_weight": """
        SELECT count(DISTINCT gli.load_id)
        FROM galvanization_load_items gli
        JOIN proposal_items pi ON pi.id = gli.proposal_item_id
        WHERE pi.unit_weight IS NULL OR pi.unit_weight = 0
    """,
    "expedition_rows_with_unknown_item_weight": """
        SELECT count(*)
        FROM expedition_items ei
        JOIN proposal_items pi ON pi.id = ei.proposal_item_id
        WHERE pi.unit_weight IS NULL OR pi.unit_weight = 0
    """,
    "fiscal_rows_with_unknown_item_weight": """
        SELECT count(*)
        FROM fiscal_items fi
        JOIN proposal_items pi ON pi.id = fi.proposal_item_id
        WHERE pi.unit_weight IS NULL OR pi.unit_weight = 0
    """,
}


async def collect_weight_diagnostics() -> dict[str, int]:
    engine = get_engine()
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            return {
                name: int((await connection.execute(text(query))).scalar_one() or 0)
                for name, query in COUNT_QUERIES.items()
            }
        finally:
            await transaction.rollback()


async def _main() -> None:
    try:
        result = await collect_weight_diagnostics()
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(_main())
