"""Desfazer a ultima acao da proposta - integracao HTTP + PostgreSQL descartavel.

Exige APP_ENV=test e POSTGRES_TEST_DATABASE_URL (banco com "test" no nome); o setUpClass derruba e recria o
schema (alembic downgrade base/upgrade head), como test_proposals_integration.py. Regras puras: test_proposal_undo_rules.py.
"""

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
from api.app.modules.auth import permissions as perms
from api.app.modules.auth.models import Permission, Role, User
from api.app.modules.auth.permissions import ADMIN_PERMISSION_CODES
from api.app.modules.auth.security import hash_password
from api.app.modules.auth.tokens import utcnow


ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "api"
TEST_DATABASE_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL", "")
PASSWORD = "Senha forte undo 12345"
STATE_FIELDS = (
    "current_area", "current_status", "general_status", "production_status", "galvanization_status",
    "shipping_status", "warehouse_status", "flow_situation", "has_production_pending", "is_completed",
)


def _database_name(url: str) -> str:
    return urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1)).path.lstrip("/")


def _integration_enabled() -> bool:
    return bool(TEST_DATABASE_URL) and os.environ.get("APP_ENV") == "test" and "test" in _database_name(TEST_DATABASE_URL).lower()


def _alembic_config() -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    return config


def _item(number: str, *, quantity: str = "2.0000", galvanization: bool = False) -> dict:
    return {
        "item_number": number, "product_code": "COD", "description": f"Item {number}", "quantity": quantity, "unit": "un",
        "unit_weight": "3.5000", "total_weight": "7.0000", "produce_internally": True, "requires_galvanization": galvanization,
    }


def _payload(number: str, items: list[dict] | None = None) -> dict:
    return {
        "proposal_number": number, "customer_name": "Cliente", "project_name": "Obra", "purchase_order": "PC1",
        "batch_reference": "L1", "proposal_date": "2026-07-20", "deadline_date": "2026-07-30", "source": "MANUAL",
        "notes": "Criada pelo teste", "items": items or [_item("1")],
    }


