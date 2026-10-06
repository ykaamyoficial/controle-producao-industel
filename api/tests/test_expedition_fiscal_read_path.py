"""Fase 0 (diagnostico): listas de Expedicao/Fiscal sem escrita em GET.

Parte 1 (caracterizacao): contrato HTTP de ordenacao, filtro, paginacao e
indicadores -- passa igual antes e depois da otimizacao.
Parte 2: os GET nao gravam; derivados (ExpeditionItem/FiscalRecord) nascem na
escrita e/ou no backfill idempotente.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text

from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.main import create_app
from api.app.modules.auth.models import Permission, Role, User
from api.app.modules.auth.permissions import ADMIN_PERMISSION_CODES
from api.app.modules.auth.security import hash_password
from api.app.modules.auth.tokens import utcnow
from api.tests.test_proposals_integration import (
    TEST_DATABASE_URL,
    _alembic_config,
    _integration_enabled,
    _item_payload,
    _proposal_payload,
)

TRUNCATE = "TRUNCATE TABLE security_events, auth_sessions, fiscal_events, fiscal_invoice_items, fiscal_invoices, fiscal_items, fiscal_records, expedition_events, expedition_items, galvanization_load_events, galvanization_load_items, galvanization_loads, proposal_events, proposal_items, proposals, sync_runs, role_permissions, user_roles, users, roles RESTART IDENTITY CASCADE"

EXPECTED_EXPEDITION_ORDER = ["EXP-E", "EXP-A", "EXP-B", "EXP-C"]
EXPECTED_FISCAL_ORDER = ["EXP-D", "EXP-E", "EXP-A", "EXP-B", "EXP-F", "EXP-C"]
EXPECTED_FISCAL_BY_STATUS = {
    "FALTA_EMITIR_NOTA_FISCAL": ["EXP-D", "EXP-E", "EXP-A", "EXP-F"],
    "NOTA_FISCAL_PARCIAL": ["EXP-B"],
    "NOTA_FISCAL_EMITIDA": ["EXP-C"],
}
EXPECTED_FISCAL_BY_SITUATION = {
    "PENDENCIA_FISCAL_CRITICA": ["EXP-D"],
    "DISPONIVEL_PARA_EMISSAO": ["EXP-E", "EXP-A"],
    "NF_PARCIAL": ["EXP-B"],
    "CP_EM_PROCESSAMENTO": ["EXP-F"],
    "NF_EMITIDA": ["EXP-C"],
    "NF_RETIRADA_CLIENTE": [],
}
EXPECTED_FISCAL_SEARCH_BETA = ["EXP-E", "EXP-B"]
EXPECTED_INDICATORS = {
    "falta_emitir": 4, "nf_parcial": 1, "nf_emitida": 1, "pendencia_critica": 1, "entregues_sem_nf": 1,
    "peso_pendente": "42.0000", "peso_faturado": "14.0000", "mais_7_dias_sem_emissao": 0,
}
EXPECTED_INDICATOR_ROWS = {
    "falta_emitir": ["EXP-A", "EXP-D", "EXP-E", "EXP-F"],
    "nf_parcial": ["EXP-B"],
    "nf_emitida": ["EXP-C"],
    "pendencia_critica": ["EXP-D"],
    "mais_7_dias_sem_emissao": [],
    "peso_pendente": ["EXP-A", "EXP-B", "EXP-D", "EXP-E", "EXP-F"],
    "peso_faturado": ["EXP-B", "EXP-C"],
}
EXPECTED_EXPEDITION_ORDER_AFTER_WIPE = EXPECTED_EXPEDITION_ORDER


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class ExpeditionFiscalReadPathTests(unittest.TestCase):
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
        # Nao deixar fiscal_items/proposals para a proxima classe de integracao
        # (o downgrade para base de 20260811_0016 recusa linhas com peso nulo).
        async def _cleanup():
            async with get_engine().begin() as conn:
                await conn.execute(text(TRUNCATE))

        asyncio.run(_cleanup())
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
        self.headers = self._headers()

    async def _seed_admin(self):
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(text(TRUNCATE))
        async with get_sessionmaker()() as session:
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

    # ---- helpers de cenario -------------------------------------------------
    def _post(self, url, body):
        response = self.client.post(url, json=body, headers=self.headers)
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def _create(self, number, items=None, customer="Cliente"):
        payload = _proposal_payload(number, items)
        payload["customer_name"] = customer
        return self._post("/api/v1/proposals", payload)

    def _ready(self, number, items=None, customer="Cliente"):
        proposal = self._create(number, items, customer)
        released = self._post(f"/api/v1/proposals/{proposal['id']}/status", {"version": proposal["version"], "to_area": "PRODUCAO", "to_status": "LIBERADO_PRODUCAO", "reason": "Liberacao"})
        started = self._post(f"/api/v1/production/proposals/{proposal['id']}/start", {"version": released["version"]})
        done = self._post(f"/api/v1/production/proposals/{proposal['id']}/complete-items", {"version": started["version"]})
        self.assertEqual(done["current_area"], "EXPEDICAO")
        return done

    def _build_scenario(self):
        def no_galv(n, q="2.0000"):
            return _item_payload(n, requires_galvanization=False, quantity=q)

        ids = {}
        ids["A"] = self._ready("EXP-A", [no_galv("1")], "Alfa Ltda")["id"]
        b = self._ready("EXP-B", [no_galv("1"), no_galv("2", "4.0000")], "Beta Industria")
        ids["B"] = b["id"]
        self._post(f"/api/v1/shipping/proposals/{b['id']}/start-separation", {"version": b["version"]})
        c = self._ready("EXP-C", [no_galv("1")], "Gama SA")
        ids["C"] = c["id"]
        started = self._post(f"/api/v1/shipping/proposals/{c['id']}/start-separation", {"version": c["version"]})
        self._post(f"/api/v1/shipping/proposals/{c['id']}/separate-items", {"version": started["version"]})
        d = self._ready("EXP-D", [no_galv("1")], "Delta SA")
        ids["D"] = d["id"]
        started = self._post(f"/api/v1/shipping/proposals/{d['id']}/start-separation", {"version": d["version"]})
        separated = self._post(f"/api/v1/shipping/proposals/{d['id']}/separate-items", {"version": started["version"]})
        self._post(f"/api/v1/shipping/proposals/{d['id']}/deliver-items", {"version": separated["version"]})
        ids["E"] = self._ready("EXP-E", [no_galv("1")], "Beta Comercio")["id"]
        ids["F"] = self._create("EXP-F", [no_galv("1")], "Foxtrot")["id"]
        # Fiscal: NF total em C, NF parcial em B.
        records = {row["proposal_number"]: row for row in self._fiscal_list(limit=200)["items"]}
        self._post(f"/api/v1/fiscal/records/{records['EXP-C']['id']}/invoices", {"version": records["EXP-C"]["version"], "invoice_number": "1001", "series": "1"})
        detail = self.client.get(f"/api/v1/fiscal/records/{records['EXP-B']['id']}", headers=self.headers).json()
        first = sorted(detail["items"], key=lambda row: row["item_number"])[0]
        self._post(
            f"/api/v1/fiscal/records/{records['EXP-B']['id']}/invoices",
            {"version": detail["version"], "invoice_number": "1002", "series": "1", "items": [{"fiscal_item_id": first["id"], "quantity": "1.0000", "weight": None}]},
        )
        return ids

    def _shipping_list(self, **params):
        response = self.client.get("/api/v1/shipping/proposals", params=params, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _fiscal_list(self, **params):
        response = self.client.get("/api/v1/fiscal/records", params=params, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _nums(self, payload):
        return [row["proposal_number"] for row in payload["items"]]

    def test_zz_dump(self):
        if not os.environ.get("FASE0_DUMP"):
            self.skipTest("dump manual")
        self._build_scenario()
        out = {"exp": self._nums(self._shipping_list(limit=200)), "fiscal": self._nums(self._fiscal_list(limit=200))}
        out["by_status"] = {s: self._nums(self._fiscal_list(status=s, limit=200)) for s in ("FALTA_EMITIR_NOTA_FISCAL", "NOTA_FISCAL_PARCIAL", "NOTA_FISCAL_EMITIDA")}
        out["by_situation"] = {s: self._nums(self._fiscal_list(situation=s, limit=200)) for s in ("PENDENCIA_FISCAL_CRITICA", "DISPONIVEL_PARA_EMISSAO", "NF_PARCIAL", "CP_EM_PROCESSAMENTO", "NF_EMITIDA", "NF_RETIRADA_CLIENTE")}
        out["beta"] = self._nums(self._fiscal_list(search="beta", limit=200))
        out["indicators"] = self.client.get("/api/v1/fiscal/indicators", headers=self.headers).json()
        out["rows"] = {i: sorted(r["proposal_number"] for r in self.client.get(f"/api/v1/fiscal/indicator-rows/{i}", headers=self.headers).json()) for i in ("falta_emitir", "nf_parcial", "nf_emitida", "pendencia_critica", "mais_7_dias_sem_emissao", "peso_pendente", "peso_faturado")}
        print("\nDUMP" + json.dumps(out, default=str))

    # ---- parte 1: caracterizacao ---------------------------------------------
    def test_expedition_list_order_filter_and_pagination(self):
        self._build_scenario()
        full = self._shipping_list(limit=200)
        numbers = self._nums(full)
        self.assertEqual(numbers, EXPECTED_EXPEDITION_ORDER)
        self.assertEqual(full["total"], len(numbers))
        self.assertEqual(self._shipping_list(search="beta", limit=200)["total"], 2)
        self.assertEqual(self._nums(self._shipping_list(search="  BETA IND ")), ["EXP-B"])
        self.assertEqual(self._shipping_list(search="exp-c")["total"], 1)
        self.assertEqual(self._shipping_list(search="%")["total"], 0)
        page = self._shipping_list(limit=2, offset=1)
        self.assertEqual(page["total"], len(numbers))
        self.assertEqual(self._nums(page), numbers[1:3])
        self.assertEqual(page["limit"], 2)
        self.assertEqual(page["offset"], 1)
        self.assertEqual(self._shipping_list(limit=5, offset=50)["items"], [])
        for key in ("id", "shipping_status", "item_count", "available_quantity", "separated_quantity", "pending_quantity", "origins", "actions", "version"):
            self.assertIn(key, full["items"][0])

    def test_expedition_detail_still_available(self):
        ids = self._build_scenario()
        detail = self.client.get(f"/api/v1/shipping/proposals/{ids['B']}", headers=self.headers)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.json()["items"]), 2)
        self.assertEqual(detail.json()["shipping_status"], "SEPARACAO_INICIADA")

    def test_fiscal_list_filters_order_pagination_and_indicators(self):
        self._build_scenario()
        full = self._fiscal_list(limit=200)
        self.assertEqual(self._nums(full), EXPECTED_FISCAL_ORDER)
        self.assertEqual(full["total"], len(EXPECTED_FISCAL_ORDER))
        for status_value, expected in EXPECTED_FISCAL_BY_STATUS.items():
            self.assertEqual(self._nums(self._fiscal_list(status=status_value, limit=200)), expected, status_value)
        for situation, expected in EXPECTED_FISCAL_BY_SITUATION.items():
            self.assertEqual(self._nums(self._fiscal_list(situation=situation, limit=200)), expected, situation)
        self.assertEqual(self._nums(self._fiscal_list(search="beta", limit=200)), EXPECTED_FISCAL_SEARCH_BETA)
        page = self._fiscal_list(limit=2, offset=2)
        self.assertEqual(page["total"], len(EXPECTED_FISCAL_ORDER))
        self.assertEqual(self._nums(page), EXPECTED_FISCAL_ORDER[2:4])
        indicators = self.client.get("/api/v1/fiscal/indicators", headers=self.headers).json()
        self.assertEqual(indicators, EXPECTED_INDICATORS)
        for indicator, expected in EXPECTED_INDICATOR_ROWS.items():
            rows = self.client.get(f"/api/v1/fiscal/indicator-rows/{indicator}", headers=self.headers).json()
            self.assertEqual(sorted(r["proposal_number"] for r in rows), expected, indicator)

    def test_cancelled_proposal_leaves_both_lists(self):
        ids = self._build_scenario()
        current = self.client.get(f"/api/v1/proposals/{ids['A']}", headers=self.headers).json()
        self._post(f"/api/v1/proposals/{ids['A']}/cancel", {"version": current["version"], "reason": "teste"})
        self.assertNotIn("EXP-A", self._nums(self._shipping_list(limit=200)))
        self.assertNotIn("EXP-A", self._nums(self._fiscal_list(limit=200)))

    # ---- parte 2: GET sem escrita / derivados na escrita ---------------------
    def test_get_endpoints_do_not_write_derived_state(self):
        ids = self._build_scenario()
        record_id = self._fiscal_list(limit=1)["items"][0]["id"]
        statements: list[str] = []
        engine = get_engine().sync_engine

        def _capture(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
                statements.append(statement[:160].lower())

        event.listen(engine, "before_cursor_execute", _capture)
        try:
            self._shipping_list(limit=50)
            self.client.get(f"/api/v1/shipping/proposals/{ids['A']}", headers=self.headers)
            self._fiscal_list(limit=50)
            self.client.get(f"/api/v1/fiscal/records/{record_id}", headers=self.headers)
            self.client.get("/api/v1/fiscal/indicators", headers=self.headers)
            self.client.get("/api/v1/fiscal/indicator-rows/falta_emitir", headers=self.headers)
        finally:
            event.remove(engine, "before_cursor_execute", _capture)
        derived = [s for s in statements if any(t in s for t in ("expedition_items", "fiscal_records", "fiscal_items", "update proposals", "proposal_events"))]
        self.assertEqual(derived, [])

    def test_derived_rows_exist_right_after_write_without_any_read(self):
        self._build_scenario_no_reads()
        counts = asyncio.run(self._derived_counts())
        self.assertEqual(counts["fiscal_records"], 2)
        self.assertEqual(counts["fiscal_items_missing"], 0)
        self.assertEqual(counts["expedition_items"], 1)

    def _build_scenario_no_reads(self):
        # Somente escritas (POST): nenhuma leitura de Expedicao/Fiscal.
        self._ready("EXP-W1", [_item_payload("1", requires_galvanization=False)])
        self._create("EXP-W2", [_item_payload("1", requires_galvanization=False)])

    def test_backfill_is_idempotent_and_recreates_missing_rows(self):
        from api.app.modules.proposals import derived_sync

        self._build_scenario()
        before = asyncio.run(self._derived_counts())
        asyncio.run(derived_sync.backfill_derived_state())
        self.assertEqual(asyncio.run(self._derived_counts()), before)
        asyncio.run(self._wipe_derived())
        self.assertEqual(asyncio.run(self._derived_counts())["fiscal_records"], 0)
        asyncio.run(derived_sync.backfill_derived_state())
        asyncio.run(derived_sync.backfill_derived_state())
        after = asyncio.run(self._derived_counts())
        self.assertEqual(after["fiscal_records"], 6)
        self.assertEqual(after["fiscal_items_missing"], 0)
        self.assertEqual(self._nums(self._shipping_list(limit=200)), EXPECTED_EXPEDITION_ORDER_AFTER_WIPE)

    async def _derived_counts(self):
        async with get_sessionmaker()() as session:
            async def scalar(sql):
                return (await session.execute(text(sql))).scalar_one()

            return {
                "fiscal_records": await scalar("select count(*) from fiscal_records"),
                "fiscal_items": await scalar("select count(*) from fiscal_items"),
                "expedition_items": await scalar("select count(*) from expedition_items"),
                "fiscal_items_missing": await scalar("select count(*) from proposal_items pi join fiscal_records fr on fr.proposal_id=pi.proposal_id where pi.active and not exists (select 1 from fiscal_items fi where fi.fiscal_record_id=fr.id and fi.proposal_item_id=pi.id)"),
            }

    async def _wipe_derived(self):
        async with get_sessionmaker()() as session:
            for table in ("fiscal_events", "fiscal_invoice_items", "fiscal_invoices", "fiscal_items", "fiscal_records"):
                await session.execute(text(f"delete from {table}"))
            await session.commit()
