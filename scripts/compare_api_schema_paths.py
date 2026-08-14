from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"


def run_alembic(database_url: str, *args: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env.setdefault("SECRET_KEY", "schema-compare-local-secret-key-32chars")
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=API_DIR, env=env, check=True)


async def snapshot(database_url: str) -> dict[str, Any]:
    engine = create_async_engine(database_url if "+asyncpg" in database_url else database_url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        async with engine.connect() as conn:
            data: dict[str, Any] = {"tables": {}, "revision": None}
            inspector_data = await conn.run_sync(_inspect_schema)
            table_names = inspector_data.pop("__table_names__")
            has_alembic = "alembic_version" in table_names
            if has_alembic:
                data["revision"] = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            for table in sorted(table_names):
                data["tables"][table] = inspector_data[table]
            return data
    finally:
        await engine.dispose()


def _inspect_schema(sync_conn) -> dict[str, Any]:
    inspector = inspect(sync_conn)
    data: dict[str, Any] = {"__table_names__": sorted(inspector.get_table_names())}
    for table in data["__table_names__"]:
        if table.startswith("pg_") or table == "spatial_ref_sys":
            continue
        data[table] = {
            "columns": [
                {
                    "name": column["name"],
                    "type": str(column["type"]),
                    "nullable": column["nullable"],
                    "default": str(column.get("default")),
                }
                for column in inspector.get_columns(table)
            ],
            "pk": inspector.get_pk_constraint(table),
            "foreign_keys": inspector.get_foreign_keys(table),
            "unique_constraints": inspector.get_unique_constraints(table),
            "indexes": inspector.get_indexes(table),
        }
    return data


def normalize(data: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(data, sort_keys=True, default=str))
    for table in normalized["tables"].values():
        for key in ("foreign_keys", "unique_constraints", "indexes"):
            table[key] = sorted(table[key], key=lambda value: json.dumps(value, sort_keys=True))
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description="Compara schema final entre upgrade direto e progressivo.")
    parser.add_argument("--direct-url", required=True)
    parser.add_argument("--progressive-url", required=True)
    parser.add_argument("--output", default=str(ROOT / "reports" / "schema_path_comparison.json"))
    args = parser.parse_args()

    run_alembic(args.direct_url, "downgrade", "base")
    run_alembic(args.direct_url, "upgrade", "head")

    run_alembic(args.progressive_url, "downgrade", "base")
    for revision in (
        "20260720_0001",
        "20260720_0002",
        "20260720_0003",
        "20260720_0004",
        "20260720_0005",
        "20260721_0006",
        "20260721_0007",
        "20260721_0008",
        "20260722_0009",
        "20260727_0010",
        "20260801_0011",
        "20260802_0012",
        "20260803_0013",
        "20260807_0014",
        "20260810_0015",
    ):
        run_alembic(args.progressive_url, "upgrade", revision)

    direct = normalize(asyncio.run(snapshot(args.direct_url)))
    progressive = normalize(asyncio.run(snapshot(args.progressive_url)))
    equivalent = direct == progressive
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"equivalent": equivalent, "direct": direct, "progressive": progressive}, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Schemas equivalentes: {'Sim' if equivalent else 'Nao'}")
    print(f"Relatorio: {output}")
    raise SystemExit(0 if equivalent else 1)


if __name__ == "__main__":
    main()
