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


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class ProposalsIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV"), "SECRET_KEY": os.environ.get("SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "proposal-integration-secret-key-more-than-32"
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
            await conn.execute(text("TRUNCATE TABLE security_events, auth_sessions, fiscal_events, fiscal_invoice_items, fiscal_invoices, fiscal_items, fiscal_records, expedition_events, expedition_items, galvanization_load_events, galvanization_load_items, galvanization_loads, proposal_events, proposal_items, proposals, sync_runs, role_permissions, user_roles, users, roles RESTART IDENTITY CASCADE"))
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            permissions = (await session.execute(select(Permission).where(Permission.code.in_(ADMIN_PERMISSION_CODES)))).scalars().all()
            role = Role(code="admin", name="Administrador", active=True, system_role=True)
            role.permissions.extend(permissions)
            user = User(username="admin", display_name="Administrador", password_hash=hash_password("Senha forte proposta 123"), active=True, is_superuser=True, password_changed_at=utcnow())
            user.roles.append(role)
            session.add(user)
            await session.commit()

    def _headers(self):
        login = self.client.post("/api/v1/auth/login", json={"username": "admin", "password": "Senha forte proposta 123"})
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    def test_create_read_update_cancel_and_audit_official_proposal(self):
        headers = self._headers()
        created = self.client.post("/api/v1/proposals", json=_proposal_payload("CP00001"), headers=headers)
        self.assertEqual(created.status_code, 201)
        data = created.json()
        self.assertEqual(data["legacy_id"], None)
        self.assertEqual(data["current_area"], "CONTROLE_GERAL")
        self.assertEqual(data["current_status"], "AGUARDANDO_LIBERACAO")
        self.assertEqual(data["source"], "MANUAL")
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["items"][0]["description"], "Linha 1\nLinha 2")

        updated = self.client.patch(
            f"/api/v1/proposals/{data['id']}",
            json={"version": data["version"], "customer_name": "Cliente Atualizado", "notes": "Observacao revisada"},
            headers=headers,
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["version"], 2)
        self.assertEqual(updated.json()["customer_name"], "Cliente Atualizado")

        stale = self.client.patch(f"/api/v1/proposals/{data['id']}", json={"version": 1, "customer_name": "Conflito"}, headers=headers)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["error"]["code"], "PROPOSAL_VERSION_CONFLICT")

        released = self.client.post(
            f"/api/v1/proposals/{data['id']}/status",
            json={"version": 2, "to_area": "PRODUCAO", "to_status": "LIBERADO_PRODUCAO", "reason": "Liberacao inicial"},
            headers=headers,
        )
        self.assertEqual(released.status_code, 200)
        self.assertEqual(released.json()["current_area"], "PRODUCAO")
        self.assertEqual(released.json()["current_status"], "LIBERADO_PRODUCAO")

        blocked_edit = self.client.patch(f"/api/v1/proposals/{data['id']}", json={"version": 3, "customer_name": "Bloqueado"}, headers=headers)
        self.assertEqual(blocked_edit.status_code, 409)
        self.assertEqual(blocked_edit.json()["error"]["code"], "PROPOSAL_CANNOT_BE_EDITED")

        cancelled = self.client.post(f"/api/v1/proposals/{data['id']}/cancel", json={"version": 3, "reason": "Teste"}, headers=headers)
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["current_status"], "CANCELADA")
        self.assertTrue(cancelled.json()["is_cancelled"])

        events = asyncio.run(self._proposal_event_count(data["id"]))
        self.assertGreaterEqual(events, 4)

    def test_create_rejects_duplicate_proposal_number_and_financial_fields(self):
        headers = self._headers()
        first = self.client.post("/api/v1/proposals", json=_proposal_payload("CP00002"), headers=headers)
        self.assertEqual(first.status_code, 201)

        duplicate = self.client.post("/api/v1/proposals", json=_proposal_payload("CP00002"), headers=headers)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["error"]["code"], "PROPOSAL_NUMBER_ALREADY_EXISTS")

        payload = _proposal_payload("CP00003")
        payload["valor_total"] = "999.99"
        forbidden = self.client.post("/api/v1/proposals", json=payload, headers=headers)
        self.assertEqual(forbidden.status_code, 422)

    def test_create_requires_items_and_valid_item_values(self):
        headers = self._headers()
        no_items = _proposal_payload("CP00004")
        no_items["items"] = []
        response = self.client.post("/api/v1/proposals", json=no_items, headers=headers)
        self.assertEqual(response.status_code, 422)

        bad_item = _proposal_payload("CP00005")
        bad_item["items"][0]["quantity"] = "0"
        response = self.client.post("/api/v1/proposals", json=bad_item, headers=headers)
        self.assertEqual(response.status_code, 422)

    def test_item_create_update_soft_delete_and_version_conflict(self):
        headers = self._headers()
        proposal = self.client.post("/api/v1/proposals", json=_proposal_payload("CP00006"), headers=headers).json()
        created_item = self.client.post(f"/api/v1/proposals/{proposal['id']}/items", json=_item_payload("2"), headers=headers)
        self.assertEqual(created_item.status_code, 201)
        item = created_item.json()
        self.assertEqual(item["version"], 1)

        updated_item = self.client.patch(f"/api/v1/proposal-items/{item['id']}", json={"version": 1, "description": "Descricao alterada"}, headers=headers)
        self.assertEqual(updated_item.status_code, 200)
        self.assertEqual(updated_item.json()["version"], 2)
        self.assertEqual(updated_item.json()["description"], "Descricao alterada")

        stale = self.client.patch(f"/api/v1/proposal-items/{item['id']}", json={"version": 1, "description": "Conflito"}, headers=headers)
        self.assertEqual(stale.status_code, 409)

        deleted = self.client.delete(f"/api/v1/proposal-items/{item['id']}", headers=headers)
        self.assertEqual(deleted.status_code, 204)
        detail = self.client.get(f"/api/v1/proposal-items/{item['id']}", headers=headers)
        self.assertFalse(detail.json()["active"])

    def test_proposal_pagination_has_stable_id_tiebreaker(self):
        headers = self._headers()
        for index in range(1, 6):
            response = self.client.post("/api/v1/proposals", json=_proposal_payload(f"CP9{index:04d}"), headers=headers)
            self.assertEqual(response.status_code, 201)

        page_one = self.client.get("/api/v1/proposals?limit=2&offset=0&sort_by=proposal_date&sort_dir=asc", headers=headers).json()
        page_two = self.client.get("/api/v1/proposals?limit=2&offset=2&sort_by=proposal_date&sort_dir=asc", headers=headers).json()
        page_three = self.client.get("/api/v1/proposals?limit=2&offset=4&sort_by=proposal_date&sort_dir=asc", headers=headers).json()
        numbers = [item["proposal_number"] for page in (page_one, page_two, page_three) for item in page["items"]]
        self.assertEqual(numbers, ["CP90001", "CP90002", "CP90003", "CP90004", "CP90005"])

    def test_legacy_sync_endpoint_is_disabled(self):
        headers = self._headers()
        response = self.client.post("/api/v1/admin/sync/proposals", json={"proposals": []}, headers=headers)
        self.assertEqual(response.status_code, 404)

    def test_official_production_flow_with_galvanization_and_partial(self):
        headers = self._headers()
        proposal = self.client.post("/api/v1/proposals", json=_proposal_payload("CP01001", [_item_payload("1"), _item_payload("2")]), headers=headers).json()
        released = self._release_to_production(proposal, headers)

        production_list = self.client.get("/api/v1/production/proposals", headers=headers)
        self.assertEqual(production_list.status_code, 200)
        self.assertEqual(production_list.json()["items"][0]["proposal_number"], "CP01001")
        self.assertEqual(production_list.json()["items"][0]["production_status"], "NAO_INICIADO")

        started = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/start", json={"version": released["version"]}, headers=headers)
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.json()["production_status"], "INICIADO")

        stale = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/start", json={"version": released["version"]}, headers=headers)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["error"]["code"], "PROPOSAL_VERSION_CONFLICT")

        first_item = started.json()["items"][0]
        partial = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/complete-items",
            json={"version": started.json()["version"], "item_ids": [first_item["id"]], "observation": "Parcial"},
            headers=headers,
        )
        self.assertEqual(partial.status_code, 200)
        self.assertEqual(partial.json()["production_status"], "FINALIZADO_PARCIAL")
        self.assertEqual(partial.json()["current_area"], "PRODUCAO")
        self.assertEqual(partial.json()["progress"]["pending_items"], 1)

        done = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/complete-items",
            json={"version": partial.json()["version"]},
            headers=headers,
        )
        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.json()["production_status"], "FINALIZADO")
        self.assertEqual(done.json()["current_area"], "GALVANIZACAO")
        self.assertEqual(done.json()["galvanization_status"], "AGUARDANDO_ENVIO")

        events = asyncio.run(self._proposal_event_count(proposal["id"]))
        self.assertGreaterEqual(events, 6)

    def test_official_production_items_endpoint_lists_flat_pending_and_produced_items(self):
        headers = self._headers()
        proposal = self.client.post("/api/v1/proposals", json=_proposal_payload("CP01050", [_item_payload("1"), _item_payload("2")]), headers=headers).json()
        released = self._release_to_production(proposal, headers)
        started = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/start", json={"version": released["version"]}, headers=headers).json()

        pending = self.client.get("/api/v1/production/items", params={"pending": "true", "search": "CP01050"}, headers=headers)
        self.assertEqual(pending.status_code, 200)
        pending_rows = pending.json()["items"]
        self.assertEqual(len(pending_rows), 2)
        self.assertTrue(all(row["proposal_number"] == "CP01050" and row["produced"] is False for row in pending_rows))
        self.assertEqual(pending_rows[0]["proposal_version"], started["version"])

        first_item_id = pending_rows[0]["item_id"]
        completed = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/complete-items",
            json={"version": started["version"], "item_ids": [first_item_id], "observation": "Item unico"},
            headers=headers,
        )
        self.assertEqual(completed.status_code, 200)

        pending_after = self.client.get("/api/v1/production/items", params={"pending": "true", "search": "CP01050"}, headers=headers)
        pending_after_rows = pending_after.json()["items"]
        self.assertEqual(len(pending_after_rows), 1)
        self.assertNotEqual(pending_after_rows[0]["item_id"], first_item_id)

        produced = self.client.get("/api/v1/production/items", params={"pending": "false", "search": "CP01050"}, headers=headers)
        produced_rows = produced.json()["items"]
        self.assertEqual(len(produced_rows), 1)
        self.assertEqual(produced_rows[0]["item_id"], first_item_id)
        self.assertTrue(produced_rows[0]["produced"])

    def test_official_production_without_galvanization_goes_to_expedition(self):
        headers = self._headers()
        payload = _proposal_payload("CP01002", [_item_payload("1", requires_galvanization=False)])
        proposal = self.client.post("/api/v1/proposals", json=payload, headers=headers).json()
        released = self._release_to_production(proposal, headers)
        started = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/start", json={"version": released["version"]}, headers=headers).json()
        done = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/complete-items", json={"version": started["version"]}, headers=headers)

        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.json()["current_area"], "EXPEDICAO")
        self.assertEqual(done.json()["shipping_status"], "EM_SEPARACAO")

    def test_official_production_mixed_items_preserves_item_destination_summary(self):
        headers = self._headers()
        payload = _proposal_payload("CP01003", [_item_payload("1", requires_galvanization=True), _item_payload("2", requires_galvanization=False)])
        proposal = self.client.post("/api/v1/proposals", json=payload, headers=headers).json()
        released = self._release_to_production(proposal, headers)
        started = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/start", json={"version": released["version"]}, headers=headers).json()
        done = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/complete-items", json={"version": started["version"]}, headers=headers)

        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.json()["current_area"], "GALVANIZACAO")
        self.assertEqual(done.json()["progress"]["needs_galvanization_items"], 1)
        self.assertEqual(done.json()["progress"]["no_galvanization_items"], 1)

    def test_official_production_flow_definition_reason_weights_and_undefined_block(self):
        headers = self._headers()
        payload = _proposal_payload("CP01004", [_item_payload("1", produce_internally=None, requires_galvanization=None), _item_payload("2", produce_internally=True, requires_galvanization=False)])
        proposal = self.client.post("/api/v1/proposals", json=payload, headers=headers).json()
        released = self._release_to_production(proposal, headers)
        started = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/start", json={"version": released["version"]}, headers=headers).json()

        blocked = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/complete-items", json={"version": started["version"]}, headers=headers)
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["error"]["code"], "PRODUCTION_ITEM_FLOW_REQUIRED")

        undefined_item = started["items"][0]
        no_reason = self.client.patch(
            f"/api/v1/production/proposals/{proposal['id']}/item-flow",
            json={"version": started["version"], "items": [{"item_id": undefined_item["id"], "version": undefined_item["version"], "produce_internally": False, "requires_galvanization": False}]},
            headers=headers,
        )
        self.assertEqual(no_reason.status_code, 422)

        flow = self.client.patch(
            f"/api/v1/production/proposals/{proposal['id']}/item-flow",
            json={
                "version": started["version"],
                "items": [
                    {
                        "item_id": undefined_item["id"],
                        "version": undefined_item["version"],
                        "produce_internally": False,
                        "non_production_reason": "pronta_entrega",
                        "requires_galvanization": False,
                    }
                ],
            },
            headers=headers,
        )
        self.assertEqual(flow.status_code, 200)
        self.assertEqual(flow.json()["items"][0]["produce_internally"], "NAO")
        self.assertTrue(flow.json()["items"][0]["produced"])

        item = flow.json()["items"][1]
        weights = self.client.patch(
            f"/api/v1/production/proposals/{proposal['id']}/item-weights",
            json={"version": flow.json()["version"], "items": [{"item_id": item["id"], "version": item["version"], "unit_weight": "5.2500"}]},
            headers=headers,
        )
        self.assertEqual(weights.status_code, 200)
        self.assertEqual(weights.json()["items"][1]["unit_weight"], "5.2500")

        done = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/complete-items", json={"version": weights.json()["version"]}, headers=headers)
        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.json()["current_area"], "EXPEDICAO")

    def test_official_galvanization_load_partial_and_total_return(self):
        headers = self._headers()
        first = self._proposal_ready_for_galvanization("CP02001", headers, [_item_payload("1"), _item_payload("2")])
        second = self._proposal_ready_for_galvanization("CP02002", headers, [_item_payload("1")])

        candidates = self.client.get("/api/v1/galvanization/candidates", headers=headers)
        self.assertEqual(candidates.status_code, 200)
        candidate_ids = {item["item_id"] for item in candidates.json()["items"]}
        self.assertTrue({item["id"] for item in first["items"]} <= candidate_ids)

        load = self.client.post(
            "/api/v1/galvanization/loads",
            json={
                "driver_name": "Motorista",
                "expected_return_date": "2026-07-25",
                "items": [
                    {"proposal_item_id": first["items"][0]["id"], "version": first["items"][0]["version"]},
                    {"proposal_item_id": second["items"][0]["id"], "version": second["items"][0]["version"]},
                ],
            },
            headers=headers,
        )
        self.assertEqual(load.status_code, 201)
        self.assertEqual(load.json()["status"], "AGUARDANDO_LIBERACAO")
        self.assertEqual(load.json()["proposal_count"], 2)

        duplicate = self.client.patch(
            f"/api/v1/galvanization/loads/{load.json()['id']}",
            json={
                "version": load.json()["version"],
                "items": [
                    {"proposal_item_id": first["items"][0]["id"]},
                    {"proposal_item_id": first["items"][0]["id"]},
                ],
            },
            headers=headers,
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["error"]["code"], "GALVANIZATION_ITEM_DUPLICATED")

        released = self.client.post(f"/api/v1/galvanization/loads/{load.json()['id']}/release", json={"version": load.json()["version"]}, headers=headers)
        self.assertEqual(released.status_code, 200)
        self.assertEqual(released.json()["status"], "LIBERADA_PARA_ENVIO")

        stale = self.client.post(f"/api/v1/galvanization/loads/{load.json()['id']}/release", json={"version": load.json()["version"]}, headers=headers)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["error"]["code"], "GALVANIZATION_LOAD_VERSION_CONFLICT")

        first_load_item = next(item for item in released.json()["items"] if item["proposal_id"] == first["id"])
        partial = self.client.post(
            f"/api/v1/galvanization/loads/{load.json()['id']}/returns",
            json={"version": released.json()["version"], "items": [{"load_item_id": first_load_item["id"]}], "observation": "retorno parcial"},
            headers=headers,
        )
        self.assertEqual(partial.status_code, 200)
        self.assertEqual(partial.json()["status"], "RETORNO_PARCIAL")
        self.assertEqual(next(item for item in partial.json()["items"] if item["id"] == first_load_item["id"])["status"], "RETORNADO")

        proposal_after_partial = self.client.get(f"/api/v1/proposals/{first['id']}", headers=headers).json()
        self.assertEqual(proposal_after_partial["galvanization_status"], "RETORNOU_PARCIAL")
        self.assertEqual(proposal_after_partial["shipping_status"], "AGUARDANDO_SEPARACAO_PARCIAL")

        total = self.client.post(
            f"/api/v1/galvanization/loads/{load.json()['id']}/returns",
            json={"version": partial.json()["version"], "proposal_ids": [second["id"]]},
            headers=headers,
        )
        self.assertEqual(total.status_code, 200)
        self.assertEqual(total.json()["status"], "RETORNADA_GALVANIZACAO")
        proposal_after_total = self.client.get(f"/api/v1/proposals/{second['id']}", headers=headers).json()
        self.assertEqual(proposal_after_total["current_area"], "EXPEDICAO")
        self.assertEqual(proposal_after_total["shipping_status"], "EM_SEPARACAO")

        closed = self.client.post(f"/api/v1/galvanization/loads/{load.json()['id']}/close", json={"version": total.json()["version"]}, headers=headers)
        self.assertEqual(closed.status_code, 200)
        self.assertIsNotNone(closed.json()["closed_at"])

    def test_official_galvanization_rejects_non_galvanization_item(self):
        headers = self._headers()
        proposal = self._proposal_ready_for_galvanization("CP02003", headers, [_item_payload("1", requires_galvanization=False)])
        response = self.client.post(
            "/api/v1/galvanization/loads",
            json={"driver_name": "Motorista", "items": [{"proposal_item_id": proposal["items"][0]["id"]}]},
            headers=headers,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "GALVANIZATION_ITEM_NOT_ELIGIBLE")

    def test_official_galvanization_load_exceeding_max_weight_capacity_is_blocked(self):
        headers = self._headers()
        proposal = self._proposal_ready_for_galvanization("CP02010", headers, [_item_payload("1")])
        item = proposal["items"][0]

        response = self.client.post(
            "/api/v1/galvanization/loads",
            json={
                "driver_name": "Motorista",
                "max_weight": "5.0000",
                "items": [{"proposal_item_id": item["id"], "version": item["version"]}],
            },
            headers=headers,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "GALVANIZATION_LOAD_INVALID_STATE")

        loads = self.client.get("/api/v1/galvanization/loads", headers=headers)
        self.assertEqual(loads.json()["items"], [])

    def test_official_galvanization_sent_quantity_above_available_balance_is_blocked(self):
        headers = self._headers()
        proposal = self._proposal_ready_for_galvanization("CP02011", headers, [_item_payload("1")])
        item = proposal["items"][0]

        response = self.client.post(
            "/api/v1/galvanization/loads",
            json={
                "driver_name": "Motorista",
                "items": [{"proposal_item_id": item["id"], "version": item["version"], "sent_quantity": "3.0000"}],
            },
            headers=headers,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "GALVANIZATION_ITEM_NOT_ELIGIBLE")

        loads = self.client.get("/api/v1/galvanization/loads", headers=headers)
        self.assertEqual(loads.json()["items"], [])

    def test_official_galvanization_available_balance_deducts_previous_loads(self):
        headers = self._headers()
        proposal = self._proposal_ready_for_galvanization("CP02012", headers, [_item_payload("1")])
        item = proposal["items"][0]

        first_load = self.client.post(
            "/api/v1/galvanization/loads",
            json={
                "driver_name": "Motorista 1",
                "items": [{"proposal_item_id": item["id"], "version": item["version"], "sent_quantity": "1.0000"}],
            },
            headers=headers,
        )
        self.assertEqual(first_load.status_code, 201)
        self.assertEqual(first_load.json()["total_weight"], "3.5000")

        exceeds_remaining_balance = self.client.post(
            "/api/v1/galvanization/loads",
            json={
                "driver_name": "Motorista 2",
                "items": [{"proposal_item_id": item["id"], "sent_quantity": "2.0000"}],
            },
            headers=headers,
        )
        self.assertEqual(exceeds_remaining_balance.status_code, 409)
        self.assertEqual(exceeds_remaining_balance.json()["error"]["code"], "GALVANIZATION_ITEM_NOT_ELIGIBLE")

        second_load = self.client.post(
            "/api/v1/galvanization/loads",
            json={
                "driver_name": "Motorista 2",
                "items": [{"proposal_item_id": item["id"], "sent_quantity": "1.0000"}],
            },
            headers=headers,
        )
        self.assertEqual(second_load.status_code, 201)
        self.assertEqual(second_load.json()["total_weight"], "3.5000")

    def test_official_galvanization_candidates_situation_reflects_sent_to_open_load(self):
        headers = self._headers()
        proposal = self._proposal_ready_for_galvanization("CP02014", headers, [_item_payload("1")])
        item = proposal["items"][0]

        before = self.client.get("/api/v1/galvanization/candidates", params={"search": "CP02014"}, headers=headers)
        self.assertEqual(before.status_code, 200)
        before_row = before.json()["items"][0]
        self.assertEqual(before_row["situation"], "DISPONIVEL")
        self.assertEqual(before_row["sent_quantity"], "0.0000")
        self.assertEqual(before_row["available_quantity"], "2.0000")

        load = self.client.post(
            "/api/v1/galvanization/loads",
            json={
                "driver_name": "Motorista",
                "items": [{"proposal_item_id": item["id"], "version": item["version"], "sent_quantity": "2.0000"}],
            },
            headers=headers,
        )
        self.assertEqual(load.status_code, 201)

        after = self.client.get("/api/v1/galvanization/candidates", params={"search": "CP02014"}, headers=headers)
        after_row = after.json()["items"][0]
        self.assertEqual(after_row["situation"], "EM_GALVANIZACAO")
        self.assertEqual(after_row["sent_quantity"], "2.0000")
        self.assertEqual(after_row["available_quantity"], "0.0000")

        available_only = self.client.get("/api/v1/galvanization/candidates", params={"search": "CP02014", "situation": "DISPONIVEL"}, headers=headers)
        self.assertEqual(available_only.json()["items"], [])

        in_galvanization_only = self.client.get("/api/v1/galvanization/candidates", params={"search": "CP02014", "situation": "EM_GALVANIZACAO"}, headers=headers)
        self.assertEqual(len(in_galvanization_only.json()["items"]), 1)
        self.assertEqual(in_galvanization_only.json()["items"][0]["item_id"], item["id"])

        released = self.client.post(f"/api/v1/galvanization/loads/{load.json()['id']}/release", json={"version": load.json()["version"]}, headers=headers)
        self.assertEqual(released.status_code, 200)
        load_item_id = released.json()["items"][0]["id"]
        partial_return = self.client.post(
            f"/api/v1/galvanization/loads/{load.json()['id']}/returns",
            json={"version": released.json()["version"], "items": [{"load_item_id": load_item_id, "quantity_returned": "1.0000"}]},
            headers=headers,
        )
        self.assertEqual(partial_return.status_code, 200)

        after_partial_return = self.client.get("/api/v1/galvanization/candidates", params={"search": "CP02014"}, headers=headers)
        partial_row = after_partial_return.json()["items"][0]
        self.assertEqual(partial_row["situation"], "EM_GALVANIZACAO", "item ainda nao retornou totalmente, entao segue indisponivel para nova carga")
        self.assertEqual(partial_row["available_quantity"], "0.0000")
        self.assertEqual(partial_row["sent_quantity"], "1.0000", "1 das 2 unidades ja retornou, so 1 deveria seguir marcada como fora")

    def test_official_galvanization_item_not_yet_produced_is_not_eligible(self):
        headers = self._headers()
        proposal = self.client.post("/api/v1/proposals", json=_proposal_payload("CP02013", [_item_payload("1")]), headers=headers).json()
        released = self._release_to_production(proposal, headers)
        started = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/start", json={"version": released["version"]}, headers=headers).json()
        item = started["items"][0]

        response = self.client.post(
            "/api/v1/galvanization/loads",
            json={"driver_name": "Motorista", "items": [{"proposal_item_id": item["id"], "version": item["version"]}]},
            headers=headers,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "GALVANIZATION_ITEM_NOT_ELIGIBLE")

    def test_official_expedition_direct_flow_delivers_only_after_separation(self):
        headers = self._headers()
        proposal = self._proposal_ready_for_expedition("CP03001", headers, [_item_payload("1", requires_galvanization=False)])

        listed = self.client.get("/api/v1/shipping/proposals", headers=headers)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["items"][0]["proposal_number"], "CP03001")

        blocked = self.client.post(f"/api/v1/shipping/proposals/{proposal['id']}/deliver-items", json={"version": proposal["version"]}, headers=headers)
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["error"]["code"], "EXPEDITION_ITEM_NOT_AVAILABLE")

        started = self.client.post(f"/api/v1/shipping/proposals/{proposal['id']}/start-separation", json={"version": proposal["version"]}, headers=headers)
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.json()["shipping_status"], "SEPARACAO_INICIADA")

        separated = self.client.post(f"/api/v1/shipping/proposals/{proposal['id']}/separate-items", json={"version": started.json()["version"]}, headers=headers)
        self.assertEqual(separated.status_code, 200)
        self.assertEqual(separated.json()["shipping_status"], "SEPARADO")

        delivered = self.client.post(f"/api/v1/shipping/proposals/{proposal['id']}/deliver-items", json={"version": separated.json()["version"]}, headers=headers)
        self.assertEqual(delivered.status_code, 200)
        self.assertEqual(delivered.json()["shipping_status"], "ENTREGUE")
        self.assertEqual(delivered.json()["general_status"], "ENTREGUE")

    def test_official_expedition_partial_galvanization_keeps_proposal_open(self):
        headers = self._headers()
        proposal = self._proposal_ready_for_galvanization("CP03002", headers, [_item_payload("1"), _item_payload("2")])
        load = self.client.post(
            "/api/v1/galvanization/loads",
            json={"driver_name": "Motorista", "items": [{"proposal_item_id": proposal["items"][0]["id"]}]},
            headers=headers,
        ).json()
        released = self.client.post(f"/api/v1/galvanization/loads/{load['id']}/release", json={"version": load["version"]}, headers=headers).json()
        returned = self.client.post(f"/api/v1/galvanization/loads/{load['id']}/returns", json={"version": released["version"], "proposal_ids": [proposal["id"]]}, headers=headers)
        self.assertEqual(returned.status_code, 200)

        detail = self.client.get(f"/api/v1/shipping/proposals/{proposal['id']}", headers=headers)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["item_count"], 1)

        started = self.client.post(f"/api/v1/shipping/proposals/{proposal['id']}/start-separation", json={"version": detail.json()["version"]}, headers=headers).json()
        separated = self.client.post(f"/api/v1/shipping/proposals/{proposal['id']}/separate-items", json={"version": started["version"]}, headers=headers).json()
        delivered = self.client.post(f"/api/v1/shipping/proposals/{proposal['id']}/deliver-items", json={"version": separated["version"]}, headers=headers)
        self.assertEqual(delivered.status_code, 200)
        self.assertEqual(delivered.json()["shipping_status"], "ENTREGUE_PARCIAL")
        self.assertEqual(delivered.json()["general_status"], "EM_EXPEDICAO")

    def test_official_expedition_remanagement_returns_source_to_production(self):
        headers = self._headers()
        destination = self.client.post("/api/v1/proposals", json=_proposal_payload("CP03003", [_item_payload("1", requires_galvanization=False)]), headers=headers).json()
        source = self._proposal_ready_for_expedition("CP03004", headers, [_item_payload("1", requires_galvanization=False)])
        source_detail = self.client.get(f"/api/v1/shipping/proposals/{source['id']}", headers=headers).json()
        source_item = source_detail["items"][0]

        remanaged = self.client.post(
            f"/api/v1/shipping/proposals/{destination['id']}/deliver-by-remanagement",
            json={
                "version": destination["version"],
                "source_proposal_id": source["id"],
                "source_version": source_detail["version"],
                "items": [{"proposal_item_id": source_item["proposal_item_id"], "version": source_item["version"]}],
                "reason": "Cliente retirou material de outra proposta",
            },
            headers=headers,
        )
        self.assertEqual(remanaged.status_code, 200)
        self.assertEqual(remanaged.json()["current_status"], "ENTREGUE")

        source_after = self.client.get(f"/api/v1/proposals/{source['id']}", headers=headers).json()
        self.assertEqual(source_after["current_area"], "PRODUCAO")
        self.assertEqual(source_after["production_status"], "ITEM_PENDENTE_FABRICACAO")
        self.assertTrue(source_after["has_production_pending"])

    def test_official_fiscal_partial_total_duplicate_cancel_and_withdrawal(self):
        headers = self._headers()
        proposal = self.client.post("/api/v1/proposals", json=_proposal_payload("CP04001", [_item_payload("1", requires_galvanization=False), _item_payload("2", requires_galvanization=False)]), headers=headers).json()

        fiscal_list = self.client.get("/api/v1/fiscal/records", headers=headers)
        self.assertEqual(fiscal_list.status_code, 200)
        record = next(item for item in fiscal_list.json()["items"] if item["proposal_id"] == proposal["id"])
        self.assertEqual(record["status_fiscal"], "FALTA_EMITIR_NOTA_FISCAL")

        detail = self.client.get(f"/api/v1/fiscal/records/{record['id']}", headers=headers).json()
        first_item = detail["items"][0]
        partial = self.client.post(
            f"/api/v1/fiscal/records/{record['id']}/invoices",
            json={"version": detail["version"], "invoice_number": "NF-04001-A", "items": [{"fiscal_item_id": first_item["id"], "version": first_item["version"]}]},
            headers=headers,
        )
        self.assertEqual(partial.status_code, 201)
        self.assertEqual(partial.json()["status_fiscal"], "NOTA_FISCAL_PARCIAL")
        self.assertEqual(partial.json()["pending_items"], 1)

        stale = self.client.post(
            f"/api/v1/fiscal/records/{record['id']}/invoices",
            json={"version": detail["version"], "invoice_number": "NF-04001-STALE", "items": [{"fiscal_item_id": partial.json()["items"][1]["id"]}]},
            headers=headers,
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["error"]["code"], "FISCAL_VERSION_CONFLICT")

        duplicate = self.client.post(
            f"/api/v1/fiscal/records/{record['id']}/invoices",
            json={"version": partial.json()["version"], "invoice_number": "NF-04001-A", "items": [{"fiscal_item_id": partial.json()["items"][1]["id"]}]},
            headers=headers,
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["error"]["code"], "FISCAL_INVOICE_DUPLICATED")

        completed = self.client.post(
            f"/api/v1/fiscal/records/{record['id']}/invoices",
            json={"version": partial.json()["version"], "invoice_number": "NF-04001-B", "items": [{"fiscal_item_id": partial.json()["items"][1]["id"], "version": partial.json()["items"][1]["version"]}]},
            headers=headers,
        )
        self.assertEqual(completed.status_code, 201)
        self.assertEqual(completed.json()["status_fiscal"], "NOTA_FISCAL_EMITIDA")
        self.assertEqual(completed.json()["pending_items"], 0)

        withdrawn = self.client.post(f"/api/v1/fiscal/records/{record['id']}/withdrawal", json={"version": completed.json()["version"], "observation": "Retirada"}, headers=headers)
        self.assertEqual(withdrawn.status_code, 200)
        self.assertEqual(withdrawn.json()["fiscal_situation"], "NF_RETIRADA_CLIENTE")

        invoice_item_id = partial.json()["invoices"][0]["items"][0]["id"]
        cancelled = self.client.post(f"/api/v1/fiscal/invoice-items/{invoice_item_id}/cancel", json={"version": withdrawn.json()["version"], "reason": "Correcao interna"}, headers=headers)
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["status_fiscal"], "NOTA_FISCAL_PARCIAL")
        self.assertGreaterEqual(len(cancelled.json()["events"]), 4)

    def test_official_fiscal_indicators_and_critical_pending_are_operationally_independent(self):
        headers = self._headers()
        proposal = self._proposal_ready_for_expedition("CP04002", headers, [_item_payload("1", requires_galvanization=False)])
        fiscal_list = self.client.get("/api/v1/fiscal/records", headers=headers).json()
        record = next(item for item in fiscal_list["items"] if item["proposal_id"] == proposal["id"])
        self.assertEqual(record["fiscal_situation"], "DISPONIVEL_PARA_EMISSAO")

        started = self.client.post(f"/api/v1/shipping/proposals/{proposal['id']}/start-separation", json={"version": proposal["version"]}, headers=headers).json()
        separated = self.client.post(f"/api/v1/shipping/proposals/{proposal['id']}/separate-items", json={"version": started["version"]}, headers=headers).json()
        delivered = self.client.post(f"/api/v1/shipping/proposals/{proposal['id']}/deliver-items", json={"version": separated["version"]}, headers=headers)
        self.assertEqual(delivered.status_code, 200)

        rows = self.client.get("/api/v1/fiscal/indicator-rows/pendencia_critica", headers=headers)
        self.assertEqual(rows.status_code, 200)
        self.assertTrue(any(item["proposal_id"] == proposal["id"] for item in rows.json()))
        indicators = self.client.get("/api/v1/fiscal/indicators", headers=headers).json()
        self.assertGreaterEqual(indicators["pendencia_critica"], 1)

    def test_administrative_correction_uses_api_postgresql_state_and_audit(self):
        headers = self._headers()
        proposal = self.client.post("/api/v1/proposals", json=_proposal_payload("CP05001"), headers=headers).json()
        released = self._release_to_production(proposal, headers)

        corrected = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/administrative-correction",
            json={"to_area": "PRODUCAO", "to_status": "INICIADO", "justification": "Ajuste administrativo homologado"},
            headers=headers,
        )
        self.assertEqual(corrected.status_code, 200)
        self.assertEqual(corrected.json()["current_area"], "PRODUCAO")
        self.assertEqual(corrected.json()["current_status"], "INICIADO")
        self.assertEqual(corrected.json()["production_status"], "INICIADO")
        self.assertEqual(corrected.json()["version"], released["version"] + 1)

        repeated = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/administrative-correction",
            json={"to_area": "PRODUCAO", "to_status": "INICIADO", "justification": "Repeticao indevida"},
            headers=headers,
        )
        self.assertEqual(repeated.status_code, 409)

        blank_reason = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/administrative-correction",
            json={"to_area": "PRODUCAO", "to_status": "PARADO", "justification": "   "},
            headers=headers,
        )
        self.assertEqual(blank_reason.status_code, 422)

        invalid_status = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/administrative-correction",
            json={"to_area": "PRODUCAO", "to_status": "STATUS_INVALIDO", "justification": "Teste"},
            headers=headers,
        )
        self.assertEqual(invalid_status.status_code, 409)

        not_found = self.client.post(
            "/api/v1/proposals/999999/administrative-correction",
            json={"to_area": "PRODUCAO", "to_status": "PARADO", "justification": "Teste"},
            headers=headers,
        )
        self.assertEqual(not_found.status_code, 404)

        operator_headers = asyncio.run(self._operator_headers())
        denied = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/administrative-correction",
            json={"to_area": "PRODUCAO", "to_status": "PARADO", "justification": "Sem permissao"},
            headers=operator_headers,
        )
        self.assertEqual(denied.status_code, 403)

        history = self.client.get(f"/api/v1/proposals/{proposal['id']}/history", headers=headers)
        self.assertEqual(history.status_code, 200)
        self.assertTrue(any(row["event_type"] == "PROPOSAL_ADMINISTRATIVE_CORRECTION" for row in history.json()))
        security_events = self.client.get("/api/v1/security-events?limit=20&offset=0", headers=headers)
        self.assertTrue(any(row["event_type"] == "PROPOSAL_ADMINISTRATIVE_CORRECTION" for row in security_events.json()["items"]))

    def _release_to_production(self, proposal: dict, headers: dict) -> dict:
        response = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/status",
            json={"version": proposal["version"], "to_area": "PRODUCAO", "to_status": "LIBERADO_PRODUCAO", "reason": "Liberacao"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def _proposal_ready_for_galvanization(self, number: str, headers: dict, items: list[dict]) -> dict:
        proposal = self.client.post("/api/v1/proposals", json=_proposal_payload(number, items), headers=headers).json()
        released = self._release_to_production(proposal, headers)
        started = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/start", json={"version": released["version"]}, headers=headers).json()
        done = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/complete-items", json={"version": started["version"]}, headers=headers)
        self.assertEqual(done.status_code, 200)
        return done.json()

    def _proposal_ready_for_expedition(self, number: str, headers: dict, items: list[dict]) -> dict:
        proposal = self.client.post("/api/v1/proposals", json=_proposal_payload(number, items), headers=headers).json()
        released = self._release_to_production(proposal, headers)
        started = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/start", json={"version": released["version"]}, headers=headers).json()
        done = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/complete-items", json={"version": started["version"]}, headers=headers)
        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.json()["current_area"], "EXPEDICAO")
        return done.json()

    async def _proposal_event_count(self, proposal_id: int) -> int:
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            result = await session.execute(text("SELECT count(*) FROM proposal_events WHERE proposal_id = :proposal_id").bindparams(proposal_id=proposal_id))
            return int(result.scalar_one())

    async def _operator_headers(self) -> dict:
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            user = User(username="operador", display_name="Operador", password_hash=hash_password("Senha forte operador 123"), active=True, is_superuser=False, password_changed_at=utcnow())
            session.add(user)
            await session.commit()
        login = self.client.post("/api/v1/auth/login", json={"username": "operador", "password": "Senha forte operador 123"})
        return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _proposal_payload(proposal_number: str, items: list[dict] | None = None) -> dict:
    return {
        "proposal_number": proposal_number,
        "customer_name": "Cliente",
        "project_name": "Site",
        "purchase_order": "PC1",
        "batch_reference": "L1",
        "proposal_date": "2026-07-20",
        "deadline_date": "2026-07-30",
        "source": "MANUAL",
        "notes": "Criada pela API",
        "items": items or [_item_payload("1")],
    }


def _item_payload(item_number: str, *, produce_internally=True, requires_galvanization=True) -> dict:
    return {
        "item_number": item_number,
        "product_code": "COD",
        "description": "Linha 1\nLinha 2",
        "quantity": "2.0000",
        "unit": "un",
        "unit_weight": "3.5000",
        "total_weight": "7.0000",
        "produce_internally": produce_internally,
        "requires_galvanization": requires_galvanization,
    }


if __name__ == "__main__":
    unittest.main()
