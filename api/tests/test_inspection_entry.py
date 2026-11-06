"""Entrada na Inspecao (spec-entrada-inspecao): extracao do PD, marcacao requires_inspection, linhas "A solicitar",
sugestao de PD e inicio a partir da proposta. Os testes de API exigem APP_ENV=test e POSTGRES_TEST_DATABASE_URL (nome com `test`).
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
from api.app.modules.auth.permissions import INSPECTION_EDIT, INSPECTION_VIEW, PROPOSALS_CREATE, PROPOSALS_UPDATE, PROPOSALS_VIEW
from api.app.modules.inspection.pd_extraction import extract_pd, suggest_pd
from api.app.modules.proposals.domain import INITIAL_AREA, INITIAL_STATUS
from api.app.modules.proposals.models import Proposal, ProposalEvent

TEST_DATABASE_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL", "")


def _database_name(url: str) -> str:
    return urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1)).path.lstrip("/")


def _integration_enabled() -> bool:
    return bool(TEST_DATABASE_URL) and os.environ.get("APP_ENV") == "test" and "test" in _database_name(TEST_DATABASE_URL).lower()


def _alembic_config() -> Config:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "api" / "alembic.ini"))
    config.set_main_option("script_location", str(root / "api" / "alembic"))
    return config


class PdExtractionTests(unittest.TestCase):
    CASES = [
        ("PEDIDO COMPRA 5400120719", "5400120719"),
        ("PEDIDO COMPRA 7000053481", "7000053481"),
        ("7000053018", "7000053018"),
        ("5400125858", "5400125858"),
        ("MSRTD004_A", None),
        ("SITE - IHS 12060032 - SITTE64", None),
        ("1101085506 - SMSEE67", None),
        ("64060060 - GOCZK03 GF", None),
        ("SUBESTAÇÃO BURITIZEIRO", None),
        ("DADOS DO CLIENTE ENERTEL INDUSTRIA METALURGICA", None),
        ("", None),
        (None, None),
        # variacoes da regra (espacos, separadores, caixa, minimo de 6 digitos)
        ("  7000053018  ", "7000053018"),
        ("123456", "123456"),
        ("12345", None),
        ("PEDIDO: 700005", "700005"),
        ("pedido #700005", "700005"),
        ("Pedido - 700005", "700005"),
        ("PEDIDO DE COMPRA 700005", "700005"),
        ("ORDEM DE COMPRA: 700005", "700005"),
        ("OC 700005", "700005"),
        ("OC-700005", "700005"),
        ("SITE ABC OC 700005", "700005"),
        ("OC 12345", None),
        ("BOC 700005", None),
        ("PEDIDO700005", None),
        ("PEDIDO 700005A", None),
        ("OC 700005 / OC 800006", None),  # ambiguo
        ("OC 700005 e PEDIDO 700005", "700005"),
        ("PEDIDO COMPRA", None),
    ]

    def test_extraction_table(self):
        for text_, expected in self.CASES:
            with self.subTest(text=text_):
                self.assertEqual(extract_pd(text_), expected)

    def test_result_is_digits_only(self):
        self.assertTrue(extract_pd("PEDIDO COMPRA 5400120719").isdigit())

    def test_order_reference_wins_and_is_kept_as_is(self):
        self.assertEqual(suggest_pd(" PEDIDO COMPRA 700 ", "OC 700005"), ("PEDIDO COMPRA 700", "order_reference"))
        self.assertEqual(suggest_pd(None, "OC 700005"), ("700005", "project_name"))
        self.assertEqual(suggest_pd("  ", "MSRTD004_A"), (None, None))


@unittest.skipUnless(_integration_enabled(), "Exige APP_ENV=test e POSTGRES_TEST_DATABASE_URL.")
class InspectionEntryApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {k: os.environ.get(k) for k in ("DATABASE_URL", "APP_ENV", "SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "inspection-entry-secret-key-32chars-x"
        get_settings.cache_clear()
        get_engine.cache_clear()
        command.downgrade(_alembic_config(), "base")
        command.upgrade(_alembic_config(), "head")

    @classmethod
    def tearDownClass(cls):
        asyncio.run(dispose_engine())
        for key, value in cls.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        get_engine.cache_clear()

    def setUp(self):
        asyncio.run(self._reset())
        self.tokens, self.ids = asyncio.run(self._seed())
        self.client = TestClient(create_app())

    async def _reset(self):
        async with get_engine().begin() as conn:
            await conn.execute(text(
                "TRUNCATE TABLE inspection_events, inspections, security_events, proposal_events, proposal_items, proposals, "
                "role_permissions, user_roles, users, roles, permissions RESTART IDENTITY CASCADE"
            ))

    async def _seed(self):
        from api.app.modules.auth.bootstrap import sync_official_permissions
        from api.app.modules.auth.models import User
        from api.app.modules.auth.security import hash_password
        from api.app.modules.auth.tokens import create_access_token, utcnow
        from api.app.modules.users import service as users_service
        from api.app.modules.users.schemas import UserCreate

        await sync_official_permissions()
        async with get_sessionmaker()() as session:
            boot = User(username="boot", display_name="Boot", password_hash=hash_password("senha-boot-teste-123"), active=True, is_superuser=True, password_changed_at=utcnow())
            session.add(boot)
            await session.flush()
            specs = [
                # numero, cliente, obra/site, pedido, marcada, cancelada
                ("CP 100", "Cliente X", "PEDIDO COMPRA 5400120719", None, True, False),
                ("CP 101", "Cliente X", None, "PD-1", True, False),
                ("CP 102", "Cliente X", None, "pd-1", True, False),
                ("CP 103", "Cliente X", "MSRTD004_A", None, True, False),
                ("CP 104", "Cliente X", None, "PD-4", True, True),
                ("CP 105", "Cliente Y", None, "PD-9", False, False),
                ("CP 106", "Cliente X", "OC 700005", None, False, False),
                ("CP 107", "Cliente X", None, "PD-5", False, False),
                ("CP 108", "Cliente X", "PEDIDO 5400120719", None, True, False),
            ]
            ids = {}
            for number, customer, project, order, marked, cancelled in specs:
                row = Proposal(proposal_number=number, customer_name=customer, project_name=project, order_reference=order,
                               requires_inspection=marked, is_cancelled=cancelled,
                               current_area=INITIAL_AREA, current_status=INITIAL_STATUS)
                session.add(row)
                await session.flush()
                ids[number] = row.id
            tokens = {}
            roles = {
                "editor": [INSPECTION_VIEW, INSPECTION_EDIT, PROPOSALS_UPDATE, PROPOSALS_VIEW, PROPOSALS_CREATE],
                "insp_only": [INSPECTION_VIEW, INSPECTION_EDIT],
                "prop_only": [INSPECTION_VIEW, PROPOSALS_UPDATE],
            }
            for name, perms in roles.items():
                user = await users_service.create_user(
                    session, UserCreate(username=f"entry.{name}", display_name=name.title(), password="senha-entry-teste-123", permission_codes=perms), boot,
                )
                tokens[name] = create_access_token(user.id)[0]
            await session.commit()
        return tokens, ids

    # --- helpers -------------------------------------------------------------------------

    def _h(self, who: str = "editor") -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[who]}"}

    def _start(self, number: str, pd: str, who: str = "editor", **extra):
        return self.client.post("/api/v1/inspections/from-proposal", json={"proposal_id": self.ids[number], "pd_code": pd, **extra}, headers=self._h(who))

    def _list(self, **params) -> dict:
        return self.client.get("/api/v1/inspections", params=params, headers=self._h()).json()

    def _proposal(self, number: str) -> dict:
        return self.client.get(f"/api/v1/proposals/{self.ids[number]}", headers=self._h()).json()

    def _db_proposal(self, number: str):
        async def run():
            async with get_sessionmaker()() as s:
                return (await s.execute(select(Proposal).where(Proposal.proposal_number == number))).scalars().first()

        return asyncio.run(run())

    # --- linhas "A solicitar" -------------------------------------------------------------

    def test_list_returns_to_request_rows_grouped_by_pd(self):
        body = self._list()
        self.assertEqual(body["items"], [])
        self.assertEqual(body["counts"], {"open": 0, "finished": 0, "to_request": 3})
        rows = {tuple(r["proposal_numbers"]): r for r in body["to_request"]}
        # CP 100 e CP 108 compartilham o PD sugerido 5400120719; CP 101 e CP 102 compartilham PD-1 (sem caixa); CP 104 cancelada some
        self.assertEqual(set(rows), {("CP 100", "CP 108"), ("CP 101", "CP 102"), ("CP 103",)})
        sug = rows[("CP 100", "CP 108")]
        self.assertEqual((sug["row_type"], sug["pd_code"], sug["pd_source"], sug["proposal_id"]), ("to_request", "5400120719", "project_name", self.ids["CP 100"]))
        self.assertEqual(sug["customer_name"], "Cliente X")
        self.assertEqual([p["proposal_number"] for p in sug["proposals"]], ["CP 100", "CP 108"])
        order = rows[("CP 101", "CP 102")]
        self.assertEqual((order["pd_code"], order["pd_source"]), ("PD-1", "order_reference"))
        none = rows[("CP 103",)]
        self.assertEqual((none["pd_code"], none["pd_source"]), (None, None))

    def test_to_request_disappears_once_inspection_exists_and_follows_filters(self):
        self.assertEqual(self._start("CP 101", "PD-1").status_code, 201)
        body = self._list()
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual({tuple(r["proposal_numbers"]) for r in body["to_request"]}, {("CP 100", "CP 108"), ("CP 103",)})
        self.assertEqual(body["counts"]["to_request"], 2)
        self.assertEqual(self._list(stage="nqt")["to_request"], [])
        self.assertEqual(self._list(stage="solicitada")["to_request"], [])
        self.assertEqual(len(self._list(stage="open")["to_request"]), 2)
        self.assertEqual([r["proposal_numbers"] for r in self._list(search="CP 103")["to_request"]], [["CP 103"]])
        self.assertEqual([r["proposal_numbers"] for r in self._list(search="5400120719")["to_request"]], [["CP 100", "CP 108"]])

    # --- sugestao --------------------------------------------------------------------------

    def test_pd_suggestion(self):
        url = lambda n: f"/api/v1/inspections/proposals/{self.ids[n]}/pd-suggestion"  # noqa: E731
        got = self.client.get(url("CP 100"), headers=self._h("prop_only")).json()
        self.assertEqual((got["pd_code"], got["pd_source"], got["existing_inspection_id"], got["is_cancelled"]), ("5400120719", "project_name", None, False))
        self.assertEqual(self.client.get(url("CP 103"), headers=self._h()).json()["pd_code"], None)
        self.assertEqual(self.client.get(url("CP 107"), headers=self._h()).json()["pd_source"], "order_reference")
        self.assertTrue(self.client.get(url("CP 104"), headers=self._h()).json()["is_cancelled"])
        self.assertEqual(self.client.get("/api/v1/inspections/proposals/9999/pd-suggestion", headers=self._h()).status_code, 404)
        self.assertEqual(self.client.get(url("CP 100")).status_code, 401)

    def test_pd_suggestion_reports_existing_inspection_and_customer_conflict(self):
        self.assertEqual(self._start("CP 107", "PD-5").status_code, 201)
        got = self.client.get(f"/api/v1/inspections/proposals/{self.ids['CP 107']}/pd-suggestion", headers=self._h()).json()
        self.assertIsNotNone(got["existing_inspection_id"])
        # CP 106 sugere 700005 (nao e Pedido de ninguem); CP 105 e do Cliente Y com PD-9 -> conflito para quem usar PD-9
        self.assertEqual(self.client.get(f"/api/v1/inspections/proposals/{self.ids['CP 106']}/pd-suggestion", headers=self._h()).json()["conflicting_proposals"], [])

    # --- iniciar a partir da proposta ---------------------------------------------------

    def test_start_writes_order_reference_with_history_and_creates_inspection(self):
        before = self._proposal("CP 100")
        self.assertIsNone(before["order_reference"])
        resp = self._start("CP 100", "5400120719")
        self.assertEqual(resp.status_code, 201, resp.text)
        body = resp.json()
        self.assertEqual((body["pd_code"], body["stage"], body["created"]), ("5400120719", "pendente", True))
        self.assertEqual(body["proposal_numbers"], ["CP 100"])
        after = self._proposal("CP 100")
        self.assertEqual(after["order_reference"], "5400120719")
        self.assertEqual(after["version"], before["version"] + 1)

        async def events():
            async with get_sessionmaker()() as s:
                return (await s.execute(select(ProposalEvent).where(ProposalEvent.proposal_id == self.ids["CP 100"]))).scalars().all()

        ev = [e for e in asyncio.run(events()) if e.event_type == "PROPOSAL_UPDATED"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0].actor_user_id is not None, True)
        # CP 108 (mesmo PD sugerido) agora cai no mesmo PD: some de "A solicitar"
        self.assertNotIn(["CP 100", "CP 108"], [r["proposal_numbers"] for r in self._list()["to_request"]])

    def test_start_pd_registered_is_ignored(self):
        body = self._start("CP 100", "5400120719", pd_registered=False).json()
        self.assertEqual(body["stage"], "pendente")

    def test_start_returns_existing_inspection_without_duplicating(self):
        first = self._start("CP 101", "PD-1").json()
        again = self._start("CP 102", "PD-1")
        self.assertEqual(again.status_code, 200)
        self.assertEqual((again.json()["id"], again.json()["created"]), (first["id"], False))
        self.assertEqual(self._list()["counts"]["open"], 1)
        # PD novo em proposta sem Pedido cujo PD ja tem inspecao: liga a proposta e devolve a existente
        self.assertEqual(self._start("CP 107", "PD-5").status_code, 201)

    def test_start_never_overwrites_existing_order_reference(self):
        resp = self._start("CP 101", "PD-777")
        self.assertEqual((resp.status_code, resp.json()["error"]["code"]), (409, "INSPECTION_PD_DIFFERS_FROM_ORDER"))
        self.assertEqual(resp.json()["error"]["details"]["order_reference"], "PD-1")
        self.assertEqual(self._db_proposal("CP 101").order_reference, "PD-1")
        # igual (sem caixa) aceita e mantem o texto da proposta
        ok = self._start("CP 101", "pd-1")
        self.assertEqual((ok.status_code, ok.json()["pd_code"]), (201, "PD-1"))
        self.assertEqual(self._db_proposal("CP 101").order_reference, "PD-1")

    def test_start_requires_typed_pd_when_not_identified(self):
        self.assertEqual(self._start("CP 103", "   ").status_code, 422)
        ok = self._start("CP 103", "PD-5555")
        self.assertEqual((ok.status_code, ok.json()["pd_code"]), (201, "PD-5555"))
        self.assertEqual(self._db_proposal("CP 103").order_reference, "PD-5555")

    def test_typed_pd_is_validated(self):
        for bad in ("x" * 61, "PD;DROP TABLE proposals", "PD'1", "-PD1", "PD\n1", "PD<1>"):
            resp = self._start("CP 103", bad)
            self.assertEqual(resp.status_code, 422, bad)
        self.assertIsNone(self._db_proposal("CP 103").order_reference)
        self.assertEqual(self._list()["items"], [])
        self.assertEqual(self._start("CP 103", "PD-1180/2.A_b").status_code, 201)

    def test_customer_conflict_needs_explicit_confirmation(self):
        resp = self._start("CP 106", "PD-9")  # PD-9 e Pedido da CP 105 (Cliente Y); CP 106 e do Cliente X
        self.assertEqual((resp.status_code, resp.json()["error"]["code"]), (409, "INSPECTION_PD_CUSTOMER_CONFLICT"))
        self.assertEqual([p["proposal_number"] for p in resp.json()["error"]["details"]["proposals"]], ["CP 105"])
        self.assertIsNone(self._db_proposal("CP 106").order_reference)
        self.assertEqual(self._list()["counts"]["open"], 0)
        ok = self._start("CP 106", "PD-9", confirm_customer_conflict=True)
        self.assertEqual((ok.status_code, ok.json()["pd_code"]), (201, "PD-9"))
        self.assertEqual(self._db_proposal("CP 106").order_reference, "PD-9")
        # mesmo cliente nao pede confirmacao (CP 101/CP 102 compartilham PD-1)
        self.assertEqual(self._start("CP 101", "PD-1").status_code, 201)

    def test_cancelled_and_unknown_proposal_are_refused(self):
        resp = self._start("CP 104", "PD-4")
        self.assertEqual((resp.status_code, resp.json()["error"]["code"]), (409, "PROPOSAL_CANCELLED_TERMINAL"))
        self.assertEqual(self._list()["counts"]["open"], 0)
        missing = self.client.post("/api/v1/inspections/from-proposal", json={"proposal_id": 99999, "pd_code": "PD-1"}, headers=self._h())
        self.assertEqual((missing.status_code, missing.json()["error"]["code"]), (404, "PROPOSAL_NOT_FOUND"))

    def test_start_needs_both_inspection_edit_and_proposal_update(self):
        for who in ("insp_only", "prop_only"):
            resp = self._start("CP 100", "5400120719", who=who)
            self.assertEqual((resp.status_code, resp.json()["error"]["code"]), (403, "PERMISSION_DENIED"), who)
        self.assertIsNone(self._db_proposal("CP 100").order_reference)
        self.assertEqual(self._list()["counts"]["open"], 0)
        self.assertEqual(self.client.post("/api/v1/inspections/from-proposal", json={"proposal_id": 1, "pd_code": "1"}).status_code, 401)

    # --- marcar / desmarcar ---------------------------------------------------------------

    def test_requires_inspection_read_edit_and_default(self):
        self.assertFalse(self._proposal("CP 105")["requires_inspection"])
        self.assertTrue(self._proposal("CP 101")["requires_inspection"])
        version = self._proposal("CP 105")["version"]
        patch = lambda body: self.client.patch(f"/api/v1/proposals/{self.ids['CP 105']}", json=body, headers=self._h())  # noqa: E731
        resp = patch({"version": version, "requires_inspection": True})
        self.assertEqual((resp.status_code, resp.json()["requires_inspection"]), (200, True))
        self.assertIn("CP 105", [n for r in self._list()["to_request"] for n in r["proposal_numbers"]])
        # null nao altera
        resp = patch({"version": version + 1, "requires_inspection": None, "notes": "x"})
        self.assertEqual(resp.json()["requires_inspection"], True)
        listing = self.client.get("/api/v1/proposals", headers=self._h()).json()
        self.assertIn("requires_inspection", listing["items"][0])

    def test_unmark_blocked_only_when_inspection_exists(self):
        self.assertEqual(self._start("CP 101", "PD-1").status_code, 201)
        patch = lambda number, body: self.client.patch(f"/api/v1/proposals/{self.ids[number]}", json=body, headers=self._h())  # noqa: E731
        blocked = patch("CP 101", {"version": self._proposal("CP 101")["version"], "requires_inspection": False})
        self.assertEqual((blocked.status_code, blocked.json()["error"]["code"]), (409, "INSPECTION_UNMARK_BLOCKED"))
        self.assertTrue(self._db_proposal("CP 101").requires_inspection)
        # CP 102 divide o PD-1 (que ja tem inspecao): tambem bloqueada
        self.assertEqual(patch("CP 102", {"version": self._proposal("CP 102")["version"], "requires_inspection": False}).status_code, 409)
        # sem inspecao do PD: pode desmarcar
        free = patch("CP 103", {"version": self._proposal("CP 103")["version"], "requires_inspection": False})
        self.assertEqual((free.status_code, free.json()["requires_inspection"]), (200, False))

    def test_create_proposal_default_false_and_import_does_not_fill(self):
        payload = {"proposal_number": "CP 900", "customer_name": "Cliente Z", "source": "NOMUS_API",
                   "items": [{"item_number": "1", "description": "Item", "quantity": 1}]}
        resp = self.client.post("/api/v1/proposals", json=payload, headers=self._h())
        self.assertEqual(resp.status_code, 201, resp.text)
        self.assertFalse(resp.json()["requires_inspection"])
        self.assertNotIn("CP 900", [n for r in self._list()["to_request"] for n in r["proposal_numbers"]])
        marked = self.client.post("/api/v1/proposals", json={**payload, "proposal_number": "CP 901", "requires_inspection": True}, headers=self._h())
        self.assertTrue(marked.json()["requires_inspection"])


if __name__ == "__main__":
    unittest.main()
