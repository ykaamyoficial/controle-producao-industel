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
from api.app.modules.logistics import calendar_rules
from api.app.modules.logistics.calendar_rules import local_today
from api.app.modules.proposals.domain import INITIAL_AREA, INITIAL_STATUS
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
                p = Proposal(proposal_number=number, customer_name=customer or "Cliente " + number, order_reference=pd, current_area=INITIAL_AREA, current_status=INITIAL_STATUS)
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
                ("prop", ["proposals.view", "proposals.update", "proposals.cancel", INSPECTION_VIEW, LOGISTICS_VIEW]),
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
        # Datas relativas a hoje (local); confirm_dates=True porque o dia pode cair em fim de semana/feriado (os avisos tem teste proprio).
        today = local_today()
        body = {
            "code": code, "state": "EQT-MA", "requested_date": str(today + timedelta(20)), "loading_date": str(today + timedelta(19)),
            "delivery_date": str(today + timedelta(20)), "proposal_ids": [self.ids[c] for c in cps], "confirm_dates": True, **extra,
        }
        return self.client.post("/api/v1/logistics/logs", json=body, headers=self._h(who))

    def _approved_log(self, code="LOG101", cps=("CP 100", "CP 101")) -> int:
        lid = self._log(code, cps).json()["id"]
        docs = {"nf_link": "https://x/nf.pdf", "xml_link": "https://x/nf.xml", "bim_link": r"\\srv\bim\a.pdf"}
        self.assertEqual(self.client.post(f"/api/v1/logistics/logs/{lid}/docs", json=docs, headers=self._h()).status_code, 200)
        self.assertEqual(self.client.post(f"/api/v1/logistics/logs/{lid}/approve", headers=self._h()).status_code, 200)
        return lid

    def _load(self, log_ids, who="editor"):
        return self.client.post("/api/v1/logistics/loads", json={"departure_date": str(local_today() + timedelta(18)), "log_ids": log_ids, "confirm_dates": True}, headers=self._h(who))

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
            "code": "LOG101", "state": "EQT-MA", "requested_date": "2030-11-01", "loading_date": "2030-11-01", "delivery_date": "2030-11-02", "proposal_ids": [9999],
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
        ok = self.client.post(f"/api/v1/logistics/logs/{lid}/items/{new['id']}/resolve", json={"result": "ok"}, headers=self._h()).json()
        self.assertEqual([i["status"] for i in ok["items"] if i["proposal_number"] == "CP 200"], ["ok"])
        self._err(self.client.post(f"/api/v1/logistics/logs/{lid}/items/{new['id']}/resolve", json={"result": "ok"}, headers=self._h()), 409, "LOGISTICS_ITEM_NOT_PENDING")
        # reprovada sai do LOG, fica no historico de removidas e a proposta fica livre para outro LOG
        add2 = self.client.post(f"/api/v1/logistics/logs/{lid}/proposals", json={"proposal_ids": [self.ids["CP 201"]]}, headers=self._h()).json()
        bad = [i for i in add2["items"] if i["proposal_number"] == "CP 201"][0]
        res = self.client.post(f"/api/v1/logistics/logs/{lid}/items/{bad['id']}/resolve", json={"result": "reprovada"}, headers=self._h()).json()
        self.assertEqual(([i["proposal_number"] for i in res["items"]], res["proposal_count"]), (["CP 100", "CP 101", "CP 200"], 3))
        self.assertEqual([(i["proposal_number"], i["status"], i["removal_reason"]) for i in res["removed_items"]], [("CP 201", "reprovada", "Inclusao reprovada")])
        self.assertIn("CP 201", [p["proposal_number"] for p in self.client.get("/api/v1/logistics/eligible-proposals", headers=self._h()).json()["items"]])
        self._err(self.client.post(f"/api/v1/logistics/logs/{lid}/items/{bad['id']}/resolve", json={"result": "ok"}, headers=self._h()), 404, "LOGISTICS_ITEM_NOT_FOUND")
        # remocao exige motivo
        url = f"/api/v1/logistics/logs/{lid}/items/{new['id']}/remove"
        self.assertEqual(self.client.post(url, json={"reason": "  "}, headers=self._h()).status_code, 422)
        self.assertEqual(self.client.post(url, json={}, headers=self._h()).status_code, 422)
        out = self.client.post(url, json={"reason": "cliente cancelou"}, headers=self._h()).json()
        self.assertFalse(out["log_deleted"])
        log = out["log"]
        self.assertEqual((log["proposal_count"], [i["proposal_number"] for i in log["items"]]), (2, ["CP 100", "CP 101"]))
        gone = [i for i in log["removed_items"] if i["proposal_number"] == "CP 200"][0]
        self.assertEqual((gone["removal_reason"], gone["removed_by_name"]), ("cliente cancelou", "Editor"))
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
        today = local_today()
        by_code = {i["code"]: i["business_days_in_stage"] for i in get()["items"]}
        self.assertEqual(by_code, {"LOG101": calendar_rules.business_days_between(today - timedelta(days=4), today), "LOG102": 0})
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
        self.assertEqual(self.client.post("/api/v1/logistics/loads", json={"departure_date": "2030-11-01", "log_ids": []}, headers=self._h()).status_code, 422)
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
        two = self.client.post(f"{base}/logs", json={"log_id": b, "confirm_dates": True}, headers=self._h()).json()
        self.assertEqual((two["log_count"], two["proposal_count"]), (2, 2))
        self._err(self.client.post(f"{base}/logs", json={"log_id": b}, headers=self._h()), 409, "LOGISTICS_LOG_ALREADY_IN_LOAD")
        new_date = str(local_today() + timedelta(30))
        upd = self.client.patch(base, json={"departure_date": new_date, "reason": "caminhao atrasou", "confirm_dates": True}, headers=self._h()).json()
        self.assertEqual(upd["departure_date"], new_date)
        self.assertIn("Data de saida alterada", upd["events"][0]["text"])
        self.assertEqual(upd["events"][0]["reason"], "caminhao atrasou")
        no_reason = self.client.patch(base, json={"departure_date": str(local_today() + timedelta(31)), "confirm_dates": True}, headers=self._h())
        self.assertEqual(no_reason.status_code, 422)
        self._err(self.client.patch(base, json={"departure_date": new_date, "reason": "x", "confirm_dates": True}, headers=self._h()), 422, "VALIDATION_ERROR")
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

    def _deleted_audit(self, event_type="LOGISTICS_LOG_DELETED"):
        async def get():
            async with get_sessionmaker()() as s:
                return (await s.execute(select(SecurityEvent.details).where(SecurityEvent.event_type == event_type))).scalars().all()

        return asyncio.run(get())

    def test_empty_log_is_deleted_when_leaving_load_and_never_enters_one(self):
        a = self._approved_log("LOG101", ("CP 100",))
        b = self._approved_log("LOG102", ("CP 200",))
        c = self._approved_log("LOG103", ("CP 201",))
        load_id = self._load([a, b, c]).json()["id"]
        base = f"/api/v1/logistics/loads/{load_id}"
        self.assertEqual(self._cancel("CP 200", confirm_inspection_logistics=True).status_code, 200)  # LOG102 fica vazio dentro da carga
        self.assertEqual(self._cancel("CP 201", confirm_inspection_logistics=True).status_code, 200)  # LOG103 tambem
        self.assertEqual(self.client.get(f"/api/v1/logistics/logs/{b}", headers=self._h()).status_code, 200)
        out = self.client.delete(f"{base}/logs/{b}", headers=self._h()).json()
        self.assertEqual(out["log_codes"], ["LOG101", "LOG103"])
        self.assertEqual(self.client.get(f"/api/v1/logistics/logs/{b}", headers=self._h()).status_code, 404)
        self.assertIn("excluido", out["events"][0]["text"])
        self.assertEqual([d["code"] for d in self._deleted_audit()], ["LOG102"])
        self.assertTrue(any("CP 200 removida" in e["text"] for e in self._deleted_audit()[0]["history"]))
        # desfazer a carga tambem exclui o LOG vazio e preserva o que tem propostas
        self.assertEqual(self.client.delete(base, headers=self._h()).status_code, 204)
        self.assertEqual(self.client.get(f"/api/v1/logistics/logs/{c}", headers=self._h()).status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/logistics/logs/{a}", headers=self._h()).json()["load_id"], None)
        deleted = {d["code"]: d for d in self._deleted_audit()}
        self.assertEqual(sorted(deleted), ["LOG102", "LOG103"])
        self.assertTrue(any("CP 201 removida" in e["text"] for e in deleted["LOG103"]["history"]))
        # LOG sem itens ativos (dado legado) e recusado na carga
        async def empty():
            async with get_engine().begin() as conn:
                await conn.execute(text("UPDATE logistics_log_items SET removed_at = now() WHERE log_id = :i"), {"i": a})

        asyncio.run(empty())
        self._err(self._load([a]), 409, "LOGISTICS_LOG_EMPTY")

    def test_delete_load_with_log_inside_keeps_log_events_and_audits_load_history(self):
        a = self._approved_log("LOG101", ("CP 100",))
        b = self._approved_log("LOG102", ("CP 200",))
        load = self._load([a, b]).json()
        self.assertEqual(self._cancel("CP 200", confirm_inspection_logistics=True).status_code, 200)  # LOG102 fica vazio dentro da carga
        before = self.client.get(f"/api/v1/logistics/logs/{b}", headers=self._h()).json()
        self.assertEqual(self.client.delete(f"/api/v1/logistics/loads/{load['id']}", headers=self._h()).status_code, 204)
        # LOG com propostas sobrevive com os eventos; o vazio some
        self.assertEqual(self.client.get(f"/api/v1/logistics/logs/{b}", headers=self._h()).status_code, 404)
        texts = [e["text"] for e in self.client.get(f"/api/v1/logistics/logs/{a}", headers=self._h()).json()["events"]]
        self.assertIn(f"Carga {load['code']} desfeita", texts)
        self.assertTrue(any("LOG101 gerado" in t for t in texts), texts)
        # auditoria da carga guarda o historico dela; a do LOG vazio guarda o historico do LOG
        [load_audit] = self._deleted_audit("LOGISTICS_LOAD_DELETED")
        self.assertEqual(load_audit["load_code"], load["code"])
        self.assertTrue(any(e["text"].startswith("Carga criada com") for e in load_audit["history"]), load_audit["history"])
        deleted = {d["code"]: d for d in self._deleted_audit()}
        self.assertEqual(deleted["LOG102"]["reason"], f"Vazio ao desfazer a carga {load['code']}")
        fields = ("requested_date", "reserved_date", "loading_date", "delivery_date", "nf_link", "xml_link", "bim_link")
        self.assertEqual({k: deleted["LOG102"][k] for k in fields}, {k: before[k] for k in fields})
        self.assertTrue(any("CP 200 removida" in e["text"] for e in deleted["LOG102"]["history"]))

    def test_reproving_last_inclusion_of_log_in_load_records_event_in_load(self):
        a = self._approved_log("LOG101", ("CP 100",))
        added = self.client.post(f"/api/v1/logistics/logs/{a}/proposals", json={"proposal_ids": [self.ids["CP 200"]]}, headers=self._h()).json()
        pending = next(i for i in added["items"] if i["proposal_number"] == "CP 200")
        load_id = self._load([a]).json()["id"]
        self.assertEqual(self._cancel("CP 100", confirm_inspection_logistics=True).status_code, 200)
        res = self.client.post(f"/api/v1/logistics/logs/{a}/items/{pending['id']}/resolve", json={"result": "reprovada"}, headers=self._h())
        self.assertEqual(res.status_code, 200, res.text)
        texts = [e["text"] for e in self.client.get(f"/api/v1/logistics/loads/{load_id}", headers=self._h()).json()["events"]]
        self.assertTrue(any("CP 200 saiu do LOG101" in t and "sem propostas" in t for t in texts), texts)

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

    # --- avisos de data (nunca travam; 409 DATE_CONFIRMATION_REQUIRED ate confirmar) ----------

    def _warnings(self, resp):
        self._err(resp, 409, "DATE_CONFIRMATION_REQUIRED")
        return {w["code"]: w for w in resp.json()["error"]["details"]["warnings"]}

    def _raw_log(self, code="LOG101", cps=("CP 100",), **dates):
        # 2030-03-12 e uma terca sem feriado: so os avisos pedidos aparecem.
        base = {"requested_date": "2030-03-12", "loading_date": "2030-03-12", "delivery_date": "2030-03-13"}
        body = {"code": code, "state": "EQT-MA", "proposal_ids": [self.ids[c] for c in cps], **base, **dates}
        body.setdefault("reserved_date", body["delivery_date"])  # reservada == entrega: sem o aviso RESERVED_DIFFERS_FROM_DELIVERY
        return self.client.post("/api/v1/logistics/logs", json=body, headers=self._h())

    def test_clean_dates_need_no_confirmation(self):
        self.assertEqual(self._raw_log().status_code, 201)

    def test_log_warnings_block_until_confirmed_then_save(self):
        # R3 entrega antes do carregamento + R2 (sabado 2030-03-16) + R7 (passado) juntos; nada gravado no 409.
        resp = self._raw_log(requested_date="2020-01-07", loading_date="2030-03-14", delivery_date="2030-03-09")
        warns = self._warnings(resp)
        self.assertEqual(set(warns), {"DATE_IN_PAST", "NON_BUSINESS_DAY", "DELIVERY_BEFORE_LOADING"})
        self.assertEqual((warns["DATE_IN_PAST"]["field"], warns["NON_BUSINESS_DAY"]["field"], warns["DELIVERY_BEFORE_LOADING"]["field"]),
                         ("requested_date", "delivery_date", "delivery_date"))
        self.assertIn("sábado", warns["NON_BUSINESS_DAY"]["message"])
        self.assertEqual(self.client.get("/api/v1/logistics/logs", headers=self._h()).json()["total"], 0)
        ok = self._raw_log(requested_date="2020-01-07", loading_date="2030-03-14", delivery_date="2030-03-09", confirm_dates=True)
        self.assertEqual(ok.status_code, 201, ok.text)

    def test_delivery_holiday_uses_cd_state_and_factory_uses_goiania(self):
        # 2030-05-24 e sexta: feriado de Goiania (fabrica) mas nao do Maranhao (entrega no CD).
        self.assertEqual(set(self._warnings(self._raw_log(loading_date="2030-05-24", delivery_date="2030-05-24"))), {"NON_BUSINESS_DAY"})
        r = self._raw_log(loading_date="2030-05-23", delivery_date="2030-05-24")
        self.assertEqual(r.status_code, 201, r.text)

    def test_delivery_before_inspection_finished_warns(self):
        async def finish_later():
            async with get_engine().begin() as conn:
                await conn.execute(text("UPDATE inspections SET stage_since = '2030-03-14T15:00:00+00' WHERE pd_code = 'PD-1'"))

        asyncio.run(finish_later())
        self.assertEqual(set(self._warnings(self._raw_log())), {"DELIVERY_BEFORE_INSPECTION_DONE"})

    def test_agenda_conflict_visit_and_loading_both_ways(self):
        async def visit():
            async with get_engine().begin() as conn:
                await conn.execute(text("UPDATE inspections SET stage = 'inloco', decision_type = 'inloco', visit_date = '2030-03-12' WHERE pd_code = 'PD-3'"))

        asyncio.run(visit())
        warns = self._warnings(self._raw_log())
        self.assertEqual((set(warns), warns["AGENDA_CONFLICT"]["field"]), ({"AGENDA_CONFLICT"}, "loading_date"))
        self.assertIn("PD-3", warns["AGENDA_CONFLICT"]["message"])
        self.assertEqual(self._raw_log(confirm_dates=True).status_code, 201)
        # inverso: agendar visita (PD-3 volta para 'nqt') no dia do carregamento
        async def back_to_nqt():
            async with get_engine().begin() as conn:
                await conn.execute(text("UPDATE inspections SET stage = 'nqt', decision_type = NULL, visit_date = NULL WHERE pd_code = 'PD-3'"))

        asyncio.run(back_to_nqt())
        iid = self.client.get("/api/v1/inspections", params={"search": "PD-3"}, headers=self._h("none")).json()["items"][0]["id"]
        url, body = f"/api/v1/inspections/{iid}/decision", {"decision": "inloco", "visit_date": "2030-03-12"}
        warns = self._warnings(self.client.post(url, json=body, headers=self._h("none")))
        self.assertEqual((set(warns), warns["AGENDA_CONFLICT"]["field"]), ({"AGENDA_CONFLICT"}, "visit_date"))
        self.assertIn("LOG101", warns["AGENDA_CONFLICT"]["message"])
        done = self.client.post(url, json={**body, "confirm_dates": True}, headers=self._h("none"))
        self.assertEqual((done.status_code, done.json()["visit_date"]), (200, "2030-03-12"))

    def test_load_departure_warnings(self):
        a = self._approved_log("LOG101", ("CP 100",))
        loading = self.client.get(f"/api/v1/logistics/logs/{a}", headers=self._h()).json()["loading_date"]
        post = lambda dep, **kw: self.client.post("/api/v1/logistics/loads", json={"departure_date": dep, "log_ids": [a], **kw}, headers=self._h())  # noqa: E731
        warns = self._warnings(post("2030-03-12"))
        self.assertIn("DEPARTURE_DIFFERS_FROM_LOADING", warns)
        self.assertNotIn("DATE_IN_PAST", warns)
        self.assertIn(self.client.get(f"/api/v1/logistics/logs/{a}", headers=self._h()).json()["code"], warns["DEPARTURE_DIFFERS_FROM_LOADING"]["message"])
        same = post(loading, confirm_dates=True)
        self.assertEqual(same.status_code, 201, same.text)

    # --- F2: consertos ---------------------------------------------------------------------

    def test_cannot_add_proposals_to_log_in_a_load(self):
        lid = self._approved_log("LOG101", ("CP 100",))
        self._load([lid])
        r = self.client.post(f"/api/v1/logistics/logs/{lid}/proposals", json={"proposal_ids": [self.ids["CP 101"]]}, headers=self._h())
        self._err(r, 409, "LOGISTICS_LOG_IN_LOAD")
        self.assertIn("CE-01", r.json()["error"]["message"])

    def _proposal(self, cp):
        return self.client.get(f"/api/v1/proposals/{self.ids[cp]}", headers=self._h("prop")).json()

    def _cancel(self, cp, **extra):
        body = {"version": self._proposal(cp)["version"], "reason": "erro de cadastro", **extra}
        return self.client.post(f"/api/v1/proposals/{self.ids[cp]}/cancel", json=body, headers=self._h("prop"))

    def _set_order(self, cp, pd, **extra):
        body = {"version": self._proposal(cp)["version"], "purchase_order": pd, **extra}
        return self.client.patch(f"/api/v1/proposals/{self.ids[cp]}", json=body, headers=self._h("prop"))

    def _history(self, pd):
        iid = self.client.get("/api/v1/inspections", params={"search": pd}, headers=self._h("none")).json()["items"][0]["id"]
        return [e["text"] for e in self.client.get(f"/api/v1/inspections/{iid}", headers=self._h("none")).json()["events"]]

    def test_cancel_proposal_in_inspection_and_log_asks_confirmation_then_leaves_log(self):
        lid = self._log("LOG101", ("CP 100", "CP 101")).json()["id"]
        r = self._cancel("CP 100")
        self._err(r, 409, "INSPECTION_LOGISTICS_CONFIRMATION_REQUIRED")
        details = r.json()["error"]["details"]
        self.assertEqual((details["action"], details["inspection"]["pd_code"], details["log"]["code"], details["leaves_log"]), ("cancel", "PD-1", "LOG101", True))
        self.assertFalse(self._proposal("CP 100")["is_cancelled"])
        self.assertEqual(self._cancel("CP 100", confirm_inspection_logistics=True).status_code, 200)
        log = self.client.get(f"/api/v1/logistics/logs/{lid}", headers=self._h()).json()
        self.assertEqual(([i["proposal_number"] for i in log["items"]], [i["removal_reason"] for i in log["removed_items"]]), (["CP 101"], ["Proposta cancelada: erro de cadastro"]))
        self.assertTrue(any("CP 100 cancelada" in t for t in self._history("PD-1")))
        # ultima proposta: o LOG deixa de existir, mas o historico fica na proposta e na auditoria
        self.assertEqual(self._cancel("CP 101", confirm_inspection_logistics=True).status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/logistics/logs/{lid}", headers=self._h()).status_code, 404)

        async def kept():
            async with get_sessionmaker()() as s:
                events = (await s.execute(text("SELECT metadata->>'text' FROM proposal_events WHERE event_type = 'LOGISTICS_HISTORY' ORDER BY id"))).scalars().all()
                audit = (await s.execute(select(SecurityEvent.details).where(SecurityEvent.event_type == "LOGISTICS_LOG_DELETED"))).scalars().all()
                return events, audit

        events, audit = asyncio.run(kept())
        self.assertEqual(events, ["CP 100 saiu do LOG101", "CP 101 saiu do LOG101"])
        self.assertTrue(audit[0]["history"])
        # sem inspecao nem LOG: cancela direto
        self.assertEqual(self._cancel("CP 400").status_code, 200)

    def test_change_order_follows_inspection_when_sole_proposal_and_leaves_log_when_unfinished(self):
        # CP 300 e a unica do PD-3 (inspecao aberta): a inspecao acompanha o novo PD.
        r = self._set_order("CP 300", "PD-NOVO")
        self._err(r, 409, "INSPECTION_LOGISTICS_CONFIRMATION_REQUIRED")
        d = r.json()["error"]["details"]
        self.assertEqual((d["inspection_follows_new_pd"], d["new_pd_has_inspection"]), (True, False))
        self.assertEqual(self._proposal("CP 300")["order_reference"], "PD-3")
        self.assertEqual(self._set_order("CP 300", "PD-NOVO", confirm_inspection_logistics=True).status_code, 200)
        self.assertTrue(any("PD alterado de PD-3 para PD-NOVO" in t for t in self._history("PD-NOVO")))
        self.assertEqual(self.client.get("/api/v1/inspections", params={"search": "PD-3"}, headers=self._h("none")).json()["total"], 0)
        # CP 100 esta no LOG e divide o PD-1 com CP 101: a inspecao do PD-1 fica. PD-NOVO esta aberto -> CP 100 sai do LOG.
        lid = self._log("LOG101", ("CP 100", "CP 101")).json()["id"]
        r = self._set_order("CP 100", "PD-NOVO")
        self._err(r, 409, "INSPECTION_LOGISTICS_CONFIRMATION_REQUIRED")
        d = r.json()["error"]["details"]
        self.assertEqual((d["inspection"]["pd_code"], d["inspection_follows_new_pd"], d["new_pd_has_inspection"], d["leaves_log"]), ("PD-1", False, True, True))
        self.assertEqual(self._set_order("CP 100", "PD-NOVO", confirm_inspection_logistics=True).status_code, 200)
        log = self.client.get(f"/api/v1/logistics/logs/{lid}", headers=self._h()).json()
        self.assertEqual([i["proposal_number"] for i in log["items"]], ["CP 101"])
        self.assertEqual(self.client.get("/api/v1/inspections", params={"search": "PD-1"}, headers=self._h("none")).json()["items"][0]["stage"], "fim")
        # novo PD com inspecao finalizada: continua no LOG
        self.assertEqual(self._set_order("CP 101", "PD-2", confirm_inspection_logistics=True).status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/logistics/logs/{lid}", headers=self._h()).json()["proposal_count"], 1)
        # proposta sem inspecao nem LOG troca o Pedido sem confirmacao
        self.assertEqual(self._set_order("CP 400", "PD-400").status_code, 200)

    def test_cancel_in_load_keeps_empty_log_and_flags_orphaned_inspection(self):
        lid = self._approved_log("LOG101", ("CP 100",))
        load_id = self._load([lid]).json()["id"]
        r = self._cancel("CP 100")
        self._err(r, 409, "INSPECTION_LOGISTICS_CONFIRMATION_REQUIRED")
        d = r.json()["error"]["details"]
        self.assertEqual((d["log_stays_empty_in_load"], d["inspection_orphaned"]), (True, False))  # CP 101 ainda usa o PD-1
        self.assertEqual(self._cancel("CP 100", confirm_inspection_logistics=True).status_code, 200)
        log = self.client.get(f"/api/v1/logistics/logs/{lid}", headers=self._h())
        self.assertEqual((log.status_code, log.json()["proposal_count"], log.json()["load_id"]), (200, 0, load_id))
        load_events = [e["text"] for e in self.client.get(f"/api/v1/logistics/loads/{load_id}", headers=self._h()).json()["events"]]
        self.assertTrue(any("CP 100 saiu do LOG101" in t and "sem propostas" in t for t in load_events), load_events)
        # CP 101 e a ultima proposta viva do PD-1: a inspecao fica sem proposta ativa (so avisa, nao bloqueia)
        d = self._cancel("CP 101").json()["error"]["details"]
        self.assertEqual((d["inspection_orphaned"], d["log_stays_empty_in_load"]), (True, False))
        self.assertEqual(self._cancel("CP 101", confirm_inspection_logistics=True).status_code, 200)
        self.assertTrue(any("CP 101 cancelada: inspeção sem proposta ativa" in t for t in self._history("PD-1")))

    def test_change_order_to_pd_with_inspection_orphans_old_inspection(self):
        d = self._set_order("CP 300", "PD-2").json()["error"]["details"]  # PD-2 ja tem inspecao: a do PD-3 nao pode acompanhar
        self.assertEqual((d["inspection_orphaned"], d["inspection_follows_new_pd"], d["log_stays_empty_in_load"]), (True, False, False))
        self.assertEqual(self._set_order("CP 300", "PD-2", confirm_inspection_logistics=True).status_code, 200)
        self.assertTrue(any("mudou o Pedido de PD-3 para PD-2: inspeção sem proposta ativa" in t for t in self._history("PD-3")))
        # PD-1 ainda tem CP 101: trocar so a CP 100 nao deixa a inspecao orfa
        self.assertFalse(self._set_order("CP 100", "PD-2").json()["error"]["details"]["inspection_orphaned"])

    def test_reject_inclusion_detaches_with_proposal_history_and_drops_empty_log(self):
        lid = self._log("LOG101", ("CP 100",)).json()["id"]
        add = self.client.post(f"/api/v1/logistics/logs/{lid}/proposals", json={"proposal_ids": [self.ids["CP 200"]]}, headers=self._h()).json()
        ids = {i["proposal_number"]: i["id"] for i in add["items"]}
        self.client.post(f"/api/v1/logistics/logs/{lid}/items/{ids['CP 100']}/remove", json={"reason": "saiu"}, headers=self._h())
        res = self.client.post(f"/api/v1/logistics/logs/{lid}/items/{ids['CP 200']}/resolve", json={"result": "reprovada"}, headers=self._h())
        self.assertEqual((res.status_code, res.json()["log_deleted"]), (200, True))
        self.assertEqual(self.client.get(f"/api/v1/logistics/logs/{lid}", headers=self._h()).status_code, 404)

        async def history():
            async with get_sessionmaker()() as s:
                return (await s.execute(text("SELECT metadata->>'text' FROM proposal_events WHERE event_type = 'LOGISTICS_HISTORY' ORDER BY id"))).scalars().all()

        self.assertIn("CP 200 saiu do LOG101", asyncio.run(history()))

    def test_reserved_date_differing_from_delivery_only_warns(self):
        warns = self._warnings(self._raw_log(reserved_date="2030-03-11"))  # entrega 2030-03-13
        self.assertEqual((set(warns), warns["RESERVED_DIFFERS_FROM_DELIVERY"]["field"]), ({"RESERVED_DIFFERS_FROM_DELIVERY"}, "reserved_date"))
        lid = self._raw_log(reserved_date="2030-03-11", confirm_dates=True).json()["id"]
        url = f"/api/v1/logistics/logs/{lid}/dates"
        patch = lambda body: self.client.patch(url, json={**body, "reason": "x"}, headers=self._h())  # noqa: E731
        self.assertEqual(patch({"reserved_date": "2030-03-13"}).status_code, 200)  # igual a entrega: sem aviso
        warns = self._warnings(patch({"delivery_date": "2030-03-14"}))
        self.assertEqual((set(warns), warns["RESERVED_DIFFERS_FROM_DELIVERY"]["field"]), ({"RESERVED_DIFFERS_FROM_DELIVERY"}, "reserved_date"))
        self.assertEqual(patch({"delivery_date": "2030-03-14", "confirm_dates": True}).status_code, 200)

    # --- F3: editar datas do LOG e da carga com motivo --------------------------------------

    def test_edit_log_dates_needs_reason_logs_each_field_and_warns_only(self):
        lid = self._raw_log().json()["id"]
        url = f"/api/v1/logistics/logs/{lid}/dates"
        patch = lambda body, who="editor": self.client.patch(url, json=body, headers=self._h(who))  # noqa: E731
        self.assertEqual(patch({"loading_date": "2030-03-14"}).status_code, 422)  # motivo obrigatorio
        self._err(patch({"reason": "x"}), 422, "VALIDATION_ERROR")  # nada mudou
        self._err(patch({"loading_date": "2030-03-12", "reason": "x"}), 422, "VALIDATION_ERROR")  # mesma data
        # carregamento passa para depois da entrega (R3) num sabado (R2)
        warns = self._warnings(patch({"loading_date": "2030-03-16", "reason": "caminhao quebrou"}))
        self.assertEqual(set(warns), {"NON_BUSINESS_DAY", "DELIVERY_BEFORE_LOADING"})
        self.assertEqual(self.client.get(url.removesuffix("/dates"), headers=self._h()).json()["loading_date"], "2030-03-12")
        out = patch({"loading_date": "2030-03-16", "delivery_date": "2030-03-18", "reason": "caminhao quebrou", "confirm_dates": True})
        self.assertEqual(out.status_code, 200, out.text)
        log = out.json()
        self.assertEqual((log["loading_date"], log["delivery_date"], log["requested_date"]), ("2030-03-16", "2030-03-18", "2030-03-12"))
        texts = [e["text"] for e in log["events"][:2]]
        self.assertEqual(sorted(texts), ["Dia de carregamento: de 12/03/2030 para 16/03/2030", "Entrega no CD: de 13/03/2030 para 18/03/2030"])
        self.assertEqual({e["reason"] for e in log["events"][:2]}, {"caminhao quebrou"})
        # LOG numa carga: mudar o carregamento para um dia diferente da saida avisa (R3b)
        other = self._approved_log("LOG102", ("CP 200",))
        load = self._load([other]).json()
        dep = load["departure_date"]
        w = self.client.patch(f"/api/v1/logistics/logs/{other}/dates", json={"loading_date": "2030-03-12", "reason": "x"}, headers=self._h())
        self.assertIn("DEPARTURE_DIFFERS_FROM_LOADING", self._warnings(w))
        self.assertNotEqual(dep, "2030-03-12")

    # --- F5: saida real da carga e entrega real no CD ---------------------------------------

    def test_departed_and_delivered_are_real_dates_with_history_and_never_warn(self):
        a = self._approved_log("LOG101", ("CP 100",))
        b = self._approved_log("LOG102", ("CP 200",))
        load = self._load([a, b]).json()
        base = f"/api/v1/logistics/loads/{load['id']}"
        self.assertEqual((load["departed_on"], load["logs_total"], load["logs_delivered"]), (None, 2, 0))
        dep = lambda body: self.client.post(f"{base}/departed", json=body, headers=self._h())  # noqa: E731
        first = dep({"departed_on": "2020-01-04"})  # sabado no passado: data real nunca gera aviso
        self.assertEqual((first.status_code, first.json()["departed_on"], first.json()["events"][0]["text"]), (200, "2020-01-04", "Saiu em 04/01/2020"))
        self._err(dep({"departed_on": "2020-01-04"}), 422, "VALIDATION_ERROR")
        self._err(dep({"departed_on": "2020-01-06"}), 422, "VALIDATION_ERROR")  # mudar exige motivo
        second = dep({"departed_on": "2020-01-06", "reason": "digitei errado"}).json()
        self.assertEqual((second["departed_on"], second["events"][0]["text"], second["events"][0]["reason"]), ("2020-01-06", "Saida real alterada de 04/01/2020 para 06/01/2020", "digitei errado"))
        self.assertEqual(second["departure_date"], load["departure_date"])  # a prevista nao muda

        url = f"/api/v1/logistics/logs/{a}/delivery"
        post = lambda body: self.client.post(url, json=body, headers=self._h())  # noqa: E731
        self.assertEqual(post({"delivered_on": "2020-01-10", "delivery_proof_link": "javascript:x"}).status_code, 422)
        got = post({"delivered_on": "2020-01-11", "delivery_proof_link": "https://srv/comprovantes/log101.pdf"})
        self.assertEqual(got.status_code, 200, got.text)
        log = got.json()
        self.assertEqual((log["delivered_on"], log["delivery_proof_link"]), ("2020-01-11", "https://srv/comprovantes/log101.pdf"))
        self.assertEqual({e["text"] for e in log["events"][:2]}, {"Entregue no CD em 11/01/2020", "Comprovante de entrega registrado"})
        self._err(post({"delivered_on": "2020-01-12"}), 422, "VALIDATION_ERROR")  # mudar a data exige motivo
        moved = post({"delivered_on": "2020-01-12", "reason": "NF carimbada no dia seguinte"}).json()
        self.assertEqual((moved["delivered_on"], moved["delivery_proof_link"]), ("2020-01-12", "https://srv/comprovantes/log101.pdf"))  # link mantido
        self.assertEqual(moved["events"][0]["text"], "Entrega no CD (real): de 11/01/2020 para 12/01/2020")
        self._err(post({"delivered_on": "2020-01-12"}), 422, "VALIDATION_ERROR")  # nada mudou
        cleared = post({"delivered_on": "2020-01-12", "delivery_proof_link": None}).json()
        self.assertIsNone(cleared["delivery_proof_link"])
        listed = self.client.get("/api/v1/logistics/loads", headers=self._h("viewer")).json()["items"][0]
        self.assertEqual((listed["logs_total"], listed["logs_delivered"], listed["departed_on"]), (2, 1, "2020-01-06"))
        detail_log = [lg for lg in self.client.get(base, headers=self._h()).json()["logs"] if lg["id"] == a][0]
        self.assertEqual(detail_log["delivered_on"], "2020-01-12")

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
            ("patch", f"/loads/{load_id}", {"departure_date": "2026-11-01", "reason": "x"}),
            ("patch", f"/logs/{lid}/dates", {"loading_date": "2026-11-01", "reason": "x"}),
            ("post", f"/logs/{lid}/delivery", {"delivered_on": "2026-11-01"}),
            ("post", f"/loads/{load_id}/departed", {"departed_on": "2026-11-01"}),
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