HANDLER_CLASSES = {
    "RELEASE_PROPOSAL": "C", "WAREHOUSE_STATUS": "A", "START_PRODUCTION": "A", "PAUSE_PRODUCTION": "A",
    "RESUME_PRODUCTION": "A", "START_SEPARATION": "B", "SEPARATE_ITEMS": "B",
}
HANDLER_PERMISSIONS = {
    "RELEASE_PROPOSAL": perms.PROPOSALS_CHANGE_STATUS, "WAREHOUSE_STATUS": perms.PROPOSALS_CHANGE_STATUS,
    "START_PRODUCTION": perms.PRODUCTION_UPDATE, "PAUSE_PRODUCTION": perms.PRODUCTION_UPDATE,
    "RESUME_PRODUCTION": perms.PRODUCTION_UPDATE, "START_SEPARATION": perms.EXPEDITION_UPDATE,
    "SEPARATE_ITEMS": perms.EXPEDITION_UPDATE,
}


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class ProposalUndoIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {key: os.environ.get(key) for key in ("DATABASE_URL", "APP_ENV", "SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "proposal-undo-secret-key-more-than-32-chars"
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
        self._rid = 0
        self.admin = self._login("admin")

    # ---- infraestrutura ----

    async def _seed_admin(self):
        async with get_engine().begin() as conn:
            await conn.execute(text(
                "TRUNCATE TABLE notifications, security_events, auth_sessions, fiscal_events, fiscal_invoice_items, fiscal_invoices, "
                "fiscal_items, fiscal_records, expedition_events, expedition_items, galvanization_load_events, galvanization_load_items, "
                "galvanization_loads, proposal_events, proposal_items, proposals, sync_runs, role_permissions, user_roles, users, roles "
                "RESTART IDENTITY CASCADE"
            ))
        async with get_sessionmaker()() as session:
            permissions = (await session.execute(select(Permission).where(Permission.code.in_(ADMIN_PERMISSION_CODES)))).scalars().all()
            role = Role(code="admin", name="Administrador", active=True, system_role=True)
            role.permissions.extend(permissions)
            user = User(username="admin", display_name="Administrador", password_hash=hash_password(PASSWORD), active=True, is_superuser=True, password_changed_at=utcnow())
            user.roles.append(role)
            session.add(user)
            await session.commit()

    async def _create_user(self, username: str, codes: set[str]) -> int:
        async with get_sessionmaker()() as session:
            role = Role(code=f"role_{username}", name=f"Papel {username}", active=True, system_role=False)
            if codes:
                role.permissions.extend((await session.execute(select(Permission).where(Permission.code.in_(codes)))).scalars().all())
            user = User(username=username, display_name=username.capitalize(), password_hash=hash_password(PASSWORD), active=True, is_superuser=False, password_changed_at=utcnow())
            user.roles.append(role)
            session.add(user)
            await session.commit()
            return int(role.id)

    def _login(self, username: str) -> dict:
        login = self.client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
        self.assertEqual(login.status_code, 200, login.text)
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    def _user(self, username: str, codes: set[str]) -> tuple[dict, int]:
        role_id = asyncio.run(self._create_user(username, codes))
        return self._login(username), role_id

    def _sql(self, statement: str, **params):
        async def run():
            async with get_engine().begin() as conn:
                result = await conn.execute(text(statement), params)
                return result.fetchall() if result.returns_rows else []
        return asyncio.run(run())

    def _post(self, path: str, body: dict, headers: dict | None = None, rid: str | None = None):
        self._rid += 1
        merged = {**(headers or self.admin), "X-Request-ID": rid or f"act-{self._rid:04d}"}
        return self.client.post(f"/api/v1{path}", json=body, headers=merged)

    def _get(self, path: str, headers: dict | None = None, **params):
        return self.client.get(f"/api/v1{path}", headers=headers or self.admin, params=params)

    def _proposal(self, pid: int) -> dict:
        return self._get(f"/proposals/{pid}").json()

    def _create(self, number: str, items: list[dict] | None = None) -> int:
        created = self.client.post("/api/v1/proposals", json=_payload(number, items), headers=self.admin)
        self.assertEqual(created.status_code, 201, created.text)
        return created.json()["id"]

    def _release(self, pid: int, headers=None, rid=None):
        return self._post(f"/proposals/{pid}/status", {"version": self._proposal(pid)["version"], "to_area": "PRODUCAO", "to_status": "LIBERADO_PRODUCAO", "reason": "Liberacao"}, headers, rid)

    def _production(self, pid: int, action: str, headers=None, rid=None, **extra):
        body = {"version": self._proposal(pid)["version"], **extra}
        if action == "pause":
            body["reason"] = "Falta de material"
        return self._post(f"/production/proposals/{pid}/{action}", body, headers, rid)

    def _expedition(self, pid: int, action: str, headers=None, rid=None, **extra):
        return self._post(f"/shipping/proposals/{pid}/{action}", {"version": self._proposal(pid)["version"], **extra}, headers, rid)

    def _ready_for_expedition(self, number: str, items: list[dict] | None = None) -> int:
        pid = self._create(number, items)
        self.assertEqual(self._release(pid).status_code, 200)
        self.assertEqual(self._production(pid, "start").status_code, 200)
        done = self._post(f"/production/proposals/{pid}/complete-items", {"version": self._proposal(pid)["version"]})
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json()["current_area"], "EXPEDICAO")
        return pid

    def _candidate(self, pid: int, headers=None, lane: str | None = None) -> dict:
        # lane vai em params: com `params={}` (sem filtros) o httpx 0.28 descarta a query string da URL.
        response = self._get(f"/proposals/{pid}/undo/candidate", headers, **({"lane": lane} if lane else {}))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _undo(self, pid: int, target: str, headers=None, *, key: str | None = None, reason: str = "Fiz errado", version: int | None = None):
        self._rid += 1
        return self.client.post(
            f"/api/v1/proposals/{pid}/undo",
            json={
                "expected_version": version if version is not None else self._proposal(pid)["version"],
                "target_request_id": target, "reason": reason, "idempotency_key": key or f"undo-key-{self._rid:05d}",
            },
            headers={**(headers or self.admin), "X-Request-ID": f"undo-{self._rid:04d}"},
        )

    def _state(self, pid: int) -> dict:
        proposal = self._proposal(pid)
        return {name: proposal[name] for name in STATE_FIELDS}

    def _shipping_items(self, pid: int) -> list[tuple]:
        detail = self._get(f"/shipping/proposals/{pid}").json()
        return [(row["item_number"], row["status"], row["separated_quantity"]) for row in detail["items"]]

    def _events(self, pid: int, event_type: str) -> list:
        return self._sql("SELECT id, request_id, metadata FROM proposal_events WHERE proposal_id = :p AND event_type = :t ORDER BY id", p=pid, t=event_type)

    # ---- candidato ----

    def test_candidato_da_liberacao_traz_mudancas_efeitos_e_classe(self):
        pid = self._create("UNDO-001")
        released = self._release(pid, rid="rid-liberacao")
        self.assertEqual(released.status_code, 200)

        candidate = self._candidate(pid)
        self.assertEqual(candidate["proposal_id"], pid)
        self.assertEqual(candidate["proposal_version"], released.json()["version"])
        self.assertEqual(candidate["handler"], "RELEASE_PROPOSAL")
        self.assertEqual(candidate["undo_class"], "C")
        self.assertTrue(candidate["undoable"] and candidate["can_undo"])
        self.assertIsNone(candidate["cannot_undo_reason"])
        self.assertEqual(candidate["blockers"], [])
        self.assertEqual(candidate["action"]["request_id"], "rid-liberacao")
        self.assertEqual(candidate["action"]["event_type"], "PROPOSAL_STATUS_CHANGED")
        self.assertEqual(candidate["action"]["label"], "Liberacao da proposta")
        self.assertEqual(candidate["action"]["actor_name"], "Administrador")
        self.assertIn("atualizou o status", candidate["action"]["title"])
        changes = {row["field"]: row for row in candidate["changes"]}
        self.assertEqual(changes["current_area"]["label"], "Area atual")
        self.assertEqual(changes["current_area"]["current_value"], "PRODUCAO")
        self.assertEqual(changes["current_area"]["restored_value"], "CONTROLE_GERAL")
        self.assertEqual(candidate["side_effects"], [{"code": "ALMOX_NOT_NOTIFIED", "message": "O Almox+ nao e avisado; a conciliacao horaria acerta."}])

    def test_candidato_por_tipo_de_acao(self):
        pid = self._create("UNDO-002")
        self._release(pid)
        expected = [("start", "START_PRODUCTION", "A"), ("pause", "PAUSE_PRODUCTION", "A"), ("resume", "RESUME_PRODUCTION", "A")]
        for action, handler, undo_class in expected:
            with self.subTest(action=action):
                self.assertEqual(self._production(pid, action).status_code, 200)
                candidate = self._candidate(pid)
                self.assertEqual((candidate["handler"], candidate["undo_class"], candidate["can_undo"]), (handler, undo_class, True))
        warehouse = self._post(f"/warehouse/proposals/{pid}/status", {"version": self._proposal(pid)["version"], "status": "EM_SEPARACAO", "observation": "ok"})
        self.assertEqual(warehouse.status_code, 200, warehouse.text)
        # Almoxarifado tem pilha propria: nao vira a "ultima acao" do fluxo geral (continua sendo a retomada).
        self.assertEqual(self._candidate(pid)["handler"], "RESUME_PRODUCTION")
        candidate = self._candidate(pid, lane="ALMOXARIFADO")
        self.assertEqual((candidate["handler"], candidate["undo_class"], candidate["lane"]), ("WAREHOUSE_STATUS", "A", "ALMOXARIFADO"))
        self.assertEqual(candidate["changes"][0]["restored_value"], "NAO_DEFINIDO")
        self.assertIsNone(self._candidate(pid, lane="FISCAL")["action"])

    def test_acao_do_fluxo_geral_nao_trava_o_desfazer_do_almoxarifado(self):
        pid = self._create("UNDO-004")
        self._release(pid)
        self.assertEqual(self._post(f"/warehouse/proposals/{pid}/status", {"version": self._proposal(pid)["version"], "status": "EM_SEPARACAO"}, rid="rid-wh").status_code, 200)
        self.assertEqual(self._production(pid, "start", rid="rid-start").status_code, 200)
        # a producao veio depois, mas o Almox desfaz o seu proprio status sem desfazer a producao
        self.assertEqual(self._undo(pid, "rid-wh").status_code, 200)
        self.assertEqual(self._proposal(pid)["production_status"], "INICIADO")
        # e a producao desfaz a sua acao mesmo com uma acao do Almox mais recente
        self.assertEqual(self._post(f"/warehouse/proposals/{pid}/status", {"version": self._proposal(pid)["version"], "status": "EM_SEPARACAO"}, rid="rid-wh2").status_code, 200)
        self.assertEqual(self._undo(pid, "rid-start").status_code, 200)

    def test_acoes_fora_da_v1_vem_com_action_e_undoable_false(self):
        pid = self._create("UNDO-003")
        candidate = self._candidate(pid)
        self.assertEqual(candidate["action"]["event_type"], "PROPOSAL_CREATED")
        self.assertFalse(candidate["undoable"] or candidate["can_undo"])
        self.assertIsNone(candidate["handler"])
        self.assertIn("desative a proposta", candidate["cannot_undo_reason"])

        cancelled = self._post(f"/proposals/{pid}/cancel", {"version": self._proposal(pid)["version"], "reason": "Engano"}, rid="rid-cancel")
        self.assertEqual(cancelled.status_code, 200)
        candidate = self._candidate(pid)
        self.assertEqual(candidate["action"]["request_id"], "rid-cancel")
        self.assertEqual(candidate["action"]["label"], "Cancelamento da proposta")
        self.assertFalse(candidate["undoable"])
        self.assertIn("nao pode ser reativada", candidate["cannot_undo_reason"])
        self.assertEqual((candidate["blockers"], candidate["changes"], candidate["side_effects"]), ([], [], []))

        refused = self._undo(pid, "rid-cancel")
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.json()["error"]["code"], "UNDO_NOT_SUPPORTED")
        self.assertTrue(self._proposal(pid)["is_cancelled"])

    def test_acao_antiga_sem_snapshot_nao_e_desfazivel(self):
        pid = self._create("UNDO-004")
        self._release(pid, rid="rid-antiga")
        self._sql("UPDATE proposal_events SET metadata = metadata - 'previous_state' WHERE request_id = 'rid-antiga'")
        candidate = self._candidate(pid)
        self.assertEqual(candidate["handler"], "RELEASE_PROPOSAL")
        self.assertFalse(candidate["undoable"])
        self.assertIn("antes do recurso de desfazer", candidate["cannot_undo_reason"])
        refused = self._undo(pid, "rid-antiga")
        self.assertEqual((refused.status_code, refused.json()["error"]["code"]), (409, "UNDO_NOT_SUPPORTED"))

    def test_liberacao_com_evento_extra_nao_e_desfazivel(self):
        pid = self._create("UNDO-005")
        self._release(pid, rid="rid-composta")
        self._sql(
            "INSERT INTO proposal_events (proposal_id, event_type, request_id, created_at) VALUES (:p, 'PRODUCTION_FLOW_AUTO_ROUTED', 'rid-composta', now())", p=pid,
        )
        candidate = self._candidate(pid)
        self.assertFalse(candidate["undoable"])
        self.assertIn("outras partes", candidate["cannot_undo_reason"])

    # ---- desfazer: caminho feliz por acao ----

    def test_desfazer_liberacao_restaura_e_permite_editar_e_liberar_de_novo(self):
        pid = self._create("UNDO-010")
        before = self._state(pid)
        self._release(pid, rid="rid-lib")
        version = self._proposal(pid)["version"]

        response = self._undo(pid, "rid-lib", reason="Liberei a proposta errada")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual({name: body[name] for name in STATE_FIELDS}, before)
        self.assertEqual(body["version"], version + 1)

        edit = self.client.patch(f"/api/v1/proposals/{pid}", json={"version": body["version"], "customer_name": "Cliente corrigido"}, headers=self.admin)
        self.assertEqual(edit.status_code, 200, edit.text)
        self.assertEqual(self._release(pid).status_code, 200)

        events = self._events(pid, "ACTION_UNDONE")
        self.assertEqual(len(events), 1)
        metadata = events[0].metadata
        self.assertEqual(metadata["undone_request_id"], "rid-lib")
        self.assertEqual(metadata["handler"], "RELEASE_PROPOSAL")
        self.assertEqual(metadata["reason"], "Liberei a proposta errada")
        self.assertEqual(metadata["expected_version"], version)
        self.assertEqual(metadata["resulting_version"], version + 1)
        self.assertEqual(metadata["before_snapshot"]["proposal"]["current_area"], "PRODUCAO")
        self.assertEqual(metadata["after_snapshot"]["proposal"]["current_area"], "CONTROLE_GERAL")
        self.assertTrue(metadata["undone_events"])
        self.assertTrue(events[0].request_id.startswith("undo-"))

    def test_desfazer_status_almoxarifado_e_producao_restauram_o_estado_exato(self):
        pid = self._create("UNDO-011")
        self._release(pid)
        nothing = lambda: None  # noqa: E731
        scenarios = [
            ("start", nothing, lambda: self._production(pid, "start", rid="rid-start"), "rid-start"),
            ("pause", lambda: self._production(pid, "start"), lambda: self._production(pid, "pause", rid="rid-pause"), "rid-pause"),
            ("resume", nothing, lambda: self._production(pid, "resume", rid="rid-resume"), "rid-resume"),
            ("warehouse", nothing, lambda: self._post(f"/warehouse/proposals/{pid}/status", {"version": self._proposal(pid)["version"], "status": "EM_SEPARACAO"}, rid="rid-wh"), "rid-wh"),
        ]
        for name, prep, act, rid in scenarios:
            with self.subTest(action=name):
                prep()
                if name == "resume":  # retomar exige producao pausada; o desfazer da pausa deixou iniciada
                    self.assertEqual(self._production(pid, "pause").status_code, 200)
                before = self._state(pid)
                self.assertEqual(act().status_code, 200)
                self.assertNotEqual(self._state(pid), before)
                response = self._undo(pid, rid)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(self._state(pid), before)

    def test_desfazer_iniciar_producao_volta_a_poder_iniciar(self):
        pid = self._create("UNDO-012")
        self._release(pid)
        self._production(pid, "start", rid="rid-start")
        self.assertEqual(self._undo(pid, "rid-start").status_code, 200)
        self.assertEqual(self._proposal(pid)["production_status"], "NAO_INICIADO")
        self.assertEqual(self._production(pid, "start").status_code, 200)

    def test_desfazer_iniciar_separacao_e_separar_itens_restauram_itens_e_proposta(self):
        pid = self._ready_for_expedition("UNDO-013", [_item("1"), _item("2", quantity="4.0000")])
        before_state, before_items = self._state(pid), self._shipping_items(pid)

        self.assertEqual(self._expedition(pid, "start-separation", rid="rid-sep-ini").status_code, 200)
        self.assertEqual(self._shipping_items(pid)[0][1], "SEPARACAO_INICIADA")
        started_state, started_items = self._state(pid), self._shipping_items(pid)

        items = self._get(f"/shipping/proposals/{pid}").json()["items"]
        separated = self._expedition(pid, "separate-items", rid="rid-sep", items=[{"expedition_item_id": items[1]["id"], "quantity": "1"}])
        self.assertEqual(separated.status_code, 200, separated.text)
        self.assertNotEqual(self._shipping_items(pid), started_items)

        candidate = self._candidate(pid)
        self.assertEqual((candidate["handler"], candidate["undo_class"]), ("SEPARATE_ITEMS", "B"))
        self.assertIn("items[2].separated_quantity", {row["field"] for row in candidate["changes"]})

        # pilha: nao da para desfazer o inicio da separacao antes da separacao
        blocked = self._undo(pid, "rid-sep-ini")
        self.assertEqual((blocked.status_code, blocked.json()["error"]["code"]), (409, "UNDO_NOT_LATEST"))
        self.assertEqual(blocked.json()["error"]["details"], {"latest_request_id": "rid-sep"})

        self.assertEqual(self._undo(pid, "rid-sep").status_code, 200)
        self.assertEqual(self._state(pid), started_state)
        self.assertEqual(self._shipping_items(pid), started_items)

        candidate = self._candidate(pid)
        self.assertEqual(candidate["handler"], "START_SEPARATION")
        self.assertEqual(self._undo(pid, "rid-sep-ini").status_code, 200)
        self.assertEqual(self._state(pid), before_state)
        self.assertEqual(self._shipping_items(pid), before_items)
        # e a expedicao segue funcionando depois do desfazer
        self.assertEqual(self._expedition(pid, "start-separation").status_code, 200)

    # ---- pilha, repeticao, versao, idempotencia ----

    def test_pilha_lifo_ja_desfeita_e_nao_encontrada(self):
        pid = self._create("UNDO-020")
        self._release(pid, rid="rid-1")
        self._production(pid, "start", rid="rid-2")

        not_latest = self._undo(pid, "rid-1")
        self.assertEqual((not_latest.status_code, not_latest.json()["error"]["code"]), (409, "UNDO_NOT_LATEST"))
        self.assertEqual(not_latest.json()["error"]["details"], {"latest_request_id": "rid-2"})

        missing = self._undo(pid, "nao-existe")
        self.assertEqual((missing.status_code, missing.json()["error"]["code"]), (404, "UNDO_ACTION_NOT_FOUND"))

        self.assertEqual(self._undo(pid, "rid-2").status_code, 200)
        again = self._undo(pid, "rid-2")
        self.assertEqual((again.status_code, again.json()["error"]["code"]), (409, "UNDO_ALREADY_UNDONE"))

        # a pilha anda: agora o topo e a liberacao
        self.assertEqual(self._candidate(pid)["action"]["request_id"], "rid-1")
        undo_request = self._events(pid, "ACTION_UNDONE")[0].request_id
        self.assertEqual(self._undo(pid, undo_request).json()["error"]["code"], "UNDO_NOT_SUPPORTED")
        self.assertEqual(self._undo(pid, "rid-1").status_code, 200)
        candidate = self._candidate(pid)
        self.assertEqual(candidate["action"]["event_type"], "PROPOSAL_CREATED")
        self.assertFalse(candidate["undoable"])

    def test_conflito_de_versao(self):
        pid = self._create("UNDO-021")
        self._release(pid, rid="rid-1")
        stale = self._undo(pid, "rid-1", version=self._proposal(pid)["version"] - 1)
        self.assertEqual((stale.status_code, stale.json()["error"]["code"]), (409, "PROPOSAL_VERSION_CONFLICT"))
        self.assertEqual(self._events(pid, "ACTION_UNDONE"), [])

    def test_idempotencia_replay_devolve_estado_atual_e_payload_diferente_conflita(self):
        pid = self._create("UNDO-022")
        self._release(pid, rid="rid-1")
        first = self._undo(pid, "rid-1", key="chave-idempotente-1", reason="Motivo A")
        self.assertEqual(first.status_code, 200)
        version = first.json()["version"]

        replay = self._undo(pid, "rid-1", key="chave-idempotente-1", reason="Motivo A", version=1)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json()["version"], version)
        self.assertEqual(len(self._events(pid, "ACTION_UNDONE")), 1)

        other_reason = self._undo(pid, "rid-1", key="chave-idempotente-1", reason="Motivo B")
        self.assertEqual((other_reason.status_code, other_reason.json()["error"]["code"]), (409, "UNDO_IDEMPOTENCY_CONFLICT"))
        other_target = self._undo(pid, "rid-9", key="chave-idempotente-1", reason="Motivo A")
        self.assertEqual(other_target.json()["error"]["code"], "UNDO_IDEMPOTENCY_CONFLICT")
        self.assertEqual(len(self._events(pid, "ACTION_UNDONE")), 1)

    def test_corpo_invalido_e_rejeitado(self):
        pid = self._create("UNDO-023")
        for body in (
            {"expected_version": 1, "target_request_id": "x", "reason": "", "idempotency_key": "chave-valida-1"},
            {"expected_version": 1, "target_request_id": "x", "reason": "ok", "idempotency_key": "curta"},
            {"expected_version": 1, "target_request_id": "x", "reason": "ok", "idempotency_key": "chave-valida-1", "extra": 1},
            {"expected_version": 0, "target_request_id": "x", "reason": "ok", "idempotency_key": "chave-valida-1"},
        ):
            response = self.client.post(f"/api/v1/proposals/{pid}/undo", json=body, headers=self.admin)
            self.assertEqual(response.status_code, 422, body)

    def test_proposta_inexistente_e_sem_autenticacao(self):
        self.assertEqual(self._get("/proposals/99999/undo/candidate").status_code, 404)
        self.assertEqual(self._undo(99999, "x", version=1).status_code, 404)
        pid = self._create("UNDO-024")
        self.assertEqual(self.client.get(f"/api/v1/proposals/{pid}/undo/candidate").status_code, 401)
        self.assertEqual(self.client.post(f"/api/v1/proposals/{pid}/undo", json={}).status_code, 401)

    # ---- bloqueios ----

    def test_bloqueio_quando_o_estado_mudou_fora_do_historico(self):
        pid = self._create("UNDO-030")
        self._release(pid, rid="rid-1")
        self._sql("UPDATE proposals SET production_status = 'INICIADO' WHERE id = :p", p=pid)
        candidate = self._candidate(pid)
        self.assertTrue(candidate["undoable"])
        self.assertFalse(candidate["can_undo"])
        self.assertEqual({row["code"] for row in candidate["blockers"]}, {"PRODUCTION_ALREADY_STARTED"})
        self.assertEqual(candidate["cannot_undo_reason"], candidate["blockers"][0]["message"])

        blocked = self._undo(pid, "rid-1")
        self.assertEqual((blocked.status_code, blocked.json()["error"]["code"]), (409, "UNDO_BLOCKED"))
        details = blocked.json()["error"]["details"]
        self.assertEqual([row["code"] for row in details["blockers"]], ["PRODUCTION_ALREADY_STARTED"])
        self.assertEqual(self._events(pid, "ACTION_UNDONE"), [])

    def test_bloqueio_em_proposta_cancelada_e_em_item_de_expedicao_alterado(self):
        pid = self._ready_for_expedition("UNDO-031")
        self._expedition(pid, "start-separation", rid="rid-ini")
        self._sql("UPDATE expedition_items SET status = 'SEPARADO' WHERE proposal_id = :p", p=pid)
        blocked = self._undo(pid, "rid-ini")
        self.assertEqual((blocked.status_code, blocked.json()["error"]["code"]), (409, "UNDO_BLOCKED"))
        self.assertEqual(blocked.json()["error"]["details"]["blockers"][0]["code"], "ITEM_CHANGED")

    # ---- permissao ----

    def test_403_por_handler_nao_autor_sem_permissao_e_superusuario_passa(self):
        scenarios = list(HANDLER_CLASSES)
        for name in scenarios:
            with self.subTest(handler=name):
                permission = HANDLER_PERMISSIONS[name]
                author_headers, role_id = self._user(f"autor_{name.lower()}", {permission})
                other_headers, _ = self._user(f"outro_{name.lower()}", {permission})
                nobody_headers, _ = self._user(f"ninguem_{name.lower()}", set())
                pid, rid = self._build_scenario(name, author_headers)
                after_action = self._state(pid)
                version = self._proposal(pid)["version"]

                lane = "ALMOXARIFADO" if name == "WAREHOUSE_STATUS" else None  # o Almoxarifado tem pilha propria
                candidate = self._candidate(pid, author_headers, lane)
                self.assertEqual((candidate["handler"], candidate["undo_class"], candidate["can_undo"]), (name, HANDLER_CLASSES[name], True))
                as_other = self._candidate(pid, other_headers, lane)
                self.assertFalse(as_other["can_undo"])
                self.assertIn("Somente quem fez a acao", as_other["cannot_undo_reason"])
                self.assertFalse(self._candidate(pid, nobody_headers, lane)["can_undo"])

                for headers in (other_headers, nobody_headers):
                    denied = self._undo(pid, rid, headers)
                    self.assertEqual((denied.status_code, denied.json()["error"]["code"]), (403, "PERMISSION_DENIED"))
                # o autor perde a permissao da acao original: continua negado
                self._sql("DELETE FROM role_permissions WHERE role_id = :r", r=role_id)
                lost = self._undo(pid, rid, author_headers)
                self.assertEqual((lost.status_code, lost.json()["error"]["code"]), (403, "PERMISSION_DENIED"))
                self.assertEqual(self._proposal(pid)["version"], version)
                self.assertEqual(self._events(pid, "ACTION_UNDONE"), [])

                allowed = self._undo(pid, rid)  # superusuario
                self.assertEqual(allowed.status_code, 200, allowed.text)
                self.assertNotEqual(self._state(pid), after_action)

    def test_autor_com_permissao_desfaz_a_propria_acao(self):
        headers, _ = self._user("operador_prod", {perms.PRODUCTION_UPDATE})
        pid = self._create("UNDO-040")
        self._release(pid)
        self.assertEqual(self._production(pid, "start", headers, rid="rid-op").status_code, 200)
        response = self._undo(pid, "rid-op", headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["production_status"], "NAO_INICIADO")

    def _build_scenario(self, name: str, author: dict) -> tuple[int, str]:
        """Cria a proposta, leva ate o estado anterior e faz a acao-alvo com o usuario `author`."""
        rid = f"alvo-{name.lower()}"
        number = f"UNDO-P-{name[:8]}"
        if name in ("START_SEPARATION", "SEPARATE_ITEMS"):
            pid = self._ready_for_expedition(number)
            if name == "SEPARATE_ITEMS":
                self.assertEqual(self._expedition(pid, "start-separation").status_code, 200)
            response = self._expedition(pid, "start-separation" if name == "START_SEPARATION" else "separate-items", author, rid)
        else:
            pid = self._create(number)
            if name == "RELEASE_PROPOSAL":
                response = self._release(pid, author, rid)
            else:
                self.assertEqual(self._release(pid).status_code, 200)
                if name == "WAREHOUSE_STATUS":
                    response = self._post(f"/warehouse/proposals/{pid}/status", {"version": self._proposal(pid)["version"], "status": "EM_SEPARACAO"}, author, rid)
                else:
                    if name != "START_PRODUCTION":
                        self.assertEqual(self._production(pid, "start").status_code, 200)
                    if name == "RESUME_PRODUCTION":
                        self.assertEqual(self._production(pid, "pause").status_code, 200)
                    action = {"START_PRODUCTION": "start", "PAUSE_PRODUCTION": "pause", "RESUME_PRODUCTION": "resume"}[name]
                    response = self._production(pid, action, author, rid)
        self.assertEqual(response.status_code, 200, response.text)
        return pid, rid

    # ---- historico ----

    def test_historico_marca_undone_e_undone_by_event_id_sobre_a_familia_inteira(self):
        pid = self._create("UNDO-050")
        self._release(pid, rid="rid-1")
        self._production(pid, "start", rid="rid-2")
        self.assertEqual(self._undo(pid, "rid-2", reason="Iniciei sem querer").status_code, 200)
        undo_event_id = self._events(pid, "ACTION_UNDONE")[0].id

        rows = self._get(f"/proposals/{pid}/history").json()
        by_request = {row["request_id"]: row for row in rows}
        self.assertTrue(by_request["rid-2"]["undone"])
        self.assertEqual(by_request["rid-2"]["undone_by_event_id"], undo_event_id)
        self.assertFalse(by_request["rid-1"]["undone"])
        self.assertIsNone(by_request["rid-1"]["undone_by_event_id"])
        undo_row = next(row for row in rows if row["event_type"] == "ACTION_UNDONE")
        self.assertFalse(undo_row["undone"])
        self.assertEqual(undo_row["title"], 'Administrador desfez a acao "Inicio da producao" (Iniciei sem querer).')
        self.assertEqual(undo_row["detail"], "Iniciei sem querer")
        self.assertNotIn("previous_state", by_request["rid-2"]["observation"] or "")

        # a linha desfeita fica na segunda pagina, longe do ACTION_UNDONE (offset=1, limit=1): ainda vem marcada
        page = self._get(f"/proposals/{pid}/history", limit=1, offset=1).json()
        self.assertEqual(page[0]["request_id"], "rid-2")
        self.assertTrue(page[0]["undone"])
        self.assertEqual(page[0]["undone_by_event_id"], undo_event_id)

        general = self._get("/proposals/history").json()
        self.assertTrue(next(row for row in general if row["request_id"] == "rid-2")["undone"])

    def test_desfeito_tambem_marca_eventos_de_expedicao_do_mesmo_request(self):
        pid = self._ready_for_expedition("UNDO-051")
        self._expedition(pid, "start-separation", rid="rid-exp")
        self.assertEqual(self._undo(pid, "rid-exp").status_code, 200)
        rows = [row for row in self._get(f"/proposals/{pid}/history").json() if row["request_id"] == "rid-exp"]
        self.assertGreaterEqual(len(rows), 2)
        self.assertTrue(all(row["undone"] for row in rows))
        self.assertEqual({row["source"] for row in rows}, {"proposal", "expedition"})

    def test_admin_correction_ignora_producao_desfeita(self):
        pid = self._create("UNDO-052")
        self._release(pid, rid="rid-lib")
        self.assertEqual(self._undo(pid, "rid-lib").status_code, 200)
        facts = self._get(f"/proposals/{pid}/administrative-corrections/options").json()
        self.assertFalse(facts["facts"]["production_released"])
        self.assertEqual(facts["current_state"]["current_area"], "CONTROLE_GERAL")

    # ---- notificacoes ----

    def test_so_o_action_undone_notifica_e_nao_os_eventos_internos(self):
        creator_headers, _ = self._user("criador", {perms.PROPOSALS_CREATE, perms.PROPOSALS_VIEW})
        created = self.client.post("/api/v1/proposals", json=_payload("UNDO-060"), headers=creator_headers)
        pid = created.json()["id"]
        self._release(pid, rid="rid-1")
        self._production(pid, "start", rid="rid-2")
        self._sql("DELETE FROM notifications")
        self.assertEqual(self._undo(pid, "rid-2", reason="Engano").status_code, 200)
        rows = self._sql("SELECT user_id, title, category, dedup_key FROM notifications ORDER BY id")
        self.assertEqual(len(rows), 1)
        self.assertIn(":ACTION_UNDONE:", rows[0].dedup_key)
        self.assertEqual(rows[0].category, "PROPOSTA_STATUS")
        self.assertEqual(rows[0].title, 'Administrador desfez a acao "Inicio da producao" (Engano).')


if __name__ == "__main__":
    unittest.main()
