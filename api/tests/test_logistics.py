"""Modulo de Logistica (LOGs e cargas de entrega): HTTP real com PostgreSQL de teste.

Exige APP_ENV=test e POSTGRES_TEST_DATABASE_URL (nome com `test`). Os testes de schema nao precisam de banco.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, text

from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.main import create_app
from api.app.modules.auth.models import SecurityEvent
from api.app.modules.auth.permissions import INSPECTION_EDIT, INSPECTION_VIEW, LOGISTICS_EDIT, LOGISTICS_VIEW
from api.app.modules.inspection.models import Inspection
from api.app.modules.logistics import schemas
from api.app.modules.proposals.models import Proposal

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


class LogisticsPureTests(unittest.TestCase):
    def _payload(self, **extra):
        today = date.today()
        return {"code": "log103", "state": "eqt-ma", "requested_date": today, "loading_date": today, "delivery_date": today, "proposal_ids": [1], **extra}

    def test_log_code_is_normalized_and_validated(self):
        ok = schemas.LogCreate(**self._payload())
        self.assertEqual((ok.code, ok.state), ("LOG103", "EQT-MA"))
        for bad in ("LOG", "LOG12A", "ABC123", "LOG 12", "NQT1"):
            with self.assertRaises(ValidationError, msg=bad):
                schemas.LogCreate(**self._payload(code=bad))
        with self.assertRaises(ValidationError):
            schemas.LogCreate(**self._payload(proposal_ids=[]))

    def test_docs_links_validated_and_reason_required(self):
        with self.assertRaises(ValidationError):
            schemas.DocsPayload(nf_link="javascript:x", xml_link="https://x/a.xml", bim_link="https://x/b.pdf")
        with self.assertRaises(ValidationError):
            schemas.ReasonPayload(reason="   ")


@unittest.skipUnless(_integration_enabled(), "Exige APP_ENV=test e POSTGRES_TEST_DATABASE_URL.")
class LogisticsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {k: os.environ.get(k) for k in ("DATABASE_URL", "APP_ENV", "SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "logistics-integration-secret-key-32chars"
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
        self.ids, self.tokens = asyncio.run(self._seed())
        self.client = TestClient(create_app())

    async def _reset(self):
        async with get_engine().begin() as conn:
            await conn.execute(text(
                "TRUNCATE TABLE logistics_events, logistics_log_items, logistics_logs, logistics_loads, inspection_events, inspections, "
                "security_events, proposal_events, proposal_items, proposals, role_permissions, user_roles, users, roles, permissions RESTART IDENTITY CASCADE"
            ))

    async def _seed(self):
        from api.app.modules.auth.bootstrap import sync_official_permissions
        from api.app.modules.auth.models import User
        from api.app.modules.auth.security import hash_password
        from api.app.modules.auth.tokens import create_access_token, utcnow
        from api.app.modules.users import service as users_service
        from api.app.modules.users.schemas import UserCreate

        await sync_official_permissions()
        ids: dict[str, int] = {}
        async with get_sessionmaker()() as session:
            boot = User(username="boot", display_name="Boot", password_hash=hash_password("senha-boot-teste-123"), active=True, is_superuser=True, password_changed_at=utcnow())
            session.add(boot)
            await session.flush()
            # PD-1 e PD-2 com inspecao finalizada; PD-3 ainda aberta; "CP 400" sem PD.
            for number, pd, *rest in (("CP 100", "PD-1"), ("CP 101", "PD-1"), ("CP 200", "PD-2"), ("CP 201", "PD-2"), ("CP 300", "PD-3"), ("CP 400", None),
                                  ("CP 500", "PD-5", "EQUATORIAL MARANHAO DISTRIBUIDORA DE ENERGIA S.A"), ("CP 501", "PD-5", "EQUATORIAL MARANHÃO"),
                                  ("CP 502", "PD-6", "EQUATORIAL PARÁ DISTRIBUIDORA DE ENERGIA S.A.")):
                customer = rest[0] if rest else None
                p = Proposal(proposal_number=number, customer_name=customer or "Cliente " + number, order_reference=pd)
                session.add(p)
                await session.flush()
                ids[number] = p.id
            session.add(Inspection(pd_code="PD-1", nqt_code="N1", stage="fim", doc_link="https://x/1.pdf"))
            session.add(Inspection(pd_code="PD-2", nqt_code="N2", stage="fim", doc_link="https://x/2.pdf"))
            session.add(Inspection(pd_code="PD-3", nqt_code="N3", stage="doc"))
            session.add(Inspection(pd_code="PD-5", nqt_code="N5", stage="fim", doc_link="https://x/5.pdf"))
            session.add(Inspection(pd_code="PD-6", nqt_code="N6", stage="fim", doc_link="https://x/6.pdf"))
            tokens = {}
            for name, perms in (
                ("editor", [LOGISTICS_VIEW, LOGISTICS_EDIT]), ("viewer", [LOGISTICS_VIEW]),
                ("none", ["proposals.view", INSPECTION_VIEW, INSPECTION_EDIT]),
            ):
                user = await users_service.create_user(
                    session, UserCreate(username=f"log.{name}", display_name=name.title(), password="senha-log-teste-123", permission_codes=perms), boot,
                )
                tokens[name] = create_access_token(user.id)[0]
            await session.commit()
        return ids, tokens

    # --- helpers -------------------------------------------------------------------------

    def _h(self, who: str = "editor") -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[who]}"}

    def _log(self, code="LOG101", cps=("CP 100", "CP 101"), who="editor", **extra):
        today = date.today()
        body = {
            "code": code, "state": "EQT-MA", "requested_date": str(today + timedelta(20)), "loading_date": str(today + timedelta(19)),
            "delivery_date": str(today + timedelta(20)), "proposal_ids": [self.ids[c] for c in cps], **extra,
        }
        return self.client.post("/api/v1/logistics/logs", json=body, headers=self._h(who))

    def _approved_log(self, code="LOG101", cps=("CP 100", "CP 101")) -> int:
        lid = self._log(code, cps).json()["id"]
        docs = {"nf_link": "https://x/nf.pdf", "xml_link": "https://x/nf.xml", "bim_link": r"\\srv\bim\a.pdf"}
        self.assertEqual(self.client.post(f"/api/v1/logistics/logs/{lid}/docs", json=docs, headers=self._h()).status_code, 200)
        self.assertEqual(self.client.post(f"/api/v1/logistics/logs/{lid}/approve", headers=self._h()).status_code, 200)
        return lid

    def _load(self, log_ids, who="editor"):
        return self.client.post("/api/v1/logistics/loads", json={"departure_date": str(date.today() + timedelta(18)), "log_ids": log_ids}, headers=self._h(who))

    def _err(self, resp, status, code):
        self.assertEqual((resp.status_code, resp.json()["error"]["code"]), (status, code), resp.text)

    # --- LOG -----------------------------------------------------------------------------

    def test_create_log_flow_stages_history_and_days(self):
        resp = self._log("log101")
        self.assertEqual(resp.status_code, 201, resp.text)
        log = resp.json()
        self.assertEqual((log["code"], log["stage"], log["days_in_stage"], log["proposal_count"], log["load_id"]), ("LOG101", "reservada", 0, 2, None))
        self.assertEqual(log["reserved_date"], log["requested_date"])
        self.assertEqual([i["proposal_number"] for i in log["items"]], ["CP 100", "CP 101"])
        self.assertEqual({i["status"] for i in log["items"]}, {"ok"})
        lid = log["id"]
        # nao aprova sem docs
        self._err(self.client.post(f"/api/v1/logistics/logs/{lid}/approve", headers=self._h()), 409, "LOGISTICS_INVALID_STAGE")
        bad = {"nf_link": "javascript:x", "xml_link": "https://x/a.xml", "bim_link": "https://x/b.pdf"}
        self.assertEqual(self.client.post(f"/api/v1/logistics/logs/{lid}/docs", json=bad, headers=self._h()).status_code, 422)
        docs = {"nf_link": "https://x/nf.pdf", "xml_link": "https://x/nf.xml", "bim_link": "https://x/b.pdf"}
        self.assertEqual(self.client.post(f"/api/v1/logistics/logs/{lid}/docs", json=docs, headers=self._h()).json()["stage"], "docs")
        self._err(self.client.post(f"/api/v1/logistics/logs/{lid}/docs", json=docs, headers=self._h()), 409, "LOGISTICS_INVALID_STAGE")
        done = self.client.post(f"/api/v1/logistics/logs/{lid}/approve", headers=self._h()).json()
        self.assertEqual((done["stage"], done["bim_link"]), ("aprovada", "https://x/b.pdf"))
        self.assertEqual([e["actor_name"] for e in done["events"]], ["Editor"] * 3)
        self.assertTrue(done["events"][-1]["text"].startswith("Data reservada"))

        async def audits():
            async with get_sessionmaker()() as s:
                return (await s.execute(select(SecurityEvent.event_type).where(SecurityEvent.event_type.like("LOGISTICS_%")))).scalars().all()

        types = asyncio.run(audits())
        self.assertEqual((types.count("LOGISTICS_LOG_CREATED"), types.count("LOGISTICS_LOG_STAGE_CHANGED")), (1, 2))

    def test_alternate_reserved_date_is_recorded(self):
        alt = str(date.today() + timedelta(24))
        log = self._log(reserved_date=alt).json()
        self.assertEqual(log["reserved_date"], alt)
        self.assertIn("indisponivel", log["events"][0]["text"])

    def test_log_code_unique_and_format(self):
        self.assertEqual(self._log("LOG101", ("CP 100",)).status_code, 201)
        dup = self._log("log101", ("CP 200",))
        self._err(dup, 409, "LOGISTICS_LOG_CODE_ALREADY_EXISTS")
        self.assertIn("LOG101", dup.json()["error"]["message"])
        self.assertEqual(self._log("XYZ1", ("CP 200",)).status_code, 422)
        self.assertEqual(self.client.get("/api/v1/logistics/logs", headers=self._h()).json()["total"], 1)

    def test_eligibility_requires_finished_inspection_and_free_proposal(self):
        elig = self.client.get("/api/v1/logistics/eligible-proposals", headers=self._h("viewer")).json()
        self.assertEqual([p["proposal_number"] for p in elig["items"]], ["CP 100", "CP 101", "CP 200", "CP 201", "CP 500", "CP 501", "CP 502"])
        self.assertEqual((elig["items"][0]["pd_code"], elig["items"][0]["nqt_code"]), ("PD-1", "N1"))
        self.assertEqual([p["state"] for p in elig["items"]], [None] * 4 + ["EQT-MA", "EQT-MA", "EQT-PA"])
        # inspecao nao finalizada
        r = self._log("LOG101", ("CP 300",))
        self._err(r, 409, "LOGISTICS_INSPECTION_NOT_FINISHED")
        self.assertIn("CP 300", r.json()["error"]["message"])
        # sem PD
        self._err(self._log("LOG101", ("CP 400",)), 409, "LOGISTICS_INSPECTION_NOT_FINISHED")
        # inexistente
        resp = self.client.post("/api/v1/logistics/logs", json={
            "code": "LOG101", "state": "EQT-MA", "requested_date": "2026-11-01", "loading_date": "2026-11-01", "delivery_date": "2026-11-02", "proposal_ids": [9999],
        }, headers=self._h())
        self._err(resp, 404, "LOGISTICS_PROPOSAL_NOT_FOUND")
        # nada foi gravado pelas falhas
        self.assertEqual(self.client.get("/api/v1/logistics/logs", headers=self._h()).json()["total"], 0)
        # ja ativa em outro LOG
        self.assertEqual(self._log("LOG101", ("CP 100",)).status_code, 201)
        taken = self._log("LOG102", ("CP 100", "CP 200"))
        self._err(taken, 409, "LOGISTICS_PROPOSAL_ALREADY_IN_LOG")
        self.assertEqual(taken.json()["error"]["details"]["log_code"], "LOG101")
        elig = self.client.get("/api/v1/logistics/eligible-proposals", params={"search": "PD-1"}, headers=self._h()).json()
        self.assertEqual([p["proposal_number"] for p in elig["items"]], ["CP 101"])

    def test_log_state_is_derived_from_customer(self):
        ok = self._log("LOG101", ("CP 500", "CP 501"), state="eqt-ma")
        self.assertEqual((ok.status_code, ok.json()["state"]), (201, "EQT-MA"), ok.text)
        # estados diferentes entre propostas
        self._err(self._log("LOG102", ("CP 502", "CP 200")), 409, "LOGISTICS_STATE_MISMATCH")
        # estado enviado difere do derivado
        self._err(self._log("LOG102", ("CP 502",), state="EQT-MA"), 409, "LOGISTICS_STATE_MISMATCH")
        # derivavel + nao derivavel (caso misto) recusado
        mixed = self._log("LOG102", ("CP 502", "CP 200"), state="EQT-PA")
        self._err(mixed, 409, "LOGISTICS_STATE_MISMATCH")
        self.assertEqual(self.client.get("/api/v1/logistics/logs", headers=self._h()).json()["total"], 1)
        # cliente desconhecido: usa o estado enviado
        manual = self._log("LOG103", ("CP 200",), state="EQT-RS")
        self.assertEqual((manual.status_code, manual.json()["state"]), (201, "EQT-RS"))
        # incluir proposta de outro estado
        lid = ok.json()["id"]
        add = lambda cp: self.client.post(f"/api/v1/logistics/logs/{lid}/proposals", json={"proposal_ids": [self.ids[cp]]}, headers=self._h())  # noqa: E731
        self._err(add("CP 502"), 409, "LOGISTICS_STATE_MISMATCH")
        self.assertEqual(self.client.get(f"/api/v1/logistics/logs/{lid}", headers=self._h()).json()["proposal_count"], 2)

    def test_inclusion_resolution_and_removal_with_reason_returns_proposal(self):
        lid = self._log("LOG101", ("CP 100", "CP 101")).json()["id"]
        add = self.client.post(f"/api/v1/logistics/logs/{lid}/proposals", json={"proposal_ids": [self.ids["CP 200"]]}, headers=self._h()).json()
        self.assertEqual(add["proposal_count"], 3)
        new = [i for i in add["items"] if i["proposal_number"] == "CP 200"][0]
        self.assertEqual(new["status"], "pendente")
        res = self.client.post(f"/api/v1/logistics/logs/{lid}/items/{new['id']}/resolve", json={"result": "reprovada"}, headers=self._h()).json()
        self.assertEqual([i["status"] for i in res["items"] if i["proposal_number"] == "CP 200"], ["reprovada"])
        self._err(self.client.post(f"/api/v1/logistics/logs/{lid}/items/{new['id']}/resolve", json={"result": "ok"}, headers=self._h()), 409, "LOGISTICS_ITEM_NOT_PENDING")
        # remocao exige motivo
        url = f"/api/v1/logistics/logs/{lid}/items/{new['id']}/remove"
        self.assertEqual(self.client.post(url, json={"reason": "  "}, headers=self._h()).status_code, 422)
        self.assertEqual(self.client.post(url, json={}, headers=self._h()).status_code, 422)
        out = self.client.post(url, json={"reason": "cliente cancelou"}, headers=self._h()).json()
        self.assertFalse(out["log_deleted"])
        log = out["log"]
        self.assertEqual((log["proposal_count"], [i["proposal_number"] for i in log["items"]]), (2, ["CP 100", "CP 101"]))
        gone = log["removed_items"][0]
        self.assertEqual((gone["proposal_number"], gone["removal_reason"], gone["removed_by_name"]), ("CP 200", "cliente cancelou", "Editor"))
        self.assertIsNotNone(gone["removed_at"])
        self.assertEqual(log["events"][0]["reason"], "cliente cancelou")
        # volta a ficar disponivel e pode entrar em outro LOG
        elig = self.client.get("/api/v1/logistics/eligible-proposals", headers=self._h()).json()
        self.assertIn("CP 200", [p["proposal_number"] for p in elig["items"]])
        self.assertEqual(self._log("LOG102", ("CP 200",)).status_code, 201)
        # item removido nao pode ser removido de novo
        self._err(self.client.post(url, json={"reason": "x"}, headers=self._h()), 404, "LOGISTICS_ITEM_NOT_FOUND")

    def test_removing_last_proposal_deletes_log_and_frees_code(self):
        log = self._log("LOG101", ("CP 100",)).json()
        out = self.client.post(f"/api/v1/logistics/logs/{log['id']}/items/{log['items'][0]['id']}/remove", json={"reason": "erro"}, headers=self._h()).json()
        self.assertEqual((out["log_deleted"], out["log"]), (True, None))
        self.assertEqual(self.client.get(f"/api/v1/logistics/logs/{log['id']}", headers=self._h()).status_code, 404)
        self.assertEqual(self._log("LOG101", ("CP 100",)).status_code, 201)

    def test_list_filters_and_days_in_stage(self):
        a = self._approved_log("LOG101", ("CP 100",))
        self._log("LOG102", ("CP 200",))

        async def age():
            async with get_engine().begin() as conn:
                await conn.execute(text("UPDATE logistics_logs SET stage_since = now() - interval '4 days' WHERE id = :i"), {"i": a})

        asyncio.run(age())
        get = lambda **q: self.client.get("/api/v1/logistics/logs", params=q, headers=self._h("viewer")).json()  # noqa: E731
        self.assertEqual({i["code"]: i["days_in_stage"] for i in get()["items"]}, {"LOG101": 4, "LOG102": 0})
        self.assertEqual([i["code"] for i in get(stage="aprovada")["items"]], ["LOG101"])
        self.assertEqual([i["code"] for i in get(search="CP 200")["items"]], ["LOG102"])
        self.assertEqual([i["code"] for i in get(in_load="false", stage="aprovada")["items"]], ["LOG101"])
        self.assertEqual(self.client.get("/api/v1/logistics/logs?stage=bogus", headers=self._h()).status_code, 422)

    # --- cargas --------------------------------------------------------------------------

    def test_load_only_with_approved_free_logs_one_load_per_log(self):
        approved = self._approved_log("LOG101", ("CP 100", "CP 101"))
        pending = self._log("LOG102", ("CP 200",)).json()["id"]
        self._err(self._load([pending]), 409, "LOGISTICS_LOG_NOT_APPROVED")
        self._err(self._load([approved, pending]), 409, "LOGISTICS_LOG_NOT_APPROVED")
        self._err(self._load([9999]), 404, "LOGISTICS_LOG_NOT_FOUND")
        self.assertEqual(self.client.post("/api/v1/logistics/loads", json={"departure_date": "2026-11-01", "log_ids": []}, headers=self._h()).status_code, 422)
        self.assertEqual(self.client.get("/api/v1/logistics/loads", headers=self._h()).json()["total"], 0)

        created = self._load([approved])
        self.assertEqual(created.status_code, 201, created.text)
        load = created.json()
        self.assertEqual((load["code"], load["log_count"], load["proposal_count"], load["log_codes"], load["states"]), ("CE-01", 1, 2, ["LOG101"], ["EQT-MA"]))
        self.assertEqual(load["logs"][0]["load_code"], "CE-01")
        self.assertEqual([i["proposal_number"] for i in load["logs"][0]["items"]], ["CP 100", "CP 101"])
        self.assertEqual((load["logs"][0]["loading_date"] is not None, load["logs"][0]["stage"]), (True, "aprovada"))
        # LOG ja esta em uma carga
        self._err(self._load([approved]), 409, "LOGISTICS_LOG_ALREADY_IN_LOAD")
        second = self._approved_log("LOG103", ("CP 201",))
        self.assertEqual(self._load([second]).json()["code"], "CE-02")
        self.assertEqual(self.client.get("/api/v1/logistics/logs", params={"in_load": "false"}, headers=self._h()).json()["total"], 1)

    def test_load_add_remove_log_update_date_and_undo(self):
        a = self._approved_log("LOG101", ("CP 100",))
        b = self._approved_log("LOG102", ("CP 200",))
        c = self._approved_log("LOG103", ("CP 201",))
        load_id = self._load([a]).json()["id"]
        base = f"/api/v1/logistics/loads/{load_id}"
        two = self.client.post(f"{base}/logs", json={"log_id": b}, headers=self._h()).json()
        self.assertEqual((two["log_count"], two["proposal_count"]), (2, 2))
        self._err(self.client.post(f"{base}/logs", json={"log_id": b}, headers=self._h()), 409, "LOGISTICS_LOG_ALREADY_IN_LOAD")
        new_date = str(date.today() + timedelta(30))
        upd = self.client.patch(base, json={"departure_date": new_date}, headers=self._h()).json()
        self.assertEqual(upd["departure_date"], new_date)
        self.assertIn("Data de saida alterada", upd["events"][0]["text"])
        # tirar um LOG
        one = self.client.delete(f"{base}/logs/{b}", headers=self._h()).json()
        self.assertEqual(one["log_codes"], ["LOG101"])
        self.assertIsNone(self.client.get(f"/api/v1/logistics/logs/{b}", headers=self._h()).json()["load_id"])
        self._err(self.client.delete(f"{base}/logs/{c}", headers=self._h()), 404, "LOGISTICS_LOG_NOT_IN_THIS_LOAD")
        self._err(self.client.delete(f"{base}/logs/{a}", headers=self._h()), 409, "LOGISTICS_LOAD_LAST_LOG")
        # desfazer
        self.assertEqual(self.client.delete(base, headers=self._h()).status_code, 204)
        self._err(self.client.get(base, headers=self._h()), 404, "LOGISTICS_LOAD_NOT_FOUND")
        self.assertIsNone(self.client.get(f"/api/v1/logistics/logs/{a}", headers=self._h()).json()["load_id"])
        # CE nunca reaproveita numero
        self.assertEqual(self._load([a]).json()["code"], "CE-02")

    def test_cannot_remove_proposal_from_log_in_a_load(self):
        lid = self._approved_log("LOG101", ("CP 100", "CP 101"))
        load = self._load([lid]).json()
        item = load["logs"][0]["items"][0]
        r = self.client.post(f"/api/v1/logistics/logs/{lid}/items/{item['id']}/remove", json={"reason": "x"}, headers=self._h())
        self._err(r, 409, "LOGISTICS_LOG_IN_LOAD")
        self.assertIn("CE-01", r.json()["error"]["message"])
        self.assertEqual(self.client.get(f"/api/v1/logistics/logs/{lid}", headers=self._h()).json()["proposal_count"], 2)
        # depois de desfazer a carga, a remocao funciona
        self.client.delete(f"/api/v1/logistics/loads/{load['id']}", headers=self._h())
        ok = self.client.post(f"/api/v1/logistics/logs/{lid}/items/{item['id']}/remove", json={"reason": "x"}, headers=self._h())
        self.assertEqual(ok.status_code, 200)

    # --- permissoes ----------------------------------------------------------------------

    def test_permissions_are_enforced(self):
        lid = self._approved_log()
        load_id = self._load([lid]).json()["id"]
        item_id = self.client.get(f"/api/v1/logistics/logs/{lid}", headers=self._h()).json()["items"][0]["id"]
        gets = ["/logs", f"/logs/{lid}", "/eligible-proposals", "/loads", f"/loads/{load_id}"]
        for url in gets:
            full = "/api/v1/logistics" + url
            self.assertEqual(self.client.get(full).status_code, 401, url)
            self.assertEqual(self.client.get(full, headers=self._h("none")).status_code, 403, url)
            self.assertEqual(self.client.get(full, headers=self._h("viewer")).status_code, 200, url)
        writes = [
            ("post", "/logs", {"code": "LOG999", "state": "X", "requested_date": "2026-11-01", "loading_date": "2026-11-01", "delivery_date": "2026-11-01", "proposal_ids": [1]}),
            ("post", f"/logs/{lid}/docs", {"nf_link": "https://a/b", "xml_link": "https://a/b", "bim_link": "https://a/b"}),
            ("post", f"/logs/{lid}/approve", None),
            ("post", f"/logs/{lid}/proposals", {"proposal_ids": [1]}),
            ("post", f"/logs/{lid}/items/{item_id}/resolve", {"result": "ok"}),
            ("post", f"/logs/{lid}/items/{item_id}/remove", {"reason": "x"}),
            ("post", "/loads", {"departure_date": "2026-11-01", "log_ids": [lid]}),
            ("patch", f"/loads/{load_id}", {"departure_date": "2026-11-01"}),
            ("post", f"/loads/{load_id}/logs", {"log_id": lid}),
            ("delete", f"/loads/{load_id}/logs/{lid}", None),
            ("delete", f"/loads/{load_id}", None),
        ]
        for method, url, body in writes:
            for who in ("viewer", "none"):
                kwargs = {"json": body} if body is not None else {}
                resp = getattr(self.client, method)("/api/v1/logistics" + url, headers=self._h(who), **kwargs)
                self.assertEqual(resp.status_code, 403, (method, url, who))
                self.assertEqual(resp.json()["error"]["code"], "PERMISSION_DENIED")
        # nada mudou
        self.assertEqual(self.client.get(f"/api/v1/logistics/loads/{load_id}", headers=self._h()).json()["log_count"], 1)

    def test_unknown_ids_are_404(self):
        self._err(self.client.get("/api/v1/logistics/logs/999", headers=self._h()), 404, "LOGISTICS_LOG_NOT_FOUND")
        self._err(self.client.get("/api/v1/logistics/loads/999", headers=self._h()), 404, "LOGISTICS_LOAD_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
