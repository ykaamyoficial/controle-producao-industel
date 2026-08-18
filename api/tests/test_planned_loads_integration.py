from __future__ import annotations

import asyncio
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
from api.app.modules.auth.permissions import ADMIN_PERMISSION_CODES, GALVANIZATION_VIEW
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


def _proposal_payload(proposal_number: str, items: list[dict] | None = None) -> dict:
    return {
        "proposal_number": proposal_number,
        "customer_name": "Cliente Planejamento",
        "project_name": "Site",
        "purchase_order": "PC1",
        "batch_reference": "L1",
        "proposal_date": "2026-08-01",
        "deadline_date": "2026-08-30",
        "source": "MANUAL",
        "notes": "Criada pela API",
        "items": items or [_item_payload("1")],
    }


def _item_payload(item_number: str, *, quantity: str = "100.0000") -> dict:
    return {
        "item_number": item_number,
        "product_code": "COD",
        "description": "Item de teste",
        "quantity": quantity,
        "unit": "un",
        "unit_weight": "3.5000",
        "total_weight": "7.0000",
        "produce_internally": True,
        "requires_galvanization": True,
    }


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class PlannedLoadsIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV"), "SECRET_KEY": os.environ.get("SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "planned-loads-integration-secret-key-more-than-32"
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
        asyncio.run(self._seed_users())
        self.client = TestClient(create_app())

    async def _seed_users(self):
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE TABLE security_events, auth_sessions, planned_load_history, planned_load_items, "
                    "planned_loads, fiscal_events, fiscal_invoice_items, fiscal_invoices, fiscal_items, fiscal_records, "
                    "expedition_events, expedition_items, galvanization_load_events, galvanization_load_items, "
                    "galvanization_loads, proposal_events, proposal_items, proposals, sync_runs, role_permissions, "
                    "user_roles, users, roles RESTART IDENTITY CASCADE"
                )
            )
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            admin_permissions = (await session.execute(select(Permission).where(Permission.code.in_(ADMIN_PERMISSION_CODES)))).scalars().all()
            admin_role = Role(code="admin", name="Administrador", active=True, system_role=True)
            admin_role.permissions.extend(admin_permissions)
            admin = User(
                username="admin",
                display_name="Administrador",
                password_hash=hash_password("Senha forte planejamento 123"),
                active=True,
                is_superuser=True,
                password_changed_at=utcnow(),
            )
            admin.roles.append(admin_role)
            session.add(admin)

            view_permission = (await session.execute(select(Permission).where(Permission.code == GALVANIZATION_VIEW))).scalar_one()
            viewer_role = Role(code="galvanizacao_view", name="Galvanizacao (somente leitura)", active=True, system_role=False)
            viewer_role.permissions.append(view_permission)
            viewer = User(
                username="viewer",
                display_name="Leitor",
                password_hash=hash_password("Senha forte leitor 123"),
                active=True,
                is_superuser=False,
                password_changed_at=utcnow(),
            )
            viewer.roles.append(viewer_role)
            session.add(viewer)
            await session.commit()

    def _headers(self, username: str, password: str) -> dict:
        login = self.client.post("/api/v1/auth/login", json={"username": username, "password": password})
        self.assertEqual(login.status_code, 200, login.text)
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    def _admin_headers(self) -> dict:
        return self._headers("admin", "Senha forte planejamento 123")

    def _viewer_headers(self) -> dict:
        return self._headers("viewer", "Senha forte leitor 123")

    def _create_proposal_item(self, headers: dict, proposal_number: str, *, quantity: str = "100.0000") -> dict:
        created = self.client.post("/api/v1/proposals", json=_proposal_payload(proposal_number, [_item_payload("1", quantity=quantity)]), headers=headers)
        self.assertEqual(created.status_code, 201, created.text)
        data = created.json()
        return {"proposal_id": data["id"], "proposal_item_id": data["items"][0]["id"]}

    def test_create_read_update_and_manage_items(self):
        headers = self._admin_headers()
        item = self._create_proposal_item(headers, "PLPL0001", quantity="100.0000")

        created = self.client.post(
            "/api/v1/planned-loads",
            json={
                "expected_ship_date": "2026-08-21",
                "carrier_name": "Transportadora X",
                "notes": "Planejamento de teste",
                "items": [{"proposal_item_id": item["proposal_item_id"], "planned_quantity": "60.0000"}],
            },
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.text)
        data = created.json()
        self.assertTrue(data["code"].startswith("PL-"))
        self.assertEqual(data["status"], "Planejamento")
        self.assertEqual(data["version"], 1)
        self.assertEqual(len(data["items"]), 1)
        planned_item = data["items"][0]
        self.assertEqual(planned_item["planned_quantity"], "60.0000")
        self.assertEqual(planned_item["total_quantity"], "100.0000")
        # FASE_PL1: disponibilidade real ainda nao existe - valores neutros,
        # nunca escondidos do contrato.
        self.assertEqual(planned_item["currently_available_quantity"], "0")
        self.assertEqual(planned_item["missing_quantity"], "60.0000")
        self.assertFalse(planned_item["has_divergence"])
        self.assertEqual(planned_item["current_area"], "CONTROLE_GERAL")
        planned_load_id = data["id"]

        fetched = self.client.get(f"/api/v1/planned-loads/{planned_load_id}", headers=headers)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["code"], data["code"])
        self.assertEqual(len(fetched.json()["history"]), 1)
        self.assertEqual(fetched.json()["history"][0]["event_type"], "PLANNED_LOAD_CREATED")

        listed = self.client.get("/api/v1/planned-loads", params={"search": "Transportadora"}, headers=headers)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["total"], 1)

        updated = self.client.patch(
            f"/api/v1/planned-loads/{planned_load_id}",
            json={"version": 1, "carrier_name": "Transportadora Y"},
            headers=headers,
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["carrier_name"], "Transportadora Y")
        self.assertEqual(updated.json()["version"], 2)

        stale = self.client.patch(f"/api/v1/planned-loads/{planned_load_id}", json={"version": 1, "notes": "conflito"}, headers=headers)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["error"]["code"], "PLANNED_LOAD_VERSION_CONFLICT")

        item_id = planned_item["id"]
        item_update = self.client.patch(
            f"/api/v1/planned-loads/{planned_load_id}/items/{item_id}",
            json={"version": 1, "planned_quantity": "80.0000"},
            headers=headers,
        )
        self.assertEqual(item_update.status_code, 200, item_update.text)
        self.assertEqual(item_update.json()["items"][0]["planned_quantity"], "80.0000")

        stale_item = self.client.patch(
            f"/api/v1/planned-loads/{planned_load_id}/items/{item_id}",
            json={"version": 1, "planned_quantity": "10.0000"},
            headers=headers,
        )
        self.assertEqual(stale_item.status_code, 409)
        self.assertEqual(stale_item.json()["error"]["code"], "PLANNED_LOAD_ITEM_VERSION_CONFLICT")

        stale_delete = self.client.delete(f"/api/v1/planned-loads/{planned_load_id}/items/{item_id}", params={"version": 1}, headers=headers)
        self.assertEqual(stale_delete.status_code, 409)
        self.assertEqual(stale_delete.json()["error"]["code"], "PLANNED_LOAD_ITEM_VERSION_CONFLICT")

        deleted = self.client.delete(f"/api/v1/planned-loads/{planned_load_id}/items/{item_id}", params={"version": 2}, headers=headers)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(len(deleted.json()["items"]), 0)

        # Reabicionar o MESMO proposal_item_id apos remocao precisa funcionar
        # (hard delete, nao soft-delete) - senao a UniqueConstraint do banco
        # bloquearia a readicao para sempre.
        readded = self.client.post(
            f"/api/v1/planned-loads/{planned_load_id}/items",
            json={"items": [{"proposal_item_id": item["proposal_item_id"], "planned_quantity": "30.0000"}]},
            headers=headers,
        )
        self.assertEqual(readded.status_code, 200, readded.text)
        self.assertEqual(len(readded.json()["items"]), 1)

        duplicate = self.client.post(
            f"/api/v1/planned-loads/{planned_load_id}/items",
            json={"items": [{"proposal_item_id": item["proposal_item_id"], "planned_quantity": "5.0000"}]},
            headers=headers,
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["error"]["code"], "PLANNED_LOAD_ITEM_DUPLICATED")

    def test_reject_invalid_or_cancelled_proposal_item(self):
        headers = self._admin_headers()

        invalid = self.client.post(
            "/api/v1/planned-loads",
            json={"items": [{"proposal_item_id": 999999, "planned_quantity": "1.0000"}]},
            headers=headers,
        )
        self.assertEqual(invalid.status_code, 409)
        self.assertEqual(invalid.json()["error"]["code"], "PLANNED_LOAD_PROPOSAL_ITEM_INVALID")

        item = self._create_proposal_item(headers, "PLPL0002")
        cancel = self.client.post(f"/api/v1/proposals/{item['proposal_id']}/cancel", json={"version": 1, "reason": "Teste"}, headers=headers)
        self.assertEqual(cancel.status_code, 200, cancel.text)

        blocked = self.client.post(
            "/api/v1/planned-loads",
            json={"items": [{"proposal_item_id": item["proposal_item_id"], "planned_quantity": "1.0000"}]},
            headers=headers,
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["error"]["code"], "PLANNED_LOAD_PROPOSAL_ITEM_INVALID")

    def test_duplicate_item_in_same_request_is_rejected(self):
        headers = self._admin_headers()
        item = self._create_proposal_item(headers, "PLPL0003")
        response = self.client.post(
            "/api/v1/planned-loads",
            json={
                "items": [
                    {"proposal_item_id": item["proposal_item_id"], "planned_quantity": "10.0000"},
                    {"proposal_item_id": item["proposal_item_id"], "planned_quantity": "20.0000"},
                ]
            },
            headers=headers,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "PLANNED_LOAD_ITEM_DUPLICATED")

    def test_view_only_user_cannot_write(self):
        admin_headers = self._admin_headers()
        item = self._create_proposal_item(admin_headers, "PLPL0004")
        created = self.client.post(
            "/api/v1/planned-loads",
            json={"items": [{"proposal_item_id": item["proposal_item_id"], "planned_quantity": "5.0000"}]},
            headers=admin_headers,
        )
        self.assertEqual(created.status_code, 201)
        planned_load_id = created.json()["id"]

        viewer_headers = self._viewer_headers()
        listed = self.client.get("/api/v1/planned-loads", headers=viewer_headers)
        self.assertEqual(listed.status_code, 200)

        blocked_create = self.client.post("/api/v1/planned-loads", json={"items": []}, headers=viewer_headers)
        self.assertEqual(blocked_create.status_code, 403)
        self.assertEqual(blocked_create.json()["error"]["code"], "PERMISSION_DENIED")

        blocked_update = self.client.patch(f"/api/v1/planned-loads/{planned_load_id}", json={"version": 1, "notes": "x"}, headers=viewer_headers)
        self.assertEqual(blocked_update.status_code, 403)


if __name__ == "__main__":
    unittest.main()
