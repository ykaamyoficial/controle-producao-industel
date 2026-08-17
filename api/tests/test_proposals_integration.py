from __future__ import annotations

import asyncio
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, patch
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
        self.assertEqual(cancelled.json()["cancellation_reason"], "Teste")
        self.assertIsNotNone(cancelled.json()["cancelled_at"])
        self.assertIsNotNone(cancelled.json()["cancelled_by"])

        events = asyncio.run(self._proposal_event_count(data["id"]))
        self.assertGreaterEqual(events, 4)

    def test_cancel_is_terminal_preserves_production_and_disappears_from_operational_queues(self):
        headers = self._headers()
        proposal = self.client.post("/api/v1/proposals", json=_proposal_payload("CP-CANCEL-001", [_item_payload("1"), _item_payload("2")]), headers=headers).json()
        released = self._release_to_production(proposal, headers)
        started = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/start", json={"version": released["version"]}, headers=headers).json()
        first_item = started["items"][0]
        partial = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/complete-items",
            json={"version": started["version"], "item_ids": [first_item["id"]]},
            headers=headers,
        ).json()

        cancelled = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/cancel",
            json={"version": partial["version"], "reason": "Cliente encerrou o pedido"},
            headers=headers,
        )
        self.assertEqual(cancelled.status_code, 200)
        body = cancelled.json()
        self.assertTrue(next(item for item in body["items"] if item["id"] == first_item["id"])["produced"])

        blocked = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/complete-items",
            json={"version": body["version"]},
            headers=headers,
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["error"]["code"], "PROPOSAL_CANCELLED_TERMINAL")

        for operation, payload in (
            ("start", {"version": body["version"]}),
            ("pause", {"version": body["version"], "reason": "Tentativa apos cancelamento"}),
            ("resume", {"version": body["version"]}),
        ):
            with self.subTest(operation=operation):
                cancelled_operation = self.client.post(
                    f"/api/v1/production/proposals/{proposal['id']}/{operation}",
                    json=payload,
                    headers=headers,
                )
                self.assertEqual(cancelled_operation.status_code, 409)
                self.assertEqual(cancelled_operation.json()["error"]["code"], "PROPOSAL_CANCELLED_TERMINAL")

        admin = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/administrative-correction",
            json={
                "expected_version": body["version"],
                "to_area": "PRODUCAO",
                "to_status": "INICIADO",
                "reason": "Tentativa de reativacao",
                "idempotency_key": "cancelled-admin-correction-0001",
            },
            headers=headers,
        )
        self.assertEqual(admin.status_code, 409)
        self.assertEqual(admin.json()["error"]["code"], "PROPOSAL_CANCELLED_TERMINAL")

        general = self.client.get(f"/api/v1/proposals/{proposal['id']}", headers=headers)
        production = self.client.get("/api/v1/production/proposals", params={"search": "CP-CANCEL-001"}, headers=headers)
        expedition = self.client.get("/api/v1/shipping/proposals", params={"search": "CP-CANCEL-001"}, headers=headers)
        fiscal = self.client.get("/api/v1/fiscal/records", params={"search": "CP-CANCEL-001"}, headers=headers)
        self.assertEqual(general.status_code, 200)
        self.assertEqual(production.json()["total"], 0)
        self.assertEqual(expedition.json()["total"], 0)
        self.assertEqual(fiscal.json()["total"], 0)

        # O item 1 ja tinha sido separado para uma filha parcial
        # (CP-CANCEL-001-1) antes do cancelamento, ja que o item 2 ainda
        # estava pendente (Secao de hierarquia parcial). Cancelar a MAE nao
        # cancela em cascata uma filha ja separada e ativa - por isso o item
        # 1 continua elegivel para carga sob a proposta filha, mesmo com a
        # mae terminal. _proposal_operational_clause() ainda protege a mae
        # em si (ela nao aparece mais como candidata).
        galvanization_candidates = self.client.get(
            "/api/v1/galvanization/candidates", params={"search": "CP-CANCEL-001"}, headers=headers
        )
        self.assertEqual(galvanization_candidates.json()["total"], 1)
        self.assertEqual(galvanization_candidates.json()["items"][0]["proposal_number"], "CP-CANCEL-001-1")

    def test_cancel_requires_reason_and_rejects_fully_delivered_proposal(self):
        headers = self._headers()
        proposal = self.client.post("/api/v1/proposals", json=_proposal_payload("CP-CANCEL-002"), headers=headers).json()
        missing = self.client.post(f"/api/v1/proposals/{proposal['id']}/cancel", json={"version": proposal["version"]}, headers=headers)
        blank = self.client.post(f"/api/v1/proposals/{proposal['id']}/cancel", json={"version": proposal["version"], "reason": "   "}, headers=headers)
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(blank.status_code, 422)

        delivered = self._proposal_ready_for_expedition("CP-CANCEL-003", headers, [_item_payload("1", requires_galvanization=False)])
        started = self.client.post(f"/api/v1/shipping/proposals/{delivered['id']}/start-separation", json={"version": delivered["version"]}, headers=headers).json()
        separated = self.client.post(f"/api/v1/shipping/proposals/{delivered['id']}/separate-items", json={"version": started["version"], "items": []}, headers=headers).json()
        completed = self.client.post(f"/api/v1/shipping/proposals/{delivered['id']}/deliver-items", json={"version": separated["version"], "items": []}, headers=headers).json()
        rejected = self.client.post(f"/api/v1/proposals/{delivered['id']}/cancel", json={"version": completed["version"], "reason": "Sem estorno"}, headers=headers)
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.json()["error"]["code"], "PROPOSAL_CANNOT_BE_CANCELLED")

    def test_galvanization_return_preserves_cancelled_terminal_state_and_load_history(self):
        headers = self._headers()
        proposal = self._proposal_ready_for_galvanization("CP-CANCEL-GALV", headers, [_item_payload("1")])
        item = proposal["items"][0]
        load = self.client.post(
            "/api/v1/galvanization/loads",
            json={"driver_name": "Motorista", "items": [{"proposal_item_id": item["id"], "sent_quantity": "2.0000"}]},
            headers=headers,
        ).json()
        released = self.client.post(f"/api/v1/galvanization/loads/{load['id']}/release", json={"version": load["version"]}, headers=headers).json()
        current = self.client.get(f"/api/v1/proposals/{proposal['id']}", headers=headers).json()
        cancelled = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/cancel",
            json={"version": current["version"], "reason": "Cancelada durante transporte"},
            headers=headers,
        ).json()

        returned = self.client.post(
            f"/api/v1/galvanization/loads/{load['id']}/returns",
            json={"version": released["version"], "proposal_ids": [proposal["id"]], "observation": "Retorno fisico"},
            headers=headers,
        )
        self.assertEqual(returned.status_code, 200)
        self.assertEqual(returned.json()["items"][0]["returned_quantity"], "2.0000")
        after = self.client.get(f"/api/v1/proposals/{proposal['id']}", headers=headers).json()
        self.assertEqual(after["current_status"], "CANCELADA")
        self.assertEqual(after["current_area"], "CONTROLE_GERAL")
        self.assertEqual(after["version"], cancelled["version"])
        shipping = self.client.get("/api/v1/shipping/proposals", params={"search": "CP-CANCEL-GALV"}, headers=headers)
        self.assertEqual(shipping.json()["total"], 0)

    def test_cancelled_proposal_is_removed_from_fiscal_and_cannot_emit_invoice(self):
        headers = self._headers()
        proposal = self.client.post("/api/v1/proposals", json=_proposal_payload("CP-CANCEL-FISCAL"), headers=headers).json()
        fiscal_before = self.client.get("/api/v1/fiscal/records", params={"search": "CP-CANCEL-FISCAL"}, headers=headers).json()
        record = fiscal_before["items"][0]
        detail = self.client.get(f"/api/v1/fiscal/records/{record['id']}", headers=headers).json()
        cancelled = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/cancel",
            json={"version": proposal["version"], "reason": "Cancelamento antes da emissao"},
            headers=headers,
        )
        self.assertEqual(cancelled.status_code, 200)

        blocked = self.client.post(
            f"/api/v1/fiscal/records/{record['id']}/invoices",
            json={"version": detail["version"], "invoice_number": "NF-BLOCKED", "items": []},
            headers=headers,
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["error"]["code"], "PROPOSAL_CANCELLED_TERMINAL")
        fiscal_after = self.client.get("/api/v1/fiscal/records", params={"search": "CP-CANCEL-FISCAL"}, headers=headers)
        self.assertEqual(fiscal_after.json()["total"], 0)

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

    def test_item_without_weight_is_pending_never_zero_and_can_enter_production(self):
        headers = self._headers()
        payload_no_weight = _item_payload("1")
        del payload_no_weight["unit_weight"]
        del payload_no_weight["total_weight"]
        proposal = self.client.post("/api/v1/proposals", json=_proposal_payload("CP00050", [payload_no_weight]), headers=headers).json()
        item = proposal["items"][0]
        self.assertIsNone(item["unit_weight"])
        self.assertIsNone(item["total_weight"])
        self.assertEqual(item["weight_source"], "NONE")
        self.assertEqual(item["weight_status"], "PENDING")

        released = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/status",
            json={"version": proposal["version"], "to_area": "PRODUCAO", "to_status": "LIBERADO_PRODUCAO", "reason": "Tentativa"},
            headers=headers,
        )
        self.assertEqual(released.status_code, 200)
        self.assertEqual(released.json()["current_area"], "PRODUCAO")

    def test_item_manual_weight_is_respected_and_total_is_deterministic(self):
        headers = self._headers()
        payload = _item_payload("1")
        payload["quantity"] = "3.0000"
        payload["unit_weight"] = "2.5000"
        payload["total_weight"] = "999.0000"  # deve ser ignorado: total sempre recalculado de qtd x peso unit.
        proposal = self.client.post("/api/v1/proposals", json=_proposal_payload("CP00051", [payload]), headers=headers).json()
        item = proposal["items"][0]
        self.assertEqual(item["unit_weight"], "2.5000")
        self.assertEqual(item["total_weight"], "7.5000")
        self.assertEqual(item["weight_source"], "MANUAL")
        self.assertEqual(item["weight_status"], "MANUAL")

        released = self._release_to_production(proposal, headers)
        self.assertEqual(released["current_area"], "PRODUCAO")

    def test_item_code_change_invalidates_previous_manual_weight(self):
        headers = self._headers()
        proposal = self.client.post("/api/v1/proposals", json=_proposal_payload("CP00052"), headers=headers).json()
        item = proposal["items"][0]
        self.assertEqual(item["weight_source"], "MANUAL")

        updated = self.client.patch(
            f"/api/v1/proposal-items/{item['id']}",
            json={"version": item["version"], "product_code": "OUTRO-CODIGO"},
            headers=headers,
        )
        self.assertEqual(updated.status_code, 200)
        body = updated.json()
        self.assertEqual(body["product_code"], "OUTRO-CODIGO")
        # sem cache local nem pedido Nomus vinculado para OUTRO-CODIGO: peso anterior nao sobrevive a troca de codigo.
        self.assertIsNone(body["unit_weight"])
        self.assertEqual(body["weight_source"], "NONE")
        self.assertEqual(body["weight_status"], "PENDING")

    def test_item_quantity_change_recomputes_total_without_new_resolution(self):
        headers = self._headers()
        proposal = self.client.post("/api/v1/proposals", json=_proposal_payload("CP00053"), headers=headers).json()
        item = proposal["items"][0]
        self.assertEqual(item["unit_weight"], "3.5000")

        updated = self.client.patch(
            f"/api/v1/proposal-items/{item['id']}",
            json={"version": item["version"], "quantity": "5.0000"},
            headers=headers,
        )
        self.assertEqual(updated.status_code, 200)
        body = updated.json()
        self.assertEqual(body["unit_weight"], "3.5000")
        self.assertEqual(body["total_weight"], "17.5000")
        self.assertEqual(body["weight_source"], "MANUAL")

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

        # O item ja produzido deve aparecer na fila de galvanizacao mesmo com
        # a proposta ainda presa em PRODUCAO (irmao ainda pendente) -
        # elegibilidade e por item, nao por area agregada da proposta.
        candidates_while_partial = self.client.get(
            "/api/v1/galvanization/candidates", params={"search": "CP01001"}, headers=headers
        )
        self.assertEqual(candidates_while_partial.status_code, 200)
        candidate_items = candidates_while_partial.json()["items"]
        self.assertEqual(len(candidate_items), 1)
        self.assertEqual(candidate_items[0]["item_id"], first_item["id"])

        # Regressao: montar uma carga (mesmo rascunho) com o item ja
        # produzido nao pode "arrancar" a proposta inteira de PRODUCAO
        # enquanto o item 2 ainda estiver pendente - senao nenhum endpoint
        # de producao aceitaria mais essa proposta (inclusive o
        # complete-items do item 2, logo abaixo).
        produced_item_version = next(
            item["version"] for item in partial.json()["items"] if item["id"] == first_item["id"]
        )
        draft_load = self.client.post(
            "/api/v1/galvanization/loads",
            json={
                "driver_name": "Motorista",
                "expected_return_date": "2026-08-20",
                "items": [{"proposal_item_id": first_item["id"], "version": produced_item_version}],
            },
            headers=headers,
        )
        self.assertEqual(draft_load.status_code, 201)

        # Item 1 ja foi separado para uma filha parcial (CP01001-1) desde a
        # conclusao acima (item 2 ainda pendente) - o rascunho de carga
        # afeta o galvanization_status da FILHA, nunca o da mae (que so
        # carrega o item 2, sem nenhuma relacao com galvanizacao ainda).
        proposal_after_draft_load = self.client.get(f"/api/v1/proposals/{proposal['id']}", headers=headers).json()
        self.assertEqual(proposal_after_draft_load["current_area"], "PRODUCAO")
        child_id = next(iter(asyncio.run(self._active_child_ids(proposal["id"]))))
        child_after_draft_load = self.client.get(f"/api/v1/proposals/{child_id}", headers=headers).json()
        self.assertEqual(child_after_draft_load["proposal_number"], "CP01001-1")
        self.assertEqual(child_after_draft_load["galvanization_status"], "EM_CARGA")

        done = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/complete-items",
            json={"version": proposal_after_draft_load["version"]},
            headers=headers,
        )
        self.assertEqual(done.status_code, 200)
        # Item 2 completa a producao da mae: como ja existe uma filha
        # anterior (CP01001-1), o item 2 tambem sai para uma filha propria
        # (CP01001-2) e a mae, sem mais nenhum item pendente, "morre
        # operacionalmente" e volta a CONTROLE_GERAL como referencia
        # consolidada (Secao de hierarquia parcial).
        self.assertEqual(done.json()["production_status"], "FINALIZADO")
        self.assertEqual(done.json()["current_area"], "CONTROLE_GERAL")
        second_child_id = next(
            iter(set(asyncio.run(self._active_child_ids(proposal["id"]))) - {child_id})
        )
        second_child = self.client.get(f"/api/v1/proposals/{second_child_id}", headers=headers).json()
        self.assertEqual(second_child["proposal_number"], "CP01001-2")
        self.assertEqual(second_child["current_area"], "GALVANIZACAO")
        self.assertEqual(second_child["galvanization_status"], "AGUARDANDO_ENVIO")

        events = asyncio.run(self._proposal_event_count(proposal["id"]))
        self.assertGreaterEqual(events, 6)

    def test_production_pause_resume_preserves_data_actions_history_and_audit(self):
        headers = self._headers()
        proposal = self.client.post(
            "/api/v1/proposals",
            json=_proposal_payload("CP-PAUSE-001", [_item_payload("1", requires_galvanization=False)]),
            headers=headers,
        ).json()
        released = self._release_to_production(proposal, headers)

        waiting_actions = self.client.get(
            f"/api/v1/production/proposals/{proposal['id']}", headers=headers
        ).json()["actions"]
        waiting_ids = {action["id"] for action in waiting_actions if action.get("enabled", True)}
        self.assertIn("START_PRODUCTION", waiting_ids)
        self.assertNotIn("PAUSE_PRODUCTION", waiting_ids)
        self.assertNotIn("RESUME_PRODUCTION", waiting_ids)
        self.assertNotIn("COMPLETE_ITEMS", waiting_ids)

        pause_before_start = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/pause",
            json={"version": released["version"], "reason": "Pausa invalida antes do inicio"},
            headers=headers,
        )
        self.assertEqual(pause_before_start.status_code, 409)

        started_response = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/start",
            json={"version": released["version"], "observation": "Inicio normal"},
            headers=headers,
        )
        self.assertEqual(started_response.status_code, 200, started_response.text)
        started = started_response.json()
        started_action_ids = {action["id"] for action in started["actions"] if action.get("enabled", True)}
        self.assertIn("PAUSE_PRODUCTION", started_action_ids)
        self.assertIn("COMPLETE_ITEMS", started_action_ids)
        self.assertNotIn("START_PRODUCTION", started_action_ids)
        self.assertNotIn("RESUME_PRODUCTION", started_action_ids)

        blank_pause = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/pause",
            json={"version": started["version"], "reason": "   "},
            headers=headers,
        )
        self.assertEqual(blank_pause.status_code, 422)

        item_before = started["items"][0]
        protected_item_fields = {
            key: item_before.get(key)
            for key in (
                "quantity",
                "unit_weight",
                "total_weight",
                "produced",
                "galvanized",
                "delivered",
                "produce_internally",
                "requires_galvanization",
                "version",
            )
        }
        protected_proposal_fields = {
            key: started.get(key)
            for key in ("current_area", "general_status", "galvanization_status", "shipping_status", "warehouse_status")
        }
        progress_before = {key: value for key, value in started["progress"].items() if key != "summary_status"}

        paused_response = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/pause",
            json={"version": started["version"], "reason": "Aguardando materia-prima"},
            headers=headers,
        )
        self.assertEqual(paused_response.status_code, 200, paused_response.text)
        paused = paused_response.json()
        self.assertEqual(paused["production_status"], "PARADO")
        self.assertEqual(paused["current_area"], "PRODUCAO")
        self.assertEqual(paused["current_status"], "PARADO")
        self.assertEqual(
            {key: paused.get(key) for key in protected_proposal_fields},
            protected_proposal_fields,
        )
        self.assertEqual(
            {key: paused["items"][0].get(key) for key in protected_item_fields},
            protected_item_fields,
        )
        self.assertEqual(
            {key: value for key, value in paused["progress"].items() if key != "summary_status"},
            progress_before,
        )

        paused_action_ids = {action["id"] for action in paused["actions"] if action.get("enabled", True)}
        self.assertIn("RESUME_PRODUCTION", paused_action_ids)
        self.assertNotIn("START_PRODUCTION", paused_action_ids)
        self.assertNotIn("PAUSE_PRODUCTION", paused_action_ids)
        self.assertNotIn("COMPLETE_ITEMS", paused_action_ids)

        paused_list = self.client.get(
            "/api/v1/production/proposals", params={"search": "CP-PAUSE-001", "status": "PARADO"}, headers=headers
        )
        self.assertEqual(paused_list.status_code, 200)
        self.assertEqual(paused_list.json()["total"], 1)

        complete_while_paused = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/complete-items",
            json={"version": paused["version"]},
            headers=headers,
        )
        self.assertEqual(complete_while_paused.status_code, 409)
        self.assertIn("Retome", complete_while_paused.json()["error"]["message"])

        start_while_paused = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/start",
            json={"version": paused["version"]},
            headers=headers,
        )
        self.assertEqual(start_while_paused.status_code, 409)
        self.assertIn("Retomar", start_while_paused.json()["error"]["message"])

        repeated_pause = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/pause",
            json={"version": paused["version"], "reason": "Pausa repetida"},
            headers=headers,
        )
        self.assertEqual(repeated_pause.status_code, 409)

        resumed_response = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/resume",
            json={"version": paused["version"], "observation": "Material disponivel"},
            headers=headers,
        )
        self.assertEqual(resumed_response.status_code, 200, resumed_response.text)
        resumed = resumed_response.json()
        self.assertEqual(resumed["production_status"], "INICIADO")
        self.assertEqual(resumed["current_area"], "PRODUCAO")
        self.assertEqual(resumed["items"][0]["version"], item_before["version"])
        self.assertEqual(
            {key: value for key, value in resumed["progress"].items() if key != "summary_status"},
            progress_before,
        )

        repeated_resume = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/resume",
            json={"version": resumed["version"]},
            headers=headers,
        )
        self.assertEqual(repeated_resume.status_code, 409)

        completed_response = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/complete-items",
            json={"version": resumed["version"]},
            headers=headers,
        )
        self.assertEqual(completed_response.status_code, 200, completed_response.text)
        completed = completed_response.json()
        self.assertEqual(completed["production_status"], "FINALIZADO")
        for operation, payload in (
            ("pause", {"version": completed["version"], "reason": "Pausa depois da conclusao"}),
            ("resume", {"version": completed["version"]}),
        ):
            with self.subTest(operation=operation):
                terminal_operation = self.client.post(
                    f"/api/v1/production/proposals/{proposal['id']}/{operation}",
                    json=payload,
                    headers=headers,
                )
                self.assertEqual(terminal_operation.status_code, 409)

        history = self.client.get(f"/api/v1/proposals/{proposal['id']}/history", headers=headers).json()
        production_events = [
            row for row in reversed(history)
            if row["event_type"] in {"PRODUCTION_STARTED", "PRODUCTION_PAUSED", "PRODUCTION_RESUMED", "PRODUCTION_COMPLETED"}
        ]
        self.assertEqual(
            [row["event_type"] for row in production_events],
            ["PRODUCTION_STARTED", "PRODUCTION_PAUSED", "PRODUCTION_RESUMED", "PRODUCTION_COMPLETED"],
        )
        self.assertEqual(
            [(row["from_status"], row["to_status"]) for row in production_events],
            [
                ("NAO_INICIADO", "INICIADO"),
                ("INICIADO", "PARADO"),
                ("PARADO", "INICIADO"),
                ("INICIADO", "FINALIZADO"),
            ],
        )
        self.assertEqual(production_events[1]["observation"], "Aguardando materia-prima")

        security = self.client.get(
            "/api/v1/security-events", params={"event_type": "PRODUCTION_PAUSED"}, headers=headers
        ).json()
        pause_audit = next(row for row in security["items"] if row["details"]["proposal_id"] == proposal["id"])
        self.assertEqual(pause_audit["details"]["from_status"], "INICIADO")
        self.assertEqual(pause_audit["details"]["to_status"], "PARADO")
        self.assertEqual(pause_audit["details"]["metadata"]["reason"], "Aguardando materia-prima")

    def test_concurrent_pause_with_same_version_applies_once(self):
        headers = self._headers()
        proposal = self.client.post(
            "/api/v1/proposals",
            json=_proposal_payload("CP-PAUSE-CONCURRENCY"),
            headers=headers,
        ).json()
        released = self._release_to_production(proposal, headers)
        started = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/start",
            json={"version": released["version"]},
            headers=headers,
        ).json()

        def pause(reason: str):
            with TestClient(create_app()) as concurrent_client:
                return concurrent_client.post(
                    f"/api/v1/production/proposals/{proposal['id']}/pause",
                    json={"version": started["version"], "reason": reason},
                    headers=headers,
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(pause, ["Pausa concorrente A", "Pausa concorrente B"]))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        self.assertEqual(
            next(response for response in responses if response.status_code == 409).json()["error"]["code"],
            "PROPOSAL_VERSION_CONFLICT",
        )
        current = self.client.get(f"/api/v1/production/proposals/{proposal['id']}", headers=headers).json()
        self.assertEqual(current["production_status"], "PARADO")
        history = self.client.get(f"/api/v1/proposals/{proposal['id']}/history", headers=headers).json()
        self.assertEqual(sum(row["event_type"] == "PRODUCTION_PAUSED" for row in history), 1)

    def test_pause_rolls_back_status_when_event_recording_fails(self):
        headers = self._headers()
        proposal = self.client.post(
            "/api/v1/proposals", json=_proposal_payload("CP-PAUSE-ROLLBACK"), headers=headers
        ).json()
        released = self._release_to_production(proposal, headers)
        started = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/start",
            json={"version": released["version"]},
            headers=headers,
        ).json()

        with patch(
            "api.app.modules.proposals.service._record_event",
            new=AsyncMock(side_effect=RuntimeError("falha de auditoria simulada")),
        ):
            with TestClient(create_app(), raise_server_exceptions=False) as failing_client:
                failed = failing_client.post(
                    f"/api/v1/production/proposals/{proposal['id']}/pause",
                    json={"version": started["version"], "reason": "Teste de rollback"},
                    headers=headers,
                )
        self.assertEqual(failed.status_code, 500)

        current = self.client.get(f"/api/v1/production/proposals/{proposal['id']}", headers=headers).json()
        self.assertEqual(current["production_status"], "INICIADO")
        self.assertEqual(current["version"], started["version"])
        history = self.client.get(f"/api/v1/proposals/{proposal['id']}/history", headers=headers).json()
        self.assertFalse(any(row["event_type"] == "PRODUCTION_PAUSED" for row in history))

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

        # O item 1 (produzido) foi separado para uma filha (CP01050-1), que
        # ja saiu de PRODUCAO para GALVANIZACAO - list_production_items()
        # só lista propostas ainda EM PRODUCAO (linha ~357), então o item
        # produzido deixa de aparecer aqui e passa a ser rastreado pelo
        # módulo de galvanização/expedição, não mais pela fila de produção.
        produced = self.client.get("/api/v1/production/items", params={"pending": "false", "search": "CP01050"}, headers=headers)
        self.assertEqual(produced.json()["items"], [])

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

    def test_regression_cp05378_partial_hierarchy_mixed_destinations_and_replay(self):
        """Cobre a criacao repetida de filhas e destinos simultaneos da CP05378."""
        headers = self._headers()
        proposal = self.client.post(
            "/api/v1/proposals",
            json=_proposal_payload(
                "CP05378",
                [
                    _item_payload("1", requires_galvanization=True),
                    _item_payload("2", requires_galvanization=False),
                    _item_payload("3", requires_galvanization=True),
                ],
            ),
            headers=headers,
        ).json()
        released = self._release_to_production(proposal, headers)
        started = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/start",
            json={"version": released["version"]},
            headers=headers,
        ).json()
        first_item = started["items"][0]
        first = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/complete-items",
            json={"version": started["version"], "item_ids": [first_item["id"]]},
            headers={**headers, "X-Request-ID": "cp05378-production-1"},
        )
        self.assertEqual(first.status_code, 200)
        first_body = first.json()
        self.assertEqual(first_body["current_area"], "PRODUCAO")

        second = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/complete-items",
            json={"version": first_body["version"]},
            headers={**headers, "X-Request-ID": "cp05378-production-2"},
        )
        self.assertEqual(second.status_code, 200)
        second_body = second.json()
        self.assertEqual(second_body["current_area"], "CONTROLE_GERAL")

        hierarchy = asyncio.run(self._proposal_hierarchy(proposal["id"]))
        self.assertEqual([row["proposal_number"] for row in hierarchy["children"]], ["CP05378-1", "CP05378-2"])
        self.assertEqual(hierarchy["mother_item_count"], 0)
        self.assertEqual(hierarchy["child_item_count"], 3)
        self.assertEqual({row["current_area"] for row in hierarchy["children"]}, {"GALVANIZACAO", "EXPEDICAO"})

        replay = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/complete-items",
            json={"version": first_body["version"]},
            headers={**headers, "X-Request-ID": "cp05378-production-2"},
        )
        self.assertEqual(replay.status_code, 200)
        replay_hierarchy = asyncio.run(self._proposal_hierarchy(proposal["id"]))
        self.assertEqual(len(replay_hierarchy["children"]), 2)
        self.assertGreaterEqual(asyncio.run(self._proposal_event_count(proposal["id"])), 3)

    def test_regression_cp05390_mother_reborn_when_partial_children_converge_via_separate_requests(self):
        """CP05390 (producao real, 2026-08-14): 3 filhas parciais, cada uma
        enviada/retornada em uma carga de galvanizacao propria, atraves de
        requisicoes HTTP inteiramente separadas (nao a mesma sessao/transacao) -
        exatamente como o Desktop faz na pratica, uma carga por vez. A ultima
        filha a convergir para EXPEDICAO/EM_SEPARACAO deve reunir a mae
        (PARENT_PROPOSAL_REBORN) na mesma chamada que a fez convergir, sem
        depender de nenhuma acao seguinte."""
        headers = self._headers()
        proposal = self.client.post(
            "/api/v1/proposals",
            json=_proposal_payload("CP05390", [_item_payload("1"), _item_payload("2"), _item_payload("3")]),
            headers=headers,
        ).json()
        released = self._release_to_production(proposal, headers)
        started = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/start", json={"version": released["version"]}, headers=headers
        ).json()
        items_by_number = {item["item_number"]: item for item in started["items"]}

        # Cada item e concluido, e imediatamente colocado em carga PROPRIA,
        # antes do proximo item ser concluido - exatamente a sequencia real
        # (uma carga por vez, nunca em lote), que e o que evita a filha nova
        # ser fundida de volta na anterior por _merge_equal_status_partial_children
        # (o agrupamento so funde filhas com area+status+cargas idendicas).
        version = started["version"]
        child_ids: list[int] = []
        load_ids: list[int] = []
        for index, number in enumerate(("1", "2", "3")):
            payload = {"version": version, "observation": f"Parcial {number}"}
            if number != "3":
                payload["item_ids"] = [items_by_number[number]["id"]]
            step = self.client.post(
                f"/api/v1/production/proposals/{proposal['id']}/complete-items",
                json=payload,
                headers={**headers, "X-Request-ID": f"cp05390-production-{number}"},
            )
            self.assertEqual(step.status_code, 200)
            active_child_ids = asyncio.run(self._active_child_ids(proposal["id"]))
            self.assertEqual(len(active_child_ids), index + 1, active_child_ids)
            new_child_id = max(set(active_child_ids) - set(child_ids))
            child = self.client.get(f"/api/v1/proposals/{new_child_id}", headers=headers).json()
            child_ids.append(child["id"])

            load = self.client.post(
                "/api/v1/galvanization/loads",
                json={
                    "driver_name": f"Motorista {number}",
                    "expected_return_date": "2026-08-20",
                    "items": [{"proposal_item_id": item["id"], "version": item["version"]} for item in child["items"]],
                },
                headers=headers,
            ).json()
            release_response = self.client.post(
                f"/api/v1/galvanization/loads/{load['id']}/release", json={"version": load["version"]}, headers=headers
            )
            self.assertEqual(release_response.status_code, 200)
            load_ids.append(load["id"])

            if number != "3":
                version = self.client.get(f"/api/v1/proposals/{proposal['id']}", headers=headers).json()["version"]

        final_mother = self.client.get(f"/api/v1/proposals/{proposal['id']}", headers=headers).json()
        self.assertEqual(final_mother["current_area"], "CONTROLE_GERAL")
        self.assertEqual(len(child_ids), 3)

        # Cada filha e devolvida por uma requisicao HTTP inteiramente
        # separada - nenhuma compartilha sessao/transacao com as outras.
        for index, (child_id, load_id) in enumerate(zip(child_ids, load_ids)):
            load = self.client.get(f"/api/v1/galvanization/loads/{load_id}", headers=headers).json()
            returned = self.client.post(
                f"/api/v1/galvanization/loads/{load_id}/returns",
                json={"version": load["version"], "proposal_ids": [child_id]},
                headers={**headers, "X-Request-ID": f"cp05390-return-{index}"},
            )
            self.assertEqual(returned.status_code, 200)

        mother = self.client.get(f"/api/v1/proposals/{proposal['id']}", headers=headers).json()
        self.assertFalse(mother["is_partial"])
        self.assertEqual(mother["current_area"], "EXPEDICAO")
        self.assertEqual(mother["current_status"], "EM_SEPARACAO")
        final_hierarchy = asyncio.run(self._proposal_hierarchy(proposal["id"]))
        self.assertEqual(final_hierarchy["children"], [])
        self.assertEqual(final_hierarchy["mother_item_count"], 3)
        self.assertTrue(asyncio.run(self._has_event(proposal["id"], "PARENT_PROPOSAL_REBORN")))

    async def _active_child_ids(self, parent_id: int) -> list[int]:
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            result = await session.execute(
                text("SELECT id FROM proposals WHERE parent_proposal_id = :parent_id AND active = true ORDER BY id"),
                {"parent_id": parent_id},
            )
            return [int(row[0]) for row in result.all()]

    async def _has_event(self, proposal_id: int, event_type: str) -> bool:
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            result = await session.execute(
                text("SELECT count(*) FROM proposal_events WHERE proposal_id = :proposal_id AND event_type = :event_type"),
                {"proposal_id": proposal_id, "event_type": event_type},
            )
            return int(result.scalar_one()) > 0

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

    def test_undefined_flow_stays_visible_in_production_queues(self):
        headers = self._headers()
        proposal = self.client.post(
            "/api/v1/proposals",
            json=_proposal_payload(
                "CP01004-U",
                [_item_payload("1", produce_internally=None, requires_galvanization=None)],
            ),
            headers=headers,
        ).json()

        released = self._release_to_production(proposal, headers)

        proposals = self.client.get(
            "/api/v1/production/proposals",
            params={"search": "CP01004-U"},
            headers=headers,
        )
        self.assertEqual(proposals.status_code, 200)
        self.assertEqual(proposals.json()["total"], 1)
        row = proposals.json()["items"][0]
        self.assertEqual(row["progress"]["undefined_flow_items"], 1)
        self.assertEqual(row["progress"]["internal_items"], 0)
        start_action = next(action for action in row["actions"] if action["id"] == "START_PRODUCTION")
        self.assertFalse(start_action["enabled"])

        items = self.client.get(
            "/api/v1/production/items",
            params={"pending": "true", "search": "CP01004-U"},
            headers=headers,
        )
        self.assertEqual(items.status_code, 200)
        self.assertEqual(items.json()["total"], 1)
        self.assertFalse(items.json()["items"][0]["flow_defined"])
        self.assertEqual(items.json()["items"][0]["production_pending_quantity"], "0.0000")
        self.assertEqual(released["current_area"], "PRODUCAO")

    def test_defining_external_flow_routes_automatically_to_expedition(self):
        headers = self._headers()
        proposal = self.client.post(
            "/api/v1/proposals",
            json=_proposal_payload(
                "CP01004-E",
                [_item_payload("1", produce_internally=None, requires_galvanization=None)],
            ),
            headers=headers,
        ).json()
        released = self._release_to_production(proposal, headers)
        item = released["items"][0]

        flow = self.client.patch(
            f"/api/v1/production/proposals/{proposal['id']}/item-flow",
            json={
                "version": released["version"],
                "origin": "Teste",
                "items": [
                    {
                        "item_id": item["id"],
                        "version": item["version"],
                        "produce_internally": False,
                        "non_production_reason": "pronta_entrega",
                        "requires_galvanization": False,
                    }
                ],
            },
            headers=headers,
        )

        self.assertEqual(flow.status_code, 200)
        self.assertEqual(flow.json()["current_area"], "EXPEDICAO")
        self.assertEqual(flow.json()["current_status"], "EM_SEPARACAO")
        self.assertEqual(flow.json()["production_status"], "FINALIZADO")
        production = self.client.get(
            "/api/v1/production/proposals",
            params={"search": "CP01004-E"},
            headers=headers,
        )
        self.assertEqual(production.json()["total"], 0)
        shipping = self.client.get(
            "/api/v1/shipping/proposals",
            params={"search": "CP01004-E"},
            headers=headers,
        )
        self.assertEqual(shipping.status_code, 200)
        self.assertEqual(shipping.json()["total"], 1)

    def test_defining_external_galvanized_flow_routes_automatically_to_galvanization(self):
        headers = self._headers()
        proposal = self.client.post(
            "/api/v1/proposals",
            json=_proposal_payload(
                "CP01004-G",
                [_item_payload("1", produce_internally=None, requires_galvanization=None)],
            ),
            headers=headers,
        ).json()
        released = self._release_to_production(proposal, headers)
        item = released["items"][0]

        flow = self.client.patch(
            f"/api/v1/production/proposals/{proposal['id']}/item-flow",
            json={
                "version": released["version"],
                "items": [
                    {
                        "item_id": item["id"],
                        "version": item["version"],
                        "produce_internally": False,
                        "non_production_reason": "terceirizado",
                        "requires_galvanization": True,
                    }
                ],
            },
            headers=headers,
        )

        self.assertEqual(flow.status_code, 200)
        self.assertEqual(flow.json()["current_area"], "GALVANIZACAO")
        self.assertEqual(flow.json()["current_status"], "AGUARDANDO_ENVIO")
        candidates = self.client.get(
            "/api/v1/galvanization/candidates",
            params={"search": "CP01004-G"},
            headers=headers,
        )
        self.assertEqual(candidates.status_code, 200)
        self.assertEqual(candidates.json()["total"], 1)

    def test_defining_internal_flow_keeps_proposal_in_production(self):
        headers = self._headers()
        proposal = self.client.post(
            "/api/v1/proposals",
            json=_proposal_payload(
                "CP01004-P",
                [_item_payload("1", produce_internally=None, requires_galvanization=None)],
            ),
            headers=headers,
        ).json()
        released = self._release_to_production(proposal, headers)
        item = released["items"][0]

        flow = self.client.patch(
            f"/api/v1/production/proposals/{proposal['id']}/item-flow",
            json={
                "version": released["version"],
                "items": [
                    {
                        "item_id": item["id"],
                        "version": item["version"],
                        "produce_internally": True,
                        "requires_galvanization": False,
                    }
                ],
            },
            headers=headers,
        )

        self.assertEqual(flow.status_code, 200)
        self.assertEqual(flow.json()["current_area"], "PRODUCAO")
        self.assertEqual(flow.json()["progress"]["internal_items"], 1)
        self.assertEqual(flow.json()["progress"]["pending_items"], 1)
        production = self.client.get(
            "/api/v1/production/proposals",
            params={"search": "CP01004-P"},
            headers=headers,
        )
        self.assertEqual(production.json()["total"], 1)

    def test_release_with_predefined_external_flow_skips_empty_production(self):
        headers = self._headers()
        item = _item_payload("1", produce_internally=False, requires_galvanization=False)
        item["non_production_reason"] = "pronta_entrega"
        proposal = self.client.post(
            "/api/v1/proposals",
            json=_proposal_payload("CP01004-D", [item]),
            headers=headers,
        ).json()

        released = self._release_to_production(proposal, headers)

        self.assertEqual(released["current_area"], "EXPEDICAO")
        self.assertEqual(released["current_status"], "EM_SEPARACAO")
        self.assertEqual(released["production_status"], "FINALIZADO")

    def test_official_production_item_flow_locked_after_real_production(self):
        headers = self._headers()
        payload = _proposal_payload("CP01005", [_item_payload("1"), _item_payload("2")])
        proposal = self.client.post("/api/v1/proposals", json=payload, headers=headers).json()
        released = self._release_to_production(proposal, headers)
        started = self.client.post(f"/api/v1/production/proposals/{proposal['id']}/start", json={"version": released["version"]}, headers=headers).json()

        first_item = started["items"][0]
        second_item = started["items"][1]
        self.assertTrue(first_item["flow_editable"])
        self.assertIsNone(first_item["flow_lock_reason"])

        partial = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/complete-items",
            json={"version": started["version"], "item_ids": [first_item["id"]], "observation": "Parcial"},
            headers=headers,
        )
        self.assertEqual(partial.status_code, 200)
        locked_item = next(item for item in partial.json()["items"] if item["id"] == first_item["id"])
        unlocked_item = next(item for item in partial.json()["items"] if item["id"] == second_item["id"])
        self.assertTrue(locked_item["produced"])
        self.assertFalse(locked_item["flow_editable"])
        self.assertIn("producao registrada", locked_item["flow_lock_reason"])
        self.assertTrue(unlocked_item["flow_editable"])
        self.assertIsNone(unlocked_item["flow_lock_reason"])

        # O item ja produzido (item 1) foi imediatamente separado para uma
        # filha (item 2 continuava pendente) - ele nao pertence mais aos
        # itens editaveis da MAE, entao a tentativa contra o endpoint da mae
        # nem chega a avaliar o bloqueio de fluxo, so rejeita o item como
        # inexistente naquela proposta.
        blocked = self.client.patch(
            f"/api/v1/production/proposals/{proposal['id']}/item-flow",
            json={
                "version": partial.json()["version"],
                "items": [
                    {"item_id": locked_item["id"], "version": locked_item["version"], "produce_internally": False, "non_production_reason": "pronta_entrega"},
                ],
            },
            headers=headers,
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["error"]["code"], "PRODUCTION_ITEM_NOT_AVAILABLE")

        # A propria filha ja saiu de PRODUCAO (foi direto para GALVANIZACAO),
        # entao o endpoint de fluxo - que so opera dentro da area de Producao
        # oficial - rejeita a proposta inteira antes mesmo de olhar o item.
        child_id = next(iter(asyncio.run(self._active_child_ids(proposal["id"]))))
        child_after_partial = self.client.get(f"/api/v1/proposals/{child_id}", headers=headers).json()
        self.assertEqual(child_after_partial["current_area"], "GALVANIZACAO")
        blocked_on_child = self.client.patch(
            f"/api/v1/production/proposals/{child_id}/item-flow",
            json={
                "version": child_after_partial["version"],
                "items": [
                    {"item_id": locked_item["id"], "version": locked_item["version"], "produce_internally": False, "non_production_reason": "pronta_entrega"},
                ],
            },
            headers=headers,
        )
        self.assertEqual(blocked_on_child.status_code, 409)
        self.assertEqual(blocked_on_child.json()["error"]["code"], "PRODUCTION_INVALID_STATE")

        # O item 2 (unico item que ainda pertence a mae) continua editavel
        # normalmente.
        unlocked_only = self.client.patch(
            f"/api/v1/production/proposals/{proposal['id']}/item-flow",
            json={
                "version": partial.json()["version"],
                "items": [
                    {"item_id": unlocked_item["id"], "version": unlocked_item["version"], "produce_internally": False, "non_production_reason": "terceirizado"},
                ],
            },
            headers=headers,
        )
        self.assertEqual(unlocked_only.status_code, 200)
        saved_unlocked = next(item for item in unlocked_only.json()["items"] if item["id"] == unlocked_item["id"])
        self.assertEqual(saved_unlocked["produce_internally"], "NAO")

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
        self.assertEqual(len(partial.json()["returns"]), 1)
        first_return = partial.json()["returns"][0]
        self.assertEqual(first_return["return_type"], "PARCIAL")
        self.assertEqual(len(first_return["items"]), 1)
        self.assertEqual(first_return["items"][0]["load_item_id"], first_load_item["id"])
        self.assertEqual(first_return["items"][0]["returned_quantity"], "2.0000")
        self.assertTrue(any(row["event_type"] == "GALVANIZATION_RETURN_REGISTERED" for row in partial.json()["history"]))

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
        self.assertEqual(len(total.json()["returns"]), 2)
        self.assertEqual(total.json()["returns"][0]["id"], first_return["id"])
        self.assertEqual(total.json()["returns"][1]["return_type"], "TOTAL")
        self.assertEqual(len(total.json()["returns"][1]["items"]), 1)
        self.assertEqual(total.json()["returns"][1]["items"][0]["proposal_id"], second["id"])

        history_ids_before_read = [row["id"] for row in total.json()["history"]]
        read_only_detail = self.client.get(
            f"/api/v1/galvanization/loads/{load.json()['id']}", headers=headers
        )
        self.assertEqual(read_only_detail.status_code, 200)
        self.assertEqual([row["id"] for row in read_only_detail.json()["history"]], history_ids_before_read)
        self.assertEqual([row["id"] for row in read_only_detail.json()["returns"]], [row["id"] for row in total.json()["returns"]])
        proposal_after_total = self.client.get(f"/api/v1/proposals/{second['id']}", headers=headers).json()
        self.assertEqual(proposal_after_total["current_area"], "EXPEDICAO")
        self.assertEqual(proposal_after_total["shipping_status"], "EM_SEPARACAO")

        closed = self.client.post(f"/api/v1/galvanization/loads/{load.json()['id']}/close", json={"version": total.json()["version"]}, headers=headers)
        self.assertEqual(closed.status_code, 200)
        self.assertIsNotNone(closed.json()["closed_at"])

    def test_galvanization_load_edit_recalculates_removed_kept_and_added_proposals(self):
        headers = self._headers()
        removed = self._proposal_ready_for_galvanization(
            "CP-LOAD-EDIT-REMOVED", headers, [_item_payload("1"), _item_payload("2")]
        )
        kept = self._proposal_ready_for_galvanization("CP-LOAD-EDIT-KEPT", headers, [_item_payload("1")])
        added = self._proposal_ready_for_galvanization("CP-LOAD-EDIT-ADDED", headers, [_item_payload("1")])
        load = self.client.post(
            "/api/v1/galvanization/loads",
            json={
                "driver_name": "Motorista",
                "items": [
                    {"proposal_item_id": removed["items"][0]["id"]},
                    {"proposal_item_id": removed["items"][1]["id"]},
                    {"proposal_item_id": kept["items"][0]["id"], "sent_quantity": "1.0000"},
                ],
            },
            headers=headers,
        ).json()
        kept_load_item_id = next(
            item["id"] for item in load["items"] if item["proposal_id"] == kept["id"]
        )

        edited = self.client.patch(
            f"/api/v1/galvanization/loads/{load['id']}",
            json={
                "version": load["version"],
                "items": [
                    {"proposal_item_id": kept["items"][0]["id"], "sent_quantity": "1.5000"},
                    {"proposal_item_id": added["items"][0]["id"]},
                ],
            },
            headers=headers,
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        edited_body = edited.json()
        self.assertEqual(
            next(item["id"] for item in edited_body["items"] if item["proposal_id"] == kept["id"]),
            kept_load_item_id,
            "item inalterado na composicao deve preservar sua identidade",
        )
        self.assertEqual(
            next(item["sent_quantity"] for item in edited_body["items"] if item["proposal_id"] == kept["id"]),
            "1.5000",
        )

        removed_after = self.client.get(f"/api/v1/proposals/{removed['id']}", headers=headers).json()
        kept_after = self.client.get(f"/api/v1/proposals/{kept['id']}", headers=headers).json()
        added_after = self.client.get(f"/api/v1/proposals/{added['id']}", headers=headers).json()
        self.assertEqual(removed_after["galvanization_status"], "AGUARDANDO_ENVIO")
        self.assertEqual(kept_after["galvanization_status"], "EM_CARGA")
        self.assertEqual(added_after["galvanization_status"], "EM_CARGA")

        candidates = self.client.get(
            "/api/v1/galvanization/candidates", params={"search": "CP-LOAD-EDIT-REMOVED"}, headers=headers
        ).json()
        self.assertEqual({row["item_id"] for row in candidates["items"]}, {item["id"] for item in removed["items"]})
        self.assertTrue(all(row["situation"] == "DISPONIVEL" for row in candidates["items"]))

        audit = asyncio.run(self._galvanization_load_update_metadata(load["id"]))
        self.assertEqual(set(audit["items_removed"]), {item["id"] for item in removed["items"]})
        self.assertEqual(audit["items_added"], [added["items"][0]["id"]])
        self.assertEqual(audit["items_updated"], [kept["items"][0]["id"]])
        self.assertEqual(set(audit["proposals_affected"]), {removed["id"], kept["id"], added["id"]})
        self.assertEqual(audit["proposal_states_before"][str(removed["id"])]["current_status"], "EM_CARGA")
        self.assertEqual(audit["proposal_states_after"][str(removed["id"])]["current_status"], "AGUARDANDO_ENVIO")

        emptied = self.client.patch(
            f"/api/v1/galvanization/loads/{load['id']}",
            json={"version": edited_body["version"], "items": []},
            headers=headers,
        )
        self.assertEqual(emptied.status_code, 200, emptied.text)
        self.assertEqual(emptied.json()["items"], [])
        for proposal_id in (kept["id"], added["id"]):
            proposal_after = self.client.get(f"/api/v1/proposals/{proposal_id}", headers=headers).json()
            self.assertEqual(proposal_after["galvanization_status"], "AGUARDANDO_ENVIO")

    def test_galvanization_load_edit_keeps_status_when_another_draft_link_exists(self):
        headers = self._headers()
        proposal = self._proposal_ready_for_galvanization(
            "CP-LOAD-EDIT-OTHER", headers, [_item_payload("1"), _item_payload("2")]
        )
        first_load = self.client.post(
            "/api/v1/galvanization/loads",
            json={"driver_name": "Motorista 1", "items": [{"proposal_item_id": proposal["items"][0]["id"]}]},
            headers=headers,
        ).json()
        second_load = self.client.post(
            "/api/v1/galvanization/loads",
            json={"driver_name": "Motorista 2", "items": [{"proposal_item_id": proposal["items"][1]["id"]}]},
            headers=headers,
        )
        self.assertEqual(second_load.status_code, 201, second_load.text)

        removed_from_first = self.client.patch(
            f"/api/v1/galvanization/loads/{first_load['id']}",
            json={"version": first_load["version"], "items": []},
            headers=headers,
        )
        self.assertEqual(removed_from_first.status_code, 200, removed_from_first.text)
        proposal_after = self.client.get(f"/api/v1/proposals/{proposal['id']}", headers=headers).json()
        self.assertEqual(proposal_after["galvanization_status"], "EM_CARGA")

        released_other = self.client.post(
            f"/api/v1/galvanization/loads/{second_load.json()['id']}/release",
            json={"version": second_load.json()["version"]},
            headers=headers,
        )
        self.assertEqual(released_other.status_code, 200, released_other.text)
        rebuilt_first = self.client.patch(
            f"/api/v1/galvanization/loads/{first_load['id']}",
            json={
                "version": removed_from_first.json()["version"],
                "items": [{"proposal_item_id": proposal["items"][0]["id"]}],
            },
            headers=headers,
        )
        self.assertEqual(rebuilt_first.status_code, 200, rebuilt_first.text)
        removed_again = self.client.patch(
            f"/api/v1/galvanization/loads/{first_load['id']}",
            json={"version": rebuilt_first.json()["version"], "items": []},
            headers=headers,
        )
        self.assertEqual(removed_again.status_code, 200, removed_again.text)
        proposal_sent = self.client.get(f"/api/v1/proposals/{proposal['id']}", headers=headers).json()
        self.assertEqual(proposal_sent["galvanization_status"], "ENVIADO_GALVANIZACAO")

        other_load_item = released_other.json()["items"][0]
        partial_return = self.client.post(
            f"/api/v1/galvanization/loads/{released_other.json()['id']}/returns",
            json={
                "version": released_other.json()["version"],
                "items": [{"load_item_id": other_load_item["id"], "quantity_returned": "1.0000"}],
            },
            headers=headers,
        )
        self.assertEqual(partial_return.status_code, 200, partial_return.text)
        rebuilt_after_partial = self.client.patch(
            f"/api/v1/galvanization/loads/{first_load['id']}",
            json={
                "version": removed_again.json()["version"],
                "items": [{"proposal_item_id": proposal["items"][0]["id"]}],
            },
            headers=headers,
        ).json()
        removed_after_partial = self.client.patch(
            f"/api/v1/galvanization/loads/{first_load['id']}",
            json={"version": rebuilt_after_partial["version"], "items": []},
            headers=headers,
        )
        self.assertEqual(removed_after_partial.status_code, 200, removed_after_partial.text)
        proposal_partial = self.client.get(f"/api/v1/proposals/{proposal['id']}", headers=headers).json()
        self.assertEqual(proposal_partial["galvanization_status"], "RETORNOU_PARCIAL")

    def test_galvanization_load_edit_preserves_cancelled_terminal_state_and_rejects_addition(self):
        headers = self._headers()
        linked = self._proposal_ready_for_galvanization("CP-LOAD-EDIT-CANCELLED", headers, [_item_payload("1")])
        load = self.client.post(
            "/api/v1/galvanization/loads",
            json={"driver_name": "Motorista", "items": [{"proposal_item_id": linked["items"][0]["id"]}]},
            headers=headers,
        ).json()
        linked_current = self.client.get(f"/api/v1/proposals/{linked['id']}", headers=headers).json()
        cancelled = self.client.post(
            f"/api/v1/proposals/{linked['id']}/cancel",
            json={"version": linked_current["version"], "reason": "Cancelamento terminal"},
            headers=headers,
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)

        removed = self.client.patch(
            f"/api/v1/galvanization/loads/{load['id']}",
            json={"version": load["version"], "items": []},
            headers=headers,
        )
        self.assertEqual(removed.status_code, 200, removed.text)
        cancelled_after = self.client.get(f"/api/v1/proposals/{linked['id']}", headers=headers).json()
        self.assertTrue(cancelled_after["is_cancelled"])
        self.assertEqual(cancelled_after["current_status"], "CANCELADA")

        rejected = self.client.post(
            "/api/v1/galvanization/loads",
            json={"driver_name": "Outro", "items": [{"proposal_item_id": linked["items"][0]["id"]}]},
            headers=headers,
        )
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.json()["error"]["code"], "PROPOSAL_CANCELLED_TERMINAL")

    def test_galvanization_load_edit_is_atomic_and_sent_load_remains_immutable(self):
        headers = self._headers()
        first = self._proposal_ready_for_galvanization("CP-LOAD-EDIT-ROLLBACK-A", headers, [_item_payload("1")])
        second = self._proposal_ready_for_galvanization("CP-LOAD-EDIT-ROLLBACK-B", headers, [_item_payload("1")])
        load = self.client.post(
            "/api/v1/galvanization/loads",
            json={"driver_name": "Motorista", "items": [{"proposal_item_id": first["items"][0]["id"]}]},
            headers=headers,
        ).json()

        with patch(
            "api.app.modules.proposals.service._recalculate_proposal_after_load_change",
            new=AsyncMock(side_effect=RuntimeError("falha de recalculo simulada")),
        ):
            with TestClient(create_app(), raise_server_exceptions=False) as failing_client:
                failed = failing_client.patch(
                    f"/api/v1/galvanization/loads/{load['id']}",
                    json={"version": load["version"], "items": [{"proposal_item_id": second["items"][0]["id"]}]},
                    headers=headers,
                )
        self.assertEqual(failed.status_code, 500)
        load_after = self.client.get(f"/api/v1/galvanization/loads/{load['id']}", headers=headers).json()
        self.assertEqual(load_after["version"], load["version"])
        self.assertEqual([item["proposal_id"] for item in load_after["items"]], [first["id"]])
        self.assertEqual(
            self.client.get(f"/api/v1/proposals/{first['id']}", headers=headers).json()["galvanization_status"],
            "EM_CARGA",
        )
        self.assertEqual(
            self.client.get(f"/api/v1/proposals/{second['id']}", headers=headers).json()["galvanization_status"],
            "AGUARDANDO_ENVIO",
        )

        released = self.client.post(
            f"/api/v1/galvanization/loads/{load['id']}/release",
            json={"version": load["version"]},
            headers=headers,
        ).json()
        historical_edit = self.client.patch(
            f"/api/v1/galvanization/loads/{load['id']}",
            json={"version": released["version"], "items": []},
            headers=headers,
        )
        self.assertEqual(historical_edit.status_code, 409)
        self.assertEqual(historical_edit.json()["error"]["code"], "GALVANIZATION_LOAD_INVALID_STATE")

    def test_concurrent_galvanization_load_edits_do_not_overwrite_and_balance_is_not_reserved_twice(self):
        headers = self._headers()
        proposal = self._proposal_ready_for_galvanization("CP-LOAD-EDIT-CONCURRENCY", headers, [_item_payload("1")])
        item_id = proposal["items"][0]["id"]
        load = self.client.post(
            "/api/v1/galvanization/loads",
            json={"driver_name": "Motorista", "items": [{"proposal_item_id": item_id}]},
            headers=headers,
        ).json()

        clients = [TestClient(create_app()), TestClient(create_app())]
        for client in clients:
            client.__enter__()
        try:
            def edit(args):
                client, items = args
                return client.patch(
                    f"/api/v1/galvanization/loads/{load['id']}",
                    json={"version": load["version"], "items": items},
                    headers=headers,
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                responses = list(executor.map(edit, [(clients[0], []), (clients[1], [{"proposal_item_id": item_id}])]))
        finally:
            for client in clients:
                client.__exit__(None, None, None)
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        self.assertEqual(
            next(response for response in responses if response.status_code == 409).json()["error"]["code"],
            "GALVANIZATION_LOAD_VERSION_CONFLICT",
        )

        reserve_proposal = self._proposal_ready_for_galvanization(
            "CP-LOAD-DOUBLE-RESERVE", headers, [_item_payload("1")]
        )
        reserve_item_id = reserve_proposal["items"][0]["id"]
        available = self.client.get(
            "/api/v1/galvanization/candidates", params={"search": "CP-LOAD-DOUBLE-RESERVE"}, headers=headers
        ).json()["items"][0]["available_quantity"]
        clients = [TestClient(create_app()), TestClient(create_app())]
        for client in clients:
            client.__enter__()
        try:
            def reserve(client):
                return client.post(
                    "/api/v1/galvanization/loads",
                    json={"driver_name": "Concorrente", "items": [{"proposal_item_id": reserve_item_id, "sent_quantity": available}]},
                    headers=headers,
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                reserve_responses = list(executor.map(reserve, clients))
        finally:
            for client in clients:
                client.__exit__(None, None, None)
        self.assertEqual(sorted(response.status_code for response in reserve_responses), [201, 409])
        self.assertEqual(
            next(response for response in reserve_responses if response.status_code == 409).json()["error"]["code"],
            "GALVANIZATION_ITEM_NOT_ELIGIBLE",
        )

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

    def test_official_galvanization_load_weight_is_informational_and_independent(self):
        headers = self._headers()
        proposal = self._proposal_ready_for_galvanization("CP02010", headers, [_item_payload("1")])
        item = proposal["items"][0]

        response = self.client.post(
            "/api/v1/galvanization/loads",
            json={
                "driver_name": "Motorista",
                "max_weight": "5.0000",
                "load_weight": "9.0000",
                "items": [{"proposal_item_id": item["id"], "version": item["version"]}],
            },
            headers=headers,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["load_weight"], "9.0000")
        self.assertEqual(response.json()["max_weight"], "5.0000")
        self.assertNotEqual(response.json()["load_weight"], response.json()["known_items_weight"])

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
        self.assertEqual(after.json()["items"], [])

        available_only = self.client.get("/api/v1/galvanization/candidates", params={"search": "CP02014", "situation": "DISPONIVEL"}, headers=headers)
        self.assertEqual(available_only.json()["items"], [])

        in_galvanization_only = self.client.get("/api/v1/galvanization/candidates", params={"search": "CP02014", "situation": "EM_GALVANIZACAO"}, headers=headers)
        self.assertEqual(in_galvanization_only.json()["items"], [])

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
        self.assertEqual(after_partial_return.json()["items"], [], "item em carga/retorno deve aparecer somente no detalhe da carga")

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

    def test_compensated_remanagement_moves_ready_and_productive_allocation_without_delivery(self):
        headers = self._headers()
        destination = self.client.post("/api/v1/proposals", json=_proposal_payload("CP03003", [_item_payload("1", requires_galvanization=False)]), headers=headers).json()
        source = self._proposal_ready_for_expedition("CP03004", headers, [_item_payload("1", requires_galvanization=False)])
        source_detail = self.client.get(f"/api/v1/shipping/proposals/{source['id']}", headers=headers).json()
        source_item = source_detail["items"][0]
        destination = self.client.get(f"/api/v1/proposals/{destination['id']}", headers=headers).json()
        destination_item = destination["items"][0]
        compatible = self.client.get(
            f"/api/v1/shipping/remanagements/compatible-items?source_proposal_id={source['id']}&destination_proposal_id={destination['id']}",
            headers=headers,
        ).json()[0]

        remanaged = self.client.post(
            "/api/v1/shipping/remanagements",
            json={
                "source_proposal_id": source["id"],
                "destination_proposal_id": destination["id"],
                "source_version": source_detail["version"],
                "destination_version": destination["version"],
                "idempotency_key": "test-remanagement-main-0001",
                "items": [{
                    "source_item_id": source_item["proposal_item_id"],
                    "destination_item_id": destination_item["id"],
                    "source_item_version": compatible["source_item_version"],
                    "destination_item_version": compatible["destination_item_version"],
                    "quantity": "2.0000",
                }],
                "reason": "Cliente retirou material de outra proposta",
            },
            headers=headers,
        )
        self.assertEqual(remanaged.status_code, 201, remanaged.text)
        self.assertEqual(remanaged.json()["total_quantity"], "2.0000")

        source_after = self.client.get(f"/api/v1/proposals/{source['id']}", headers=headers).json()
        self.assertEqual(source_after["current_area"], "EXPEDICAO")
        self.assertEqual(source_after["production_status"], "ITEM_PENDENTE_FABRICACAO")
        self.assertTrue(source_after["has_production_pending"])
        self.assertTrue(source_after["items"][0]["produced"])

        destination_shipping = self.client.get(f"/api/v1/shipping/proposals/{destination['id']}", headers=headers).json()
        self.assertEqual(destination_shipping["items"][0]["available_quantity"], "2.0000")
        self.assertEqual(destination_shipping["items"][0]["delivered_quantity"], "0.0000")
        self.assertFalse(self.client.get(f"/api/v1/proposals/{destination['id']}", headers=headers).json()["items"][0]["delivered"])

        production = self.client.get("/api/v1/production/proposals?limit=200&offset=0", headers=headers).json()
        source_row = next(row for row in production["items"] if row["id"] == source["id"])
        self.assertEqual(source_row["progress"]["reallocated_production_pending"], "2.0000")

        repeated = self.client.post("/api/v1/shipping/remanagements", json={
            "source_proposal_id": source["id"], "destination_proposal_id": destination["id"],
            "source_version": source_detail["version"], "destination_version": destination["version"],
            "idempotency_key": "test-remanagement-main-0001", "reason": "Cliente retirou material de outra proposta",
            "items": [{"source_item_id": source_item["proposal_item_id"], "destination_item_id": destination_item["id"], "quantity": "2.0000"}],
        }, headers=headers)
        self.assertEqual(repeated.status_code, 201)
        self.assertEqual(repeated.json()["id"], remanaged.json()["id"])

        source_for_production = self.client.get(f"/api/v1/proposals/{source['id']}", headers=headers).json()
        started_reallocated = self.client.post(
            f"/api/v1/production/proposals/{source['id']}/start",
            json={"version": source_for_production["version"]},
            headers=headers,
        )
        self.assertEqual(started_reallocated.status_code, 200, started_reallocated.text)
        started_reallocated_body = started_reallocated.json()
        self.assertEqual(started_reallocated_body["current_area"], "EXPEDICAO")
        preserved_expedition = {
            key: started_reallocated_body.get(key)
            for key in ("current_area", "current_status", "general_status", "shipping_status", "galvanization_status")
        }
        production_balance = {
            key: value for key, value in started_reallocated_body["progress"].items() if key != "summary_status"
        }
        paused_reallocated = self.client.post(
            f"/api/v1/production/proposals/{source['id']}/pause",
            json={"version": started_reallocated_body["version"], "reason": "Pausa da fabricacao remanejada"},
            headers=headers,
        )
        self.assertEqual(paused_reallocated.status_code, 200, paused_reallocated.text)
        paused_reallocated_body = paused_reallocated.json()
        self.assertEqual(paused_reallocated_body["production_status"], "PARADO")
        self.assertEqual(
            {key: paused_reallocated_body.get(key) for key in preserved_expedition},
            preserved_expedition,
        )
        self.assertEqual(
            {key: value for key, value in paused_reallocated_body["progress"].items() if key != "summary_status"},
            production_balance,
        )
        resumed_reallocated = self.client.post(
            f"/api/v1/production/proposals/{source['id']}/resume",
            json={"version": paused_reallocated_body["version"]},
            headers=headers,
        )
        self.assertEqual(resumed_reallocated.status_code, 200, resumed_reallocated.text)
        self.assertEqual(
            {key: resumed_reallocated.json().get(key) for key in preserved_expedition},
            preserved_expedition,
        )
        completed_reallocated = self.client.post(
            f"/api/v1/production/proposals/{source['id']}/complete-items",
            json={"version": resumed_reallocated.json()["version"], "item_ids": [source_item["proposal_item_id"]]},
            headers=headers,
        )
        self.assertEqual(completed_reallocated.status_code, 200, completed_reallocated.text)
        self.assertEqual(completed_reallocated.json()["current_area"], "EXPEDICAO")
        self.assertEqual(completed_reallocated.json()["progress"]["reallocated_production_pending"], "0.0000")
        self.assertEqual(completed_reallocated.json()["progress"]["reallocated_production_completed"], "2.0000")
        source_shipping = self.client.get(f"/api/v1/shipping/proposals/{source['id']}", headers=headers).json()
        self.assertEqual(source_shipping["items"][0]["pending_quantity"], "2.0000")

    def test_compensated_remanagement_concurrency_never_overspends_source_ready_balance(self):
        headers = self._headers()
        destination = self.client.post("/api/v1/proposals", json=_proposal_payload("CP03005", [_item_payload("1", requires_galvanization=False)]), headers=headers).json()
        source = self._proposal_ready_for_expedition("CP03006", headers, [_item_payload("1", requires_galvanization=False)])
        source_detail = self.client.get(f"/api/v1/shipping/proposals/{source['id']}", headers=headers).json()
        destination = self.client.get(f"/api/v1/proposals/{destination['id']}", headers=headers).json()
        compatible = self.client.get(
            f"/api/v1/shipping/remanagements/compatible-items?source_proposal_id={source['id']}&destination_proposal_id={destination['id']}",
            headers=headers,
        ).json()[0]

        def send(key: str):
            with TestClient(create_app()) as concurrent_client:
                return concurrent_client.post("/api/v1/shipping/remanagements", json={
                    "source_proposal_id": source["id"],
                    "destination_proposal_id": destination["id"],
                    "source_version": source_detail["version"],
                    "destination_version": destination["version"],
                    "idempotency_key": key,
                    "reason": "Disputa concorrente controlada",
                    "items": [{
                        "source_item_id": compatible["source_item_id"],
                        "destination_item_id": compatible["destination_item_id"],
                        "quantity": "2.0000",
                    }],
                }, headers=headers)

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(send, ["concurrency-remanagement-0001", "concurrency-remanagement-0002"]))
        self.assertEqual(sorted(response.status_code for response in responses), [201, 409])
        history = self.client.get(f"/api/v1/shipping/remanagements?proposal_id={source['id']}", headers=headers).json()
        self.assertEqual(history["total"], 1)
        source_after = self.client.get(f"/api/v1/shipping/proposals/{source['id']}", headers=headers).json()
        self.assertEqual(source_after["items"][0]["remanaged_quantity"], "2.0000")

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
        proposal = self._proposal_ready_for_expedition(
            "CP05001",
            headers,
            [_item_payload("1", requires_galvanization=False)],
        )
        asyncio.run(
            self._force_projection(
                proposal["id"],
                current_area="PRODUCAO",
                current_status="FINALIZADO",
                general_status="EM_PRODUCAO",
                shipping_status=None,
            )
        )
        stuck = self.client.get(f"/api/v1/proposals/{proposal['id']}", headers=headers).json()

        options = self.client.get(
            f"/api/v1/proposals/{proposal['id']}/administrative-corrections/options",
            headers=headers,
        )
        self.assertEqual(options.status_code, 200, options.text)
        available = {
            (row["target_area"], row["target_status"])
            for row in options.json()["options"]
        }
        self.assertEqual(available, {("EXPEDICAO", "EM_SEPARACAO")})

        events_before_preview = asyncio.run(self._proposal_event_count(proposal["id"]))
        preview = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/administrative-corrections/preview",
            json={
                "expected_version": stuck["version"],
                "correction_type": "STATE",
                "to_area": "EXPEDICAO",
                "to_status": "EM_SEPARACAO",
            },
            headers=headers,
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertTrue(preview.json()["allowed"])
        self.assertTrue(any(row["field"] == "current_area" for row in preview.json()["changes"]))
        self.assertIn("quantidades produzidas", preview.json()["unchanged_fields"])
        self.assertEqual(asyncio.run(self._proposal_event_count(proposal["id"])), events_before_preview)
        self.assertEqual(
            self.client.get(f"/api/v1/proposals/{proposal['id']}", headers=headers).json()["current_area"],
            "PRODUCAO",
        )

        impossible_delivery = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/administrative-corrections/preview",
            json={
                "expected_version": stuck["version"],
                "to_area": "EXPEDICAO",
                "to_status": "ENTREGUE",
            },
            headers=headers,
        )
        self.assertEqual(impossible_delivery.status_code, 200)
        self.assertFalse(impossible_delivery.json()["allowed"])
        self.assertIn(
            "DELIVERY_FACTS_MISSING",
            {row["code"] for row in impossible_delivery.json()["blockers"]},
        )

        corrected = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/administrative-correction",
            json={
                "expected_version": stuck["version"],
                "correction_type": "STATE",
                "to_area": "EXPEDICAO",
                "to_status": "EM_SEPARACAO",
                "reason": "Falha de sincronizacao deixou a proposta na fila produtiva",
                "idempotency_key": "admin-correction-cp05001-0001",
            },
            headers=headers,
        )
        self.assertEqual(corrected.status_code, 200, corrected.text)
        self.assertEqual(corrected.json()["current_area"], "EXPEDICAO")
        self.assertEqual(corrected.json()["current_status"], "EM_SEPARACAO")
        self.assertEqual(corrected.json()["production_status"], "FINALIZADO")
        self.assertEqual(corrected.json()["version"], stuck["version"] + 1)

        repeated = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/administrative-correction",
            json={
                "expected_version": stuck["version"],
                "to_area": "EXPEDICAO",
                "to_status": "EM_SEPARACAO",
                "reason": "Falha de sincronizacao deixou a proposta na fila produtiva",
                "idempotency_key": "admin-correction-cp05001-0001",
            },
            headers=headers,
        )
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["version"], corrected.json()["version"])
        self.assertEqual(asyncio.run(self._proposal_event_count(proposal["id"])), events_before_preview + 1)

        blank_reason = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/administrative-correction",
            json={
                "expected_version": corrected.json()["version"],
                "to_area": "PRODUCAO",
                "to_status": "FINALIZADO",
                "reason": "   ",
                "idempotency_key": "admin-correction-blank-0001",
            },
            headers=headers,
        )
        self.assertEqual(blank_reason.status_code, 422)

        invalid_status = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/administrative-correction",
            json={
                "expected_version": corrected.json()["version"],
                "to_area": "PRODUCAO",
                "to_status": "STATUS_INVALIDO",
                "reason": "Teste de bloqueio",
                "idempotency_key": "admin-correction-invalid-0001",
            },
            headers=headers,
        )
        self.assertEqual(invalid_status.status_code, 409)
        self.assertEqual(invalid_status.json()["error"]["code"], "ADMIN_CORRECTION_BLOCKED")
        self.assertTrue(invalid_status.json()["error"]["details"]["blockers"])

        not_found = self.client.post(
            "/api/v1/proposals/999999/administrative-correction",
            json={
                "expected_version": 1,
                "to_area": "PRODUCAO",
                "to_status": "PARADO",
                "reason": "Teste de proposta ausente",
                "idempotency_key": "admin-correction-missing-0001",
            },
            headers=headers,
        )
        self.assertEqual(not_found.status_code, 404)

        operator_headers = asyncio.run(self._operator_headers())
        denied = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/administrative-correction",
            json={
                "expected_version": corrected.json()["version"],
                "to_area": "PRODUCAO",
                "to_status": "FINALIZADO",
                "reason": "Sem permissao administrativa",
                "idempotency_key": "admin-correction-denied-0001",
            },
            headers=operator_headers,
        )
        self.assertEqual(denied.status_code, 403)
        denied_options = self.client.get(
            f"/api/v1/proposals/{proposal['id']}/administrative-corrections/options",
            headers=operator_headers,
        )
        self.assertEqual(denied_options.status_code, 403)

        history = self.client.get(f"/api/v1/proposals/{proposal['id']}/history", headers=headers)
        self.assertEqual(history.status_code, 200)
        self.assertTrue(any(row["event_type"] == "PROPOSAL_ADMINISTRATIVE_CORRECTION" for row in history.json()))
        metadata = asyncio.run(self._administrative_event_metadata(proposal["id"]))
        self.assertEqual(metadata["before_snapshot"]["current_area"], "PRODUCAO")
        self.assertEqual(metadata["after_snapshot"]["current_area"], "EXPEDICAO")
        self.assertEqual(metadata["expected_version"], stuck["version"])
        self.assertEqual(metadata["resulting_version"], corrected.json()["version"])
        self.assertIn("current_area", metadata["changed_fields"])
        security_events = self.client.get("/api/v1/security-events?limit=20&offset=0", headers=headers)
        self.assertTrue(any(row["event_type"] == "PROPOSAL_ADMINISTRATIVE_CORRECTION" for row in security_events.json()["items"]))

    def test_administrative_correction_blocks_impossible_facts_cancelled_and_stale_version(self):
        headers = self._headers()
        proposal = self.client.post(
            "/api/v1/proposals",
            json=_proposal_payload("CP05002", [_item_payload("1", requires_galvanization=True)]),
            headers=headers,
        ).json()
        released = self._release_to_production(proposal, headers)

        production_complete = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/administrative-corrections/preview",
            json={"expected_version": released["version"], "to_area": "PRODUCAO", "to_status": "FINALIZADO"},
            headers=headers,
        ).json()
        total_return = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/administrative-corrections/preview",
            json={"expected_version": released["version"], "to_area": "GALVANIZACAO", "to_status": "RETORNOU_GALVANIZACAO"},
            headers=headers,
        ).json()
        self.assertIn("PRODUCTION_INCOMPLETE", {row["code"] for row in production_complete["blockers"]})
        self.assertIn("GALVANIZATION_RETURN_MISSING", {row["code"] for row in total_return["blockers"]})

        started = self.client.post(
            f"/api/v1/production/proposals/{proposal['id']}/start",
            json={"version": released["version"]},
            headers=headers,
        )
        self.assertEqual(started.status_code, 200, started.text)
        stale = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/administrative-correction",
            json={
                "expected_version": released["version"],
                "to_area": "PRODUCAO",
                "to_status": "INICIADO",
                "reason": "Tentativa baseada em versao antiga",
                "idempotency_key": "admin-correction-stale-0001",
            },
            headers=headers,
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["error"]["code"], "PROPOSAL_VERSION_CONFLICT")

        cancellable = self.client.post(
            "/api/v1/proposals",
            json=_proposal_payload("CP05003", [_item_payload("1", requires_galvanization=False)]),
            headers=headers,
        ).json()
        cancelled = self.client.post(
            f"/api/v1/proposals/{cancellable['id']}/cancel",
            json={"version": cancellable["version"], "reason": "Cancelamento oficial"},
            headers=headers,
        ).json()
        cancelled_options = self.client.get(
            f"/api/v1/proposals/{cancellable['id']}/administrative-corrections/options",
            headers=headers,
        )
        self.assertEqual(cancelled_options.status_code, 200)
        self.assertEqual(cancelled_options.json()["options"], [])
        reactivation = self.client.post(
            f"/api/v1/proposals/{cancellable['id']}/administrative-correction",
            json={
                "expected_version": cancelled["version"],
                "to_area": "PRODUCAO",
                "to_status": "NAO_INICIADO",
                "reason": "Tentativa de reativacao generica",
                "idempotency_key": "admin-correction-cancelled-0001",
            },
            headers=headers,
        )
        self.assertEqual(reactivation.status_code, 409)
        blockers = reactivation.json()["error"]["details"]["blockers"]
        self.assertEqual(blockers[0]["code"], "PROPOSAL_CANCELLED_TERMINAL")

    def test_administrative_correction_rolls_back_projection_when_audit_fails(self):
        headers = self._headers()
        proposal = self._proposal_ready_for_expedition(
            "CP05004",
            headers,
            [_item_payload("1", requires_galvanization=False)],
        )
        asyncio.run(
            self._force_projection(
                proposal["id"],
                current_area="PRODUCAO",
                current_status="FINALIZADO",
                general_status="EM_PRODUCAO",
                shipping_status=None,
            )
        )
        before = self.client.get(f"/api/v1/proposals/{proposal['id']}", headers=headers).json()
        with patch(
            "api.app.modules.proposals.service._record_event",
            new=AsyncMock(side_effect=RuntimeError("audit unavailable")),
        ):
            with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
                self.client.post(
                    f"/api/v1/proposals/{proposal['id']}/administrative-correction",
                    json={
                        "expected_version": before["version"],
                        "to_area": "EXPEDICAO",
                        "to_status": "EM_SEPARACAO",
                        "reason": "Teste de atomicidade da auditoria",
                        "idempotency_key": "admin-correction-rollback-0001",
                    },
                    headers=headers,
                )
        after = self.client.get(f"/api/v1/proposals/{proposal['id']}", headers=headers).json()
        self.assertEqual(after["current_area"], before["current_area"])
        self.assertEqual(after["current_status"], before["current_status"])
        self.assertEqual(after["shipping_status"], before["shipping_status"])
        self.assertEqual(after["version"], before["version"])

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

    async def _proposal_hierarchy(self, proposal_id: int) -> dict:
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            mother = (
                await session.execute(
                    text("SELECT count(*) AS item_count FROM proposal_items WHERE proposal_id = :id"),
                    {"id": proposal_id},
                )
            ).scalar_one()
            children = (
                await session.execute(
                    text(
                        "SELECT p.proposal_number, p.current_area, count(i.id) AS item_count "
                        "FROM proposals p LEFT JOIN proposal_items i ON i.proposal_id = p.id "
                        "WHERE p.parent_proposal_id = :id AND p.active = true "
                        "GROUP BY p.id ORDER BY p.partial_number"
                    ),
                    {"id": proposal_id},
                )
            ).mappings().all()
            return {
                "mother_item_count": int(mother or 0),
                "child_item_count": sum(int(row["item_count"] or 0) for row in children),
                "children": [dict(row) for row in children],
            }

    async def _force_projection(self, proposal_id: int, **fields) -> None:
        allowed = {
            "current_area",
            "current_status",
            "general_status",
            "production_status",
            "galvanization_status",
            "shipping_status",
            "flow_situation",
        }
        if not fields or not set(fields).issubset(allowed):
            raise AssertionError("Projection test helper received an unsupported field.")
        assignments = ", ".join(f"{field} = :{field}" for field in fields)
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            await session.execute(
                text(f"UPDATE proposals SET {assignments} WHERE id = :proposal_id"),
                {**fields, "proposal_id": proposal_id},
            )
            await session.commit()

    async def _administrative_event_metadata(self, proposal_id: int) -> dict:
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT metadata FROM proposal_events "
                    "WHERE proposal_id = :proposal_id "
                    "AND event_type = 'PROPOSAL_ADMINISTRATIVE_CORRECTION' "
                    "ORDER BY id DESC LIMIT 1"
                ),
                {"proposal_id": proposal_id},
            )
            return dict(result.scalar_one())

    async def _galvanization_load_update_metadata(self, load_id: int) -> dict:
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT metadata FROM galvanization_load_events "
                    "WHERE load_id = :load_id "
                    "AND event_type = 'GALVANIZATION_LOAD_UPDATED' "
                    "ORDER BY id DESC LIMIT 1"
                ),
                {"load_id": load_id},
            )
            return dict(result.scalar_one())

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
