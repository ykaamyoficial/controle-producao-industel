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
        return {"proposal_id": data["id"], "proposal_item_id": data["items"][0]["id"], "version": data["version"]}

    def _release_to_production(self, proposal: dict, headers: dict) -> dict:
        response = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/status",
            json={"version": proposal["version"], "to_area": "PRODUCAO", "to_status": "LIBERADO_PRODUCAO", "reason": "Liberacao"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _ready_proposal_item(self, headers: dict, proposal_number: str, *, quantity: str = "100.0000") -> dict:
        """Cria uma proposta, libera para producao e conclui o unico item -
        deixa o item elegivel para galvanizacao (produced=True,
        requires_galvanization=SIM, flow_defined=True, galvanized=False),
        mesmo criterio de _eligible_galvanization_items."""
        created = self.client.post("/api/v1/proposals", json=_proposal_payload(proposal_number, [_item_payload("1", quantity=quantity)]), headers=headers).json()
        released = self._release_to_production(created, headers)
        started = self.client.post(f"/api/v1/production/proposals/{created['id']}/start", json={"version": released["version"]}, headers=headers).json()
        done = self.client.post(f"/api/v1/production/proposals/{created['id']}/complete-items", json={"version": started["version"]}, headers=headers)
        self.assertEqual(done.status_code, 200, done.text)
        data = done.json()
        return {"proposal_id": data["id"], "proposal_item_id": data["items"][0]["id"]}

    def _create_real_galvanization_load(self, headers: dict, proposal_item_id: int, sent_quantity: str) -> dict:
        created = self.client.post(
            "/api/v1/galvanization/loads",
            json={"driver_name": "Motorista Teste", "items": [{"proposal_item_id": proposal_item_id, "sent_quantity": sent_quantity}]},
            headers=headers,
        )
        self.assertEqual(created.status_code, 201, created.text)
        return created.json()

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

    def test_availability_becomes_ready_after_production_completes(self):
        headers = self._admin_headers()
        item = self._create_proposal_item(headers, "PLPL0010", quantity="100.0000")

        created = self.client.post(
            "/api/v1/planned-loads",
            json={"items": [{"proposal_item_id": item["proposal_item_id"], "planned_quantity": "60.0000"}]},
            headers=headers,
        ).json()
        self.assertEqual(created["status"], "Planejamento")
        self.assertEqual(created["items"][0]["currently_available_quantity"], "0")
        self.assertEqual(created["total_available_quantity"], "0")

        # Ainda em producao: recarregar nao deve mudar nada por si so.
        still_pending = self.client.get(f"/api/v1/planned-loads/{created['id']}", headers=headers).json()
        self.assertEqual(still_pending["status"], "Planejamento")

        # Encerra a producao de um item de OUTRA proposta, apenas para provar
        # que o planejamento so reage ao seu proprio item_id.
        self._ready_proposal_item(headers, "PLPL0010-OUTRA")
        unaffected = self.client.get(f"/api/v1/planned-loads/{created['id']}", headers=headers).json()
        self.assertEqual(unaffected["status"], "Planejamento")

        # Marca a producao do PROPRIO item planejado como concluida via o
        # fluxo real de producao (start + complete-items na mesma proposta).
        proposal = self.client.get(f"/api/v1/proposals/{item['proposal_id']}", headers=headers).json()
        released = self._release_to_production(proposal, headers)
        started = self.client.post(f"/api/v1/production/proposals/{item['proposal_id']}/start", json={"version": released["version"]}, headers=headers).json()
        done = self.client.post(f"/api/v1/production/proposals/{item['proposal_id']}/complete-items", json={"version": started["version"]}, headers=headers)
        self.assertEqual(done.status_code, 200, done.text)

        refreshed = self.client.get(f"/api/v1/planned-loads/{created['id']}", headers=headers).json()
        self.assertEqual(refreshed["status"], "Pronta para montar")
        self.assertEqual(refreshed["items"][0]["currently_available_quantity"], "100.0000")
        self.assertEqual(refreshed["items"][0]["missing_quantity"], "0")
        self.assertFalse(refreshed["items"][0]["has_divergence"])
        self.assertEqual(refreshed["total_available_quantity"], "60.0000")
        self.assertEqual(refreshed["total_missing_quantity"], "0")

    def test_partial_readiness_across_multiple_proposals_matches_product_example(self):
        # Espelha o exemplo do dono do produto: Proposta A 100 (ainda em
        # producao), B 80 (30 prontas), C 50 (ja prontas) -> Planejado 230,
        # Disponivel 80 (30 de B + 50 de C), Parcialmente disponivel.
        headers = self._admin_headers()
        item_a = self._create_proposal_item(headers, "PLPL0011A", quantity="100.0000")
        item_b_ready = self._ready_proposal_item(headers, "PLPL0011B", quantity="30.0000")
        item_c_ready = self._ready_proposal_item(headers, "PLPL0011C", quantity="50.0000")

        created = self.client.post(
            "/api/v1/planned-loads",
            json={
                "items": [
                    {"proposal_item_id": item_a["proposal_item_id"], "planned_quantity": "100.0000"},
                    {"proposal_item_id": item_b_ready["proposal_item_id"], "planned_quantity": "80.0000"},
                    {"proposal_item_id": item_c_ready["proposal_item_id"], "planned_quantity": "50.0000"},
                ]
            },
            headers=headers,
        ).json()
        self.assertEqual(created["status"], "Parcialmente disponível")
        self.assertEqual(created["total_planned_quantity"], "230.0000")
        self.assertEqual(created["total_available_quantity"], "80.0000")
        self.assertEqual(created["total_missing_quantity"], "150.0000")

    def test_missing_quantity_without_divergence_when_consumed_by_real_load(self):
        headers = self._admin_headers()
        ready = self._ready_proposal_item(headers, "PLPL0012", quantity="100.0000")

        created = self.client.post(
            "/api/v1/planned-loads",
            json={"items": [{"proposal_item_id": ready["proposal_item_id"], "planned_quantity": "60.0000"}]},
            headers=headers,
        ).json()
        self.assertEqual(created["items"][0]["currently_available_quantity"], "100.0000")

        # 70 das 100 unidades sao legitimamente enviadas numa carga REAL
        # diferente - o planejamento nunca bloqueia isso.
        self._create_real_galvanization_load(headers, ready["proposal_item_id"], "70.0000")

        refreshed = self.client.get(f"/api/v1/planned-loads/{created['id']}", headers=headers).json()
        item = refreshed["items"][0]
        self.assertEqual(item["currently_available_quantity"], "30.0000")
        self.assertEqual(item["missing_quantity"], "30.0000")
        # Faltante por consumo legitimo NUNCA e divergencia.
        self.assertFalse(item["has_divergence"])
        self.assertIsNone(item["divergence_reason"])
        self.assertEqual(refreshed["status"], "Parcialmente disponível")

    def test_divergence_flagged_when_proposal_cancelled_after_planning_never_auto_corrected(self):
        headers = self._admin_headers()
        ready = self._ready_proposal_item(headers, "PLPL0013", quantity="100.0000")

        created = self.client.post(
            "/api/v1/planned-loads",
            json={"items": [{"proposal_item_id": ready["proposal_item_id"], "planned_quantity": "60.0000"}]},
            headers=headers,
        ).json()
        self.assertFalse(created["items"][0]["has_divergence"])

        proposal = self.client.get(f"/api/v1/proposals/{ready['proposal_id']}", headers=headers).json()
        cancelled = self.client.post(
            f"/api/v1/proposals/{ready['proposal_id']}/cancel",
            json={"version": proposal["version"], "reason": "Cliente desistiu"},
            headers=headers,
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)

        refreshed = self.client.get(f"/api/v1/planned-loads/{created['id']}", headers=headers).json()
        item = refreshed["items"][0]
        self.assertTrue(item["has_divergence"])
        self.assertEqual(item["divergence_reason"], "PROPOSAL_CANCELLED")
        # Nunca corrige/remove sozinho - o item continua no planejamento com
        # a mesma quantidade planejada, aguardando decisao do usuario.
        self.assertEqual(item["planned_quantity"], "60.0000")

    def test_free_for_other_plans_is_soft_commitment_not_a_hard_reservation(self):
        headers = self._admin_headers()
        ready = self._ready_proposal_item(headers, "PLPL0014", quantity="100.0000")

        plan_a = self.client.post(
            "/api/v1/planned-loads",
            json={"items": [{"proposal_item_id": ready["proposal_item_id"], "planned_quantity": "60.0000"}]},
            headers=headers,
        ).json()

        # Criar um segundo planejamento sobre o MESMO item nao e bloqueado -
        # e um comprometimento soft, nao uma reserva operacional.
        plan_b = self.client.post(
            "/api/v1/planned-loads",
            json={"items": [{"proposal_item_id": ready["proposal_item_id"], "planned_quantity": "30.0000"}]},
            headers=headers,
        )
        self.assertEqual(plan_b.status_code, 201, plan_b.text)
        plan_b_body = plan_b.json()

        item_b = plan_b_body["items"][0]
        self.assertEqual(item_b["currently_available_quantity"], "100.0000")
        # Livre para OUTRO planejamento = disponivel(100) - comprometido por
        # OUTROS planos (os 60 do plano A) = 40.
        self.assertEqual(item_b["free_for_other_plans_quantity"], "40.0000")

        refreshed_a = self.client.get(f"/api/v1/planned-loads/{plan_a['id']}", headers=headers).json()
        item_a = refreshed_a["items"][0]
        # Do ponto de vista do plano A: comprometido por outros = 30 (plano B).
        self.assertEqual(item_a["free_for_other_plans_quantity"], "70.0000")

    def test_list_computes_multiple_independent_loads_without_cross_contamination(self):
        """FASE_PL4: GET /planned-loads computa disponibilidade/status de N
        planejamentos numa unica leitura em lote (_annotate_loads, 2 queries
        batidas em vez de N+1). Este teste existe especificamente para pegar
        um bug de atribuicao cruzada entre planejamentos nesse lote - cada
        planejamento tem itens de propostas DIFERENTES e em situacoes
        DIFERENTES (pronta, parcial, nada disponivel), e cada um so pode
        refletir o proprio estado, nunca vazar quantidade/status de outro."""
        headers = self._admin_headers()
        ready_full = self._ready_proposal_item(headers, "PLPL0030A", quantity="50.0000")
        ready_partial = self._ready_proposal_item(headers, "PLPL0030B", quantity="20.0000")
        pending = self._create_proposal_item(headers, "PLPL0030C", quantity="90.0000")

        load_ready = self.client.post(
            "/api/v1/planned-loads",
            json={"items": [{"proposal_item_id": ready_full["proposal_item_id"], "planned_quantity": "50.0000"}]},
            headers=headers,
        ).json()
        load_partial = self.client.post(
            "/api/v1/planned-loads",
            json={"items": [{"proposal_item_id": ready_partial["proposal_item_id"], "planned_quantity": "35.0000"}]},
            headers=headers,
        ).json()
        load_pending = self.client.post(
            "/api/v1/planned-loads",
            json={"items": [{"proposal_item_id": pending["proposal_item_id"], "planned_quantity": "90.0000"}]},
            headers=headers,
        ).json()

        listed = self.client.get("/api/v1/planned-loads", headers=headers).json()
        by_id = {row["id"]: row for row in listed["items"]}

        ready_row = by_id[load_ready["id"]]
        self.assertEqual(ready_row["status"], "Pronta para montar")
        self.assertEqual(ready_row["total_planned_quantity"], "50.0000")
        self.assertEqual(ready_row["total_available_quantity"], "50.0000")
        self.assertEqual(ready_row["total_missing_quantity"], "0")

        partial_row = by_id[load_partial["id"]]
        self.assertEqual(partial_row["status"], "Parcialmente disponível")
        self.assertEqual(partial_row["total_planned_quantity"], "35.0000")
        self.assertEqual(partial_row["total_available_quantity"], "20.0000")
        self.assertEqual(partial_row["total_missing_quantity"], "15.0000")

        pending_row = by_id[load_pending["id"]]
        self.assertEqual(pending_row["status"], "Planejamento")
        self.assertEqual(pending_row["total_planned_quantity"], "90.0000")
        self.assertEqual(pending_row["total_available_quantity"], "0")
        self.assertEqual(pending_row["total_missing_quantity"], "90.0000")

        # O detalhe individual (get_planned_load_detail, caminho NAO batido)
        # precisa bater exatamente com o que a listagem batida (list_planned_loads)
        # computou para o mesmo planejamento - as duas rotas de calculo nunca
        # podem divergir.
        detail_partial = self.client.get(f"/api/v1/planned-loads/{load_partial['id']}", headers=headers).json()
        self.assertEqual(detail_partial["status"], partial_row["status"])
        self.assertEqual(detail_partial["total_available_quantity"], partial_row["total_available_quantity"])

    def test_list_filters_by_derived_status(self):
        headers = self._admin_headers()
        pending = self._create_proposal_item(headers, "PLPL0015")
        ready = self._ready_proposal_item(headers, "PLPL0016")

        self.client.post(
            "/api/v1/planned-loads",
            json={"items": [{"proposal_item_id": pending["proposal_item_id"], "planned_quantity": "10.0000"}]},
            headers=headers,
        )
        self.client.post(
            "/api/v1/planned-loads",
            json={"items": [{"proposal_item_id": ready["proposal_item_id"], "planned_quantity": "10.0000"}]},
            headers=headers,
        )

        planning_only = self.client.get("/api/v1/planned-loads", params={"status": "Planejamento"}, headers=headers).json()
        self.assertEqual(planning_only["total"], 1)

        ready_only = self.client.get("/api/v1/planned-loads", params={"status": "Pronta para montar"}, headers=headers).json()
        self.assertEqual(ready_only["total"], 1)

    def test_cancel_planned_load_blocks_further_edits(self):
        headers = self._admin_headers()
        item = self._create_proposal_item(headers, "PLPL0020")
        created = self.client.post(
            "/api/v1/planned-loads",
            json={"items": [{"proposal_item_id": item["proposal_item_id"], "planned_quantity": "10.0000"}]},
            headers=headers,
        ).json()

        stale = self.client.post(f"/api/v1/planned-loads/{created['id']}/cancel", json={"version": created["version"] + 1}, headers=headers)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["error"]["code"], "PLANNED_LOAD_VERSION_CONFLICT")

        cancelled = self.client.post(f"/api/v1/planned-loads/{created['id']}/cancel", json={"version": created["version"]}, headers=headers)
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["status"], "Cancelada")

        blocked_update = self.client.patch(f"/api/v1/planned-loads/{created['id']}", json={"version": cancelled.json()["version"], "notes": "x"}, headers=headers)
        self.assertEqual(blocked_update.status_code, 409)
        self.assertEqual(blocked_update.json()["error"]["code"], "PLANNED_LOAD_ALREADY_CANCELLED")

        double_cancel = self.client.post(f"/api/v1/planned-loads/{created['id']}/cancel", json={"version": cancelled.json()["version"]}, headers=headers)
        self.assertEqual(double_cancel.status_code, 409)
        self.assertEqual(double_cancel.json()["error"]["code"], "PLANNED_LOAD_ALREADY_CANCELLED")

    def test_build_reports_empty_full_and_partial_availability(self):
        headers = self._admin_headers()

        empty = self.client.post("/api/v1/planned-loads", json={"items": []}, headers=headers).json()
        empty_build = self.client.post(f"/api/v1/planned-loads/{empty['id']}/build", headers=headers)
        self.assertEqual(empty_build.status_code, 409)
        self.assertEqual(empty_build.json()["error"]["code"], "PLANNED_LOAD_BUILD_EMPTY")

        ready = self._ready_proposal_item(headers, "PLPL0021", quantity="100.0000")
        full = self.client.post(
            "/api/v1/planned-loads",
            json={"items": [{"proposal_item_id": ready["proposal_item_id"], "planned_quantity": "60.0000"}]},
            headers=headers,
        ).json()
        full_build = self.client.post(f"/api/v1/planned-loads/{full['id']}/build", headers=headers)
        self.assertEqual(full_build.status_code, 200, full_build.text)
        full_body = full_build.json()
        self.assertTrue(full_body["fully_available"])
        self.assertEqual(len(full_body["ready_items"]), 1)
        self.assertEqual(full_body["ready_items"][0]["available_quantity"], "60.0000")
        self.assertEqual(len(full_body["pending_items"]), 0)

        pending_item = self._create_proposal_item(headers, "PLPL0022", quantity="100.0000")
        partial = self.client.post(
            "/api/v1/planned-loads",
            json={"items": [{"proposal_item_id": pending_item["proposal_item_id"], "planned_quantity": "40.0000"}]},
            headers=headers,
        ).json()
        partial_build = self.client.post(f"/api/v1/planned-loads/{partial['id']}/build", headers=headers)
        self.assertEqual(partial_build.status_code, 200, partial_build.text)
        partial_body = partial_build.json()
        self.assertFalse(partial_body["fully_available"])
        self.assertEqual(len(partial_body["pending_items"]), 1)
        self.assertEqual(partial_body["pending_items"][0]["missing_quantity"], "40.0000")

        # /build so avalia - nunca cria a carga real nem muda o status persistido.
        detail_after_build = self.client.get(f"/api/v1/planned-loads/{full['id']}", headers=headers).json()
        self.assertIsNone(detail_after_build["converted_load_id"])
        self.assertGreaterEqual(len(detail_after_build["history"]), 2)  # CREATED + BUILD_EVALUATED

    def test_mark_converted_is_idempotent_and_conflicts_on_mismatch(self):
        headers = self._admin_headers()
        ready = self._ready_proposal_item(headers, "PLPL0023", quantity="200.0000")
        created = self.client.post(
            "/api/v1/planned-loads",
            json={"items": [{"proposal_item_id": ready["proposal_item_id"], "planned_quantity": "60.0000"}]},
            headers=headers,
        ).json()
        build = self.client.post(f"/api/v1/planned-loads/{created['id']}/build", headers=headers)
        self.assertTrue(build.json()["fully_available"])

        real_load = self._create_real_galvanization_load(headers, ready["proposal_item_id"], "60.0000")

        invalid = self.client.post(
            f"/api/v1/planned-loads/{created['id']}/mark-converted",
            json={"version": created["version"], "real_load_id": 999999},
            headers=headers,
        )
        self.assertEqual(invalid.status_code, 409)
        self.assertEqual(invalid.json()["error"]["code"], "PLANNED_LOAD_INVALID_STATE")

        converted = self.client.post(
            f"/api/v1/planned-loads/{created['id']}/mark-converted",
            json={"version": created["version"], "real_load_id": real_load["id"]},
            headers=headers,
        )
        self.assertEqual(converted.status_code, 200, converted.text)
        self.assertEqual(converted.json()["status"], "Convertida em carga")
        self.assertEqual(converted.json()["converted_load_id"], real_load["id"])

        # Duplo-clique com o MESMO real_load_id -> sucesso idempotente, sem duplicar historico.
        history_len = len(converted.json()["history"])
        retried = self.client.post(
            f"/api/v1/planned-loads/{created['id']}/mark-converted",
            json={"version": created["version"], "real_load_id": real_load["id"]},
            headers=headers,
        )
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(len(retried.json()["history"]), history_len)

        # Um real_load_id DIFERENTE do ja registrado e conflito de verdade.
        another_real_load = self._create_real_galvanization_load(headers, ready["proposal_item_id"], "60.0000")
        conflicting = self.client.post(
            f"/api/v1/planned-loads/{created['id']}/mark-converted",
            json={"version": created["version"], "real_load_id": another_real_load["id"]},
            headers=headers,
        )
        self.assertEqual(conflicting.status_code, 409)
        self.assertEqual(conflicting.json()["error"]["code"], "PLANNED_LOAD_ALREADY_CONVERTED")

        # Planejamento convertido tambem bloqueia build/cancel/edicao.
        blocked_build = self.client.post(f"/api/v1/planned-loads/{created['id']}/build", headers=headers)
        self.assertEqual(blocked_build.status_code, 409)
        self.assertEqual(blocked_build.json()["error"]["code"], "PLANNED_LOAD_ALREADY_CONVERTED")

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

        blocked_build = self.client.post(f"/api/v1/planned-loads/{planned_load_id}/build", headers=viewer_headers)
        self.assertEqual(blocked_build.status_code, 403)

        blocked_cancel = self.client.post(f"/api/v1/planned-loads/{planned_load_id}/cancel", json={"version": 1}, headers=viewer_headers)
        self.assertEqual(blocked_cancel.status_code, 403)

        blocked_convert = self.client.post(f"/api/v1/planned-loads/{planned_load_id}/mark-converted", json={"version": 1, "real_load_id": 1}, headers=viewer_headers)
        self.assertEqual(blocked_convert.status_code, 403)


if __name__ == "__main__":
    unittest.main()
