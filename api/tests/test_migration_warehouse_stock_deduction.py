from __future__ import annotations

import asyncio
import os
import unittest

from alembic import command
from sqlalchemy import text

from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine
from api.tests._migration_test_support import alembic_config, integration_enabled

TEST_DATABASE_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL", "")
_PREVIOUS_REVISION = "20261106_0043"
_COLUMNS = ("warehouse_stock_deducted_at", "warehouse_stock_deducted_by_user_id")


@unittest.skipUnless(integration_enabled(), "Exige APP_ENV=test e POSTGRES_TEST_DATABASE_URL de banco descartavel.")
class WarehouseStockDeductionMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        get_settings.cache_clear()
        get_engine.cache_clear()

    @classmethod
    def tearDownClass(cls):
        command.upgrade(alembic_config(), "head")
        asyncio.run(dispose_engine())
        for key, value in cls.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        get_engine.cache_clear()

    @staticmethod
    async def _columns() -> set[str]:
        async with get_engine().connect() as conn:
            rows = await conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'proposals'")
            )
            return {row[0] for row in rows}

    def test_backfill_marca_so_entregues_e_downgrade_remove_colunas(self):
        command.downgrade(alembic_config(), "base")
        command.upgrade(alembic_config(), _PREVIOUS_REVISION)
        self.assertFalse(set(_COLUMNS) & asyncio.run(self._columns()))

        statuses = {
            "MIG-W-ENT": "ALMOXARIFADO_ENTREGUE",
            "MIG-W-SEP": "SEPARADO",
            "MIG-W-EMS": "EM_SEPARACAO",
            "MIG-W-NUL": None,
        }

        async def seed():
            async with get_engine().begin() as conn:
                for number, status in statuses.items():
                    await conn.execute(
                        text("INSERT INTO proposals (proposal_number, customer_name, warehouse_status) VALUES (:n, 'Cliente', :s)"),
                        {"n": number, "s": status},
                    )

        asyncio.run(seed())
        command.upgrade(alembic_config(), "head")
        self.assertTrue(set(_COLUMNS) <= asyncio.run(self._columns()))

        async def read():
            async with get_engine().connect() as conn:
                rows = await conn.execute(
                    text(
                        "SELECT proposal_number, warehouse_stock_deducted_at, warehouse_stock_deducted_by_user_id "
                        "FROM proposals WHERE proposal_number LIKE 'MIG-W-%'"
                    )
                )
                return {row[0]: (row[1], row[2]) for row in rows}

        result = asyncio.run(read())
        self.assertIsNotNone(result["MIG-W-ENT"][0])
        self.assertIsNone(result["MIG-W-ENT"][1])
        for number in ("MIG-W-SEP", "MIG-W-EMS", "MIG-W-NUL"):
            self.assertEqual(result[number], (None, None), number)

        command.downgrade(alembic_config(), _PREVIOUS_REVISION)
        self.assertFalse(set(_COLUMNS) & asyncio.run(self._columns()))


if __name__ == "__main__":
    unittest.main()
