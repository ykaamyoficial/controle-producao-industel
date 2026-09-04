from __future__ import annotations

import asyncio
import hashlib
import os
import unittest
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.main import create_app
from api.app.modules.auth.models import Permission, Role, User
from api.app.modules.auth.permissions import ADMIN_PERMISSION_CODES
from api.app.modules.auth.security import hash_password
from api.app.modules.auth.tokens import utcnow


ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "api"
TEST_DATABASE_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL", "")


def _database_name(url: str) -> str:
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    return parsed.path.lstrip("/")


def _integration_enabled() -> bool:
    return bool(TEST_DATABASE_URL) and os.environ.get("APP_ENV") == "test" and "test" in _database_name(TEST_DATABASE_URL).lower()


def _alembic_config() -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    return config


def _hash(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class LegacySyncIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV"), "SECRET_KEY": os.environ.get("SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "legacy-sync-integration-secret-key-more-than-32"
        get_settings.cache_clear()
        get_engine.cache_clear()
        command.downgrade(_alembic_config(), "base")
        command.upgrade(_alembic_config(), "head")

    @classmethod
    def tearDownClass(cls):
        command.upgrade(_alembic_config(), "head")
        asyncio.run(dispose_engine())
        for key, value in cls.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        get_engine.cache_clear()

    def setUp(self):
        asyncio.run(self._seed_admin())
        self.client = TestClient(create_app())

    async def _seed_admin(self):
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE TABLE security_events, auth_sessions, fiscal_events, fiscal_invoice_items, fiscal_invoices, "
                    "fiscal_items, fiscal_records, expedition_events, expedition_items, galvanization_load_events, "
                    "galvanization_load_items, galvanization_loads, proposal_events, proposal_items, proposals, sync_runs, "
                    "role_permissions, user_roles, users, roles RESTART IDENTITY CASCADE"
                )
            )
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            permissions = (await session.execute(select(Permission).where(Permission.code.in_(ADMIN_PERMISSION_CODES)))).scalars().all()
            role = Role(code="admin", name="Administrador", active=True, system_role=True)
            role.permissions.extend(permissions)
            user = User(username="admin", display_name="Administrador", password_hash=hash_password("Senha forte legado 123"), active=True, is_superuser=True, password_changed_at=utcnow())
            user.roles.append(role)
            session.add(user)
            await session.commit()

    def _headers(self):
        login = self.client.post("/api/v1/auth/login", json={"username": "admin", "password": "Senha forte legado 123"})
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    async def _operator_headers(self) -> dict:
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            user = User(username="operador_legado", display_name="Operador", password_hash=hash_password("Senha forte operador 123"), active=True, is_superuser=False, password_changed_at=utcnow())
            session.add(user)
            await session.commit()
        login = self.client.post("/api/v1/auth/login", json={"username": "operador_legado", "password": "Senha forte operador 123"})
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    def _sync_proposal(self, headers, *, legacy_id: int, proposal_number: str) -> int:
        payload = {
            "source_identifier": "legacy.db",
            "dry_run": False,
            "batch_number": 1,
            "batch_total": 1,
            "proposals": [
                {
                    "legacy_id": legacy_id,
                    "proposal_number": proposal_number,
                    "customer_name": "Cliente Legado",
                    "current_area": "GALVANIZACAO",
                    "current_status": "RETORNOU_GALVANIZACAO",
                    "source": "sqlite",
                    "source_hash": _hash(f"proposal-{legacy_id}"),
                    "items": [
                        {
                            "legacy_id": legacy_id * 10 + 1,
                            "item_number": "1",
                            "description": "Item legado de teste",
                            "quantity": "2.0000",
                            "unit_weight": "3.5000",
                            "total_weight": "7.0000",
                            "produce_internally": "sim",
                            "requires_galvanization": "sim",
                            "produced": True,
                            "galvanized": True,
                            "delivered": True,
                            "delivered_at": "2026-08-01T10:00:00",
                            "source_hash": _hash(f"item-{legacy_id}-1"),
                        }
                    ],
                }
            ],
        }
        response = self.client.post("/api/v1/admin/sync/proposals", json=payload, headers=headers)
        self.assertEqual(response.status_code, 200)
        detail = self.client.get(f"/api/v1/proposals?proposal_number={proposal_number}", headers=headers).json()
        return detail["items"][0]["id"], legacy_id * 10 + 1

    def test_galvanization_sync_requires_superuser(self):
        headers = asyncio.run(self._operator_headers())
        response = self.client.post("/api/v1/admin/sync/galvanization", json=_galvanization_batch_payload([]), headers=headers)
        self.assertEqual(response.status_code, 403)

    def test_galvanization_sync_creates_and_dedups(self):
        headers = self._headers()
        self._sync_proposal(headers, legacy_id=8001, proposal_number="CPGALV01")
        payload = _galvanization_batch_payload([_galvanization_load_payload(legacy_id=9001, item_legacy_id=80011)])

        first = self.client.post("/api/v1/admin/sync/galvanization", json=payload, headers=headers)
        self.assertEqual(first.status_code, 200)
        first_body = first.json()
        self.assertEqual(first_body["created"], 1)
        self.assertEqual(first_body["item_created"], 1)
        self.assertEqual(first_body["rejected"], 0)
        self.assertEqual(first_body["errors"], [])

        second = self.client.post("/api/v1/admin/sync/galvanization", json=payload, headers=headers)
        self.assertEqual(second.status_code, 200)
        second_body = second.json()
        self.assertEqual(second_body["created"], 0)
        self.assertEqual(second_body["updated"], 1)

    def test_galvanization_sync_reports_unresolvable_item(self):
        headers = self._headers()
        payload = _galvanization_batch_payload([_galvanization_load_payload(legacy_id=9002, item_legacy_id=999999)])
        response = self.client.post("/api/v1/admin/sync/galvanization", json=payload, headers=headers)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["created"], 1)
        self.assertEqual(body["item_created"], 0)
        self.assertTrue(body["errors"])

    def test_fiscal_sync_creates_record_item_and_invoice(self):
        headers = self._headers()
        _proposal_id, item_legacy_id = self._sync_proposal(headers, legacy_id=8002, proposal_number="CPFISCAL01")
        payload = {
            "source_identifier": "legacy.db",
            "dry_run": False,
            "batch_number": 1,
            "batch_total": 1,
            "records": [
                {
                    "legacy_id": 7001,
                    "proposal_legacy_id": 8002,
                    "status_fiscal": "NOTA_FISCAL_EMITIDA",
                    "fiscal_situation": "NF_EMITIDA",
                    "entry_date": "2026-07-01",
                    "source_hash": _hash("fiscal-record-7001"),
                    "items": [
                        {
                            "proposal_item_legacy_id": item_legacy_id,
                            "total_quantity": "2.0000",
                            "billed_quantity": "2.0000",
                            "billed_weight": "7.0000",
                            "status": "FATURADO",
                        }
                    ],
                    "invoices": [
                        {
                            "legacy_id": 6001,
                            "invoice_number": "NF-0001",
                            "issued_at": "2026-07-02T10:00:00",
                            "emission_type": "TOTAL",
                            "source": "MANUAL",
                            "items": [{"proposal_item_legacy_id": item_legacy_id, "quantity": "2.0000", "weight": "7.0000"}],
                        }
                    ],
                }
            ],
        }
        first = self.client.post("/api/v1/admin/sync/fiscal", json=payload, headers=headers)
        self.assertEqual(first.status_code, 200)
        first_body = first.json()
        self.assertEqual(first_body["created"], 1)
        self.assertEqual(first_body["item_created"], 1)
        self.assertEqual(first_body["errors"], [])

        second = self.client.post("/api/v1/admin/sync/fiscal", json=payload, headers=headers)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["updated"], 1)

    def test_users_sync_creates_with_permissions_and_skips_admin_collision(self):
        headers = self._headers()
        payload = {
            "source_identifier": "legacy.db",
            "dry_run": False,
            "batch_number": 1,
            "batch_total": 1,
            "default_password": "2026",
            "users": [
                {
                    "legacy_id": 501,
                    "username": "fiscal_legado",
                    "display_name": "Usuario Fiscal Legado",
                    "active": True,
                    "is_superuser": False,
                    "permission_codes": ["fiscal.view", "fiscal.register_emission"],
                    "source_hash": _hash("user-501"),
                }
            ],
        }
        first = self.client.post("/api/v1/users/admin/sync", json=payload, headers=headers)
        self.assertEqual(first.status_code, 200)
        first_body = first.json()
        self.assertEqual(first_body["created"], 1)

        listed = self.client.get("/api/v1/users?limit=200", headers=headers).json()
        created_user = next(item for item in listed["items"] if item["username"] == "fiscal_legado")
        self.assertTrue(created_user["active"])

        second = self.client.post("/api/v1/users/admin/sync", json=payload, headers=headers)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["unchanged"], 1)

    def test_users_sync_requires_superuser(self):
        headers = asyncio.run(self._operator_headers())
        payload = {"source_identifier": "legacy.db", "default_password": "2026", "users": []}
        response = self.client.post("/api/v1/users/admin/sync", json=payload, headers=headers)
        self.assertEqual(response.status_code, 403)

    def test_expedition_backfill_closes_delivered_items(self):
        headers = self._headers()
        self._sync_proposal(headers, legacy_id=8003, proposal_number="CPEXPED01")

        response = self.client.post("/api/v1/admin/sync/expedition-backfill", json={}, headers=headers)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreaterEqual(body["created"], 1)

        second = self.client.post("/api/v1/admin/sync/expedition-backfill", json={}, headers=headers)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["created"], 0)


def _galvanization_batch_payload(loads: list[dict]) -> dict:
    return {
        "source_identifier": "legacy.db",
        "dry_run": False,
        "batch_number": 1,
        "batch_total": 1,
        "loads": loads,
    }


def _galvanization_load_payload(*, legacy_id: int, item_legacy_id: int) -> dict:
    return {
        "legacy_id": legacy_id,
        "driver_name": "Motorista Legado",
        "max_weight": "1000.0000",
        "total_weight": "7.0000",
        "status": "RETORNADA_GALVANIZACAO",
        "sent_at": "2026-07-01T08:00:00",
        "returned_at": "2026-07-05T08:00:00",
        "closed_at": "2026-07-05T08:00:00",
        "source_hash": _hash(f"load-{legacy_id}"),
        "items": [
            {
                "proposal_item_legacy_id": item_legacy_id,
                "sent_quantity": "2.0000",
                "returned_quantity": "2.0000",
                "unit_weight": "3.5000",
                "sent_weight": "7.0000",
                "returned_weight": "7.0000",
                "status": "RETORNADO",
                "returned_at": "2026-07-05T08:00:00",
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
