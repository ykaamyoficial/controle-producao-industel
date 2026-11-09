"""Modulo de Inspecao (NQT): ciclo completo via HTTP real com PostgreSQL de teste, permissoes e regras.

Exige APP_ENV=test e POSTGRES_TEST_DATABASE_URL (nome com `test`), igual as demais integracoes Postgres.
Os testes de schema e de dias na etapa nao precisam de banco.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
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
from api.app.modules.auth.permissions import INSPECTION_EDIT, INSPECTION_VIEW
from api.app.modules.inspection import schemas, service
from api.app.modules.logistics import calendar_rules
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


class InspectionPureTests(unittest.TestCase):
    def test_days_in_stage_is_today_minus_stage_since(self):
        since = datetime(2026, 10, 10, 23, 0, tzinfo=timezone.utc)
        self.assertEqual(service.days_in_stage(since, date(2026, 10, 15)), 5)
        self.assertEqual(service.days_in_stage(since, date(2026, 10, 10)), 0)
        self.assertEqual(service.days_in_stage(since, date(2026, 10, 1)), 0)  # nunca negativo

    def test_link_validation_accepts_url_and_paths_rejects_other_schemes(self):
        for ok in ("https://x.com/a.pdf", r"\\servidor\bim\PD1180.pdf", r"C:\bim\PD 1180.pdf", "file:///c:/a.pdf"):
            self.assertEqual(schemas.DocPayload(doc_link=ok).doc_link, ok)
        for bad in ("javascript:alert(1)", "data:text/html,x", "ftp://x/a.pdf", "relativo/a.pdf", "https://x.com/a b.pdf", "http://x\n/a"):
            with self.assertRaises(ValidationError, msg=bad):
                schemas.DocPayload(doc_link=bad)
        with self.assertRaises(ValidationError):
            schemas.DocPayload(doc_link="https://x.com/" + "a" * 500)

    def test_nqt_is_uppercased_and_reject_reason_required(self):
        self.assertEqual(schemas.NqtPayload(nqt_code=" nqt-0412 ").nqt_code, "NQT-0412")
        with self.assertRaises(ValidationError):
            schemas.NqtPayload(nqt_code="   ")
        with self.assertRaises(ValidationError):
            schemas.RejectPayload(reason="   ")


@unittest.skipUnless(_integration_enabled(), "Exige APP_ENV=test e POSTGRES_TEST_DATABASE_URL.")
class InspectionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {k: os.environ.get(k) for k in ("DATABASE_URL", "APP_ENV", "SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "inspection-integration-secret-key-32chars"
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
        self.tokens = asyncio.run(self._seed())
        self.client = TestClient(create_app())

    async def _reset(self):
        async with get_engine().begin() as conn:
            await conn.execute(text(
                "TRUNCATE TABLE inspection_events, inspections, security_events, proposal_events, proposal_items, proposals, "
                "role_permissions, user_roles, users, roles, permissions RESTART IDENTITY CASCADE"
            ))

    async def _seed(self) -> dict[str, str]:
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
            for number, pd in (("CP 100", "PD-1180"), ("CP 101", "PD-1180"), ("CP 200", "PD-1195"), ("CP 300", "PD-1201"), ("CP 400", None)):
                session.add(Proposal(proposal_number=number, customer_name="Cliente " + number, order_reference=pd))
            tokens = {}
            for name, perms in (("editor", [INSPECTION_VIEW, INSPECTION_EDIT]), ("viewer", [INSPECTION_VIEW]), ("none", ["proposals.view"])):
                user = await users_service.create_user(
                    session, UserCreate(username=f"insp.{name}", display_name=name.title(), password="senha-insp-teste-123", permission_codes=perms), boot,
                )
                tokens[name] = create_access_token(user.id)[0]
            await session.commit()
        return tokens

    # --- helpers -------------------------------------------------------------------------

    def _h(self, who: str = "editor") -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[who]}"}

    def _create(self, pd: str = "PD-1180", **extra):
        return self.client.post("/api/v1/inspections", json={"pd_code": pd, **extra}, headers=self._h())

    def _post(self, iid: int, action: str, body: dict | None = None, who: str = "editor"):
        return self.client.post(f"/api/v1/inspections/{iid}/{action}", json=body or {}, headers=self._h(who))

    def _get(self, iid: int) -> dict:
        return self.client.get(f"/api/v1/inspections/{iid}", headers=self._h()).json()

    def _to_nqt(self, pd: str = "PD-1180", nqt: str = "NQT-0412") -> int:
        iid = self._create(pd).json()["id"]
        self.assertEqual(self._post(iid, "request", {"pd_registered": True}).status_code, 200)
        self.assertEqual(self._post(iid, "nqt", {"nqt_code": nqt}).status_code, 200)
        return iid

    # --- ciclos --------------------------------------------------------------------------

    def test_full_cycle_dispensa_to_finished_and_logistics_query(self):
        created = self._create()
        self.assertEqual(created.status_code, 201, created.text)
        body = created.json()
        self.assertEqual((body["stage"], body["attempt"], body["days_in_stage"], body["finished"]), ("pendente", 1, 0, False))
        self.assertEqual(body["proposal_numbers"], ["CP 100", "CP 101"])
        iid = body["id"]

        self.assertEqual(self._post(iid, "request", {"pd_registered": True}).json()["stage"], "solicitada")
        nqt = self._post(iid, "nqt", {"nqt_code": "nqt-0412"}).json()
        self.assertEqual((nqt["stage"], nqt["nqt_code"]), ("nqt", "NQT-0412"))
        self.assertEqual(self._post(iid, "decision", {"decision": "dispensa"}).json()["stage"], "dispensa")
        self.assertEqual(self._post(iid, "pit", {"pit_link": r"\\servidor\pit\PD1180.pdf"}).json()["stage"], "doc")

        async def finished_before():
            async with get_sessionmaker()() as s:
                return await service.is_pd_inspection_finished(s, "pd-1180")

        self.assertFalse(asyncio.run(finished_before()))
        done = self._post(iid, "doc", {"doc_link": r"\\servidor\bim\PD1180.pdf"}).json()
        self.assertEqual((done["stage"], done["finished"]), ("fim", True))
        self.assertTrue(asyncio.run(finished_before()))

        events = self._get(iid)["events"]
        self.assertEqual([e["stage"] for e in events], ["fim", "doc", "dispensa", "nqt", "solicitada", "pendente"])
        self.assertTrue(all(e["actor_name"] == "Editor" for e in events))

        finished = self.client.get("/api/v1/inspections/finished", headers=self._h("viewer")).json()
        self.assertEqual(finished["total"], 1)
        item = finished["items"][0]
        self.assertEqual((item["pd_code"], item["nqt_code"]), ("PD-1180", "NQT-0412"))
        self.assertEqual([p["proposal_number"] for p in item["proposals"]], ["CP 100", "CP 101"])

        async def audits():
            async with get_sessionmaker()() as s:
                return (await s.execute(select(SecurityEvent.event_type).where(SecurityEvent.event_type.like("INSPECTION_%")))).scalars().all()

        types = asyncio.run(audits())
        self.assertEqual(types.count("INSPECTION_CREATED"), 1)
        self.assertEqual(types.count("INSPECTION_STAGE_CHANGED"), 5)

    def test_in_loco_reject_then_new_attempt_then_approve(self):
        iid = self._to_nqt("PD-1195", "NQT-0418")
        self.assertEqual(self._post(iid, "decision", {"decision": "inloco"}).status_code, 422)  # sem data
        visit = (date.today() + timedelta(days=3)).isoformat()  # pode cair em fim de semana: confirm_dates=True nos posts
        loco = self._post(iid, "decision", {"decision": "inloco", "visit_date": visit, "confirm_dates": True}).json()
        self.assertEqual((loco["stage"], loco["visit_date"]), ("inloco", visit))

        self.assertEqual(self._post(iid, "reject", {"reason": "  "}).status_code, 422)
        self.assertEqual(self._post(iid, "reject", {}).status_code, 422)
        rej = self._post(iid, "reject", {"reason": "furo fora de medida"}).json()
        self.assertEqual((rej["stage"], rej["attempt"], rej["rejection_reason"], rej["nqt_code"]), ("pendente", 2, "furo fora de medida", "NQT-0418"))
        top = rej["events"][0]
        self.assertEqual((top["reason"], top["attempt"]), ("furo fora de medida", 2))

        # nova tentativa: volta a "pendente"; precisa pedir de novo, depois registra o NQT (mesmo codigo) e segue
        self.assertEqual(self._post(iid, "nqt", {"nqt_code": "NQT-0418"}).status_code, 409)
        self.assertEqual(self._post(iid, "request", {"pd_registered": True}).json()["stage"], "solicitada")
        self.assertEqual(self._post(iid, "nqt", {"nqt_code": "NQT-0418"}).status_code, 200)
        self._post(iid, "decision", {"decision": "inloco", "visit_date": visit, "confirm_dates": True})
        self.assertEqual(self._post(iid, "approve").json()["stage"], "doc")
        self.assertEqual(self._post(iid, "doc", {"doc_link": "https://portal/doc.pdf"}).json()["stage"], "fim")
        # historico guarda a tentativa anterior
        self.assertIn(1, {e["attempt"] for e in self._get(iid)["events"]})

    def test_cannot_finish_without_doc(self):
        iid = self._to_nqt()
        # nao pula etapas
        for action, body in (("doc", {"doc_link": "https://x/a.pdf"}), ("approve", None), ("pit", {"pit_link": "https://x/p.pdf"})):
            resp = self._post(iid, action, body)
            self.assertEqual(resp.status_code, 409, action)
            self.assertEqual(resp.json()["error"]["code"], "INSPECTION_INVALID_STAGE")
        self._post(iid, "decision", {"decision": "dispensa"})
        self._post(iid, "pit", {"pit_link": "https://x/p.pdf"})
        self.assertEqual(self._post(iid, "doc", {}).status_code, 422)
        self.assertEqual(self._post(iid, "doc", {"doc_link": "javascript:alert(1)"}).status_code, 422)
        self.assertEqual(self._get(iid)["stage"], "doc")
        self.assertFalse(self._get(iid)["finished"])

    def test_nqt_is_unique_with_clear_error(self):
        self._to_nqt("PD-1180", "NQT-0412")
        other = self._create("PD-1195").json()["id"]
        dup = self._post(other, "nqt", {"nqt_code": "nqt-0412"})
        self.assertEqual(dup.status_code, 409)
        self.assertEqual(dup.json()["error"]["code"], "INSPECTION_NQT_ALREADY_EXISTS")
        self.assertIn("NQT", dup.json()["error"]["message"])
        self.assertEqual(self._get(other)["stage"], "pendente")

    def test_one_inspection_per_pd_and_pd_must_exist(self):
        self.assertEqual(self._create().status_code, 201)
        dup = self._create("pd-1180")
        self.assertEqual((dup.status_code, dup.json()["error"]["code"]), (409, "INSPECTION_ALREADY_EXISTS"))
        missing = self._create("PD-9999")
        self.assertEqual((missing.status_code, missing.json()["error"]["code"]), (404, "INSPECTION_PD_NOT_FOUND"))

    def test_new_inspection_is_pendente_and_pd_registered_is_ignored(self):
        for pd, extra in (("PD-1180", {}), ("PD-1195", {"pd_registered": False}), ("PD-1201", {"pd_registered": True})):
            body = self._create(pd, **extra).json()
            self.assertEqual(body["stage"], "pendente", pd)
            self.assertEqual(body["events"][0]["text"], "Solicitacao pendente")
            self.assertEqual(self._post(body["id"], "nqt", {"nqt_code": "X1"}).status_code, 409)
        self.assertEqual(len(self.client.get("/api/v1/inspections?stage=pendente", headers=self._h()).json()["items"]), 3)

    def test_request_true_goes_to_solicitada_false_to_cadastro(self):
        a = self._create("PD-1180").json()["id"]
        resp = self._post(a, "request", {"pd_registered": True})
        self.assertEqual((resp.status_code, resp.json()["stage"]), (200, "solicitada"))
        self.assertEqual(resp.json()["events"][0]["text"], "Inspecao solicitada no portal")
        b = self._create("PD-1195").json()["id"]
        resp = self._post(b, "request", {"pd_registered": False})
        self.assertEqual((resp.status_code, resp.json()["stage"]), (200, "cadastro"))
        self.assertEqual(resp.json()["events"][0]["text"], "Aguardando cadastro do PD no portal")
        self.assertEqual(self._post(b, "register-pd").json()["stage"], "solicitada")
        self.assertEqual(self._post(b, "request", {}).status_code, 422)  # pd_registered obrigatorio

    def test_request_outside_pendente_is_refused(self):
        iid = self._to_nqt()
        resp = self._post(iid, "request", {"pd_registered": True})
        self.assertEqual((resp.status_code, resp.json()["error"]["code"]), (409, "INSPECTION_INVALID_STAGE"))
        self.assertEqual(self._get(iid)["stage"], "nqt")

    def test_check_constraint_accepts_pendente(self):
        async def insert():
            async with get_engine().begin() as conn:
                await conn.execute(text("INSERT INTO inspections (pd_code, stage) VALUES ('PD-X', 'pendente')"))
                with_bad = None
                try:
                    async with conn.begin_nested():
                        await conn.execute(text("INSERT INTO inspections (pd_code, stage) VALUES ('PD-Y', 'bogus')"))
                except Exception as exc:  # noqa: BLE001
                    with_bad = exc
                return with_bad

        self.assertIsNotNone(asyncio.run(insert()))

    def test_list_filters_counts_and_days_in_stage(self):
        a = self._to_nqt("PD-1180", "NQT-0412")
        self._create("PD-1195")
        asyncio.run(self._age(a, 5))
        listing = self.client.get("/api/v1/inspections", headers=self._h("viewer")).json()
        self.assertEqual((listing["total"], listing["counts"]), (2, {"open": 2, "finished": 0, "to_request": 0}))
        by_pd = {i["pd_code"]: i for i in listing["items"]}
        self.assertEqual(by_pd["PD-1180"]["days_in_stage"], 5)
        self.assertEqual(by_pd["PD-1195"]["days_in_stage"], 0)
        today = calendar_rules.local_today()
        self.assertEqual(by_pd["PD-1180"]["business_days_in_stage"], calendar_rules.business_days_between(today - timedelta(days=5), today))
        self.assertLessEqual(by_pd["PD-1180"]["business_days_in_stage"], 5)
        self.assertEqual(by_pd["PD-1195"]["business_days_in_stage"], 0)
        only = lambda **q: self.client.get("/api/v1/inspections", params=q, headers=self._h()).json()["items"]  # noqa: E731
        self.assertEqual([i["pd_code"] for i in only(stage="nqt")], ["PD-1180"])
        self.assertEqual([i["pd_code"] for i in only(search="nqt-04")], ["PD-1180"])
        self.assertEqual([i["pd_code"] for i in only(search="CP 200")], ["PD-1195"])
        self.assertEqual(len(only(stage="open")), 2)
        self.assertEqual(self.client.get("/api/v1/inspections?stage=bogus", headers=self._h()).status_code, 422)
        # mudar de etapa zera os dias
        self._post(a, "decision", {"decision": "dispensa"})
        self.assertEqual(self._get(a)["days_in_stage"], 0)

    async def _age(self, iid: int, days: int):
        async with get_engine().begin() as conn:
            await conn.execute(text("UPDATE inspections SET stage_since = now() - make_interval(days => :d), stage_occurred_on = NULL WHERE id = :i"), {"d": days, "i": iid})  # NULL = linha antiga: o desde cai para stage_since

    # --- F3: andamento com data real, atualizar atrasado, remarcar e corrigir -----------------

    def _ago(self, days: int) -> str:
        return (calendar_rules.local_today() - timedelta(days=days)).isoformat()

    def test_transitions_accept_occurred_on_and_note_and_never_block_on_date(self):
        iid = self._create().json()["id"]
        one = self._post(iid, "request", {"pd_registered": True, "occurred_on": self._ago(10), "note": "  pedido por e-mail  "}).json()
        self.assertEqual((one["stage_since_date"], one["days_in_stage"]), (self._ago(10), 10))
        top = one["events"][0]
        self.assertEqual((top["occurred_on"], top["note"], top["kind"]), (self._ago(10), "pedido por e-mail", "transition"))
        self.assertIsNotNone(top["created_at"])  # "registrado em" continua o instante real do registro
        # sem occurred_on: hoje; data futura tambem e aceita (o sistema nunca trava por data)
        two = self._post(iid, "nqt", {"nqt_code": "NQT-1"}).json()
        self.assertEqual((two["stage_since_date"], two["days_in_stage"], two["events"][0]["occurred_on"]), (self._ago(0), 0, self._ago(0)))
        future = (calendar_rules.local_today() + timedelta(days=5)).isoformat()
        three = self._post(iid, "decision", {"decision": "dispensa", "occurred_on": future}).json()
        self.assertEqual((three["stage"], three["stage_since_date"], three["days_in_stage"]), ("dispensa", future, 0))
        self.assertEqual(self._post(iid, "pit", {"pit_link": "https://x/p.pdf", "occurred_on": "2020-02-30"}).status_code, 422)  # data inexistente

    def test_catch_up_applies_ordered_steps_all_or_nothing(self):
        iid = self._create().json()["id"]
        steps = [
            {"action": "request", "pd_registered": True, "occurred_on": self._ago(20), "note": "portal"},
            {"action": "nqt", "nqt_code": "nqt-9", "occurred_on": self._ago(15)},
            {"action": "decision", "decision": "dispensa", "occurred_on": self._ago(12)},
            {"action": "pit", "pit_link": "https://x/pit.pdf", "occurred_on": self._ago(8)},
            {"action": "doc", "doc_link": "https://x/doc.pdf", "occurred_on": self._ago(3)},
        ]
        # ordem errada no passo 3 (aprovar sem ter ido a in loco): nada e gravado
        bad = [*steps[:2], {"action": "approve"}]
        r = self._post(iid, "catch-up", {"steps": bad})
        self.assertEqual((r.status_code, r.json()["error"]["code"], r.json()["error"]["details"]["step_index"]), (409, "INSPECTION_INVALID_STAGE", 2))
        now = self._get(iid)
        self.assertEqual((now["stage"], now["nqt_code"], len(now["events"])), ("pendente", None, 1))
        # passo incompleto: 422 apontando o passo
        r = self._post(iid, "catch-up", {"steps": [steps[0], {"action": "nqt"}]})
        self.assertEqual((r.status_code, r.json()["error"]["details"]["step_index"]), (422, 1))
        self.assertEqual(self._get(iid)["stage"], "pendente")
        # sequencia valida: tudo de uma vez, cada evento com a sua data
        done = self._post(iid, "catch-up", {"steps": steps})
        self.assertEqual(done.status_code, 200, done.text)
        body = done.json()
        self.assertEqual((body["stage"], body["nqt_code"], body["finished"], body["days_in_stage"], body["stage_since_date"]), ("fim", "NQT-9", True, 3, self._ago(3)))
        self.assertEqual([(e["stage"], e["occurred_on"]) for e in body["events"][:5]], [("fim", self._ago(3)), ("doc", self._ago(8)), ("dispensa", self._ago(12)), ("nqt", self._ago(15)), ("solicitada", self._ago(20))])

    def test_catch_up_visit_date_only_warns_and_needs_confirmation(self):
        # "hoje" fixo (quinta 2030-03-14) e visita/aprovacao em dias uteis passados: o resultado nao depende do dia em que o teste roda
        visit, approved = "2030-03-12", "2030-03-13"
        steps = [
            {"action": "request", "pd_registered": True}, {"action": "nqt", "nqt_code": "N-7"},
            {"action": "decision", "decision": "inloco", "visit_date": visit},
            {"action": "approve", "occurred_on": approved},
        ]
        with patch.object(calendar_rules, "local_today", return_value=date(2030, 3, 14)):
            iid = self._create().json()["id"]
            # sem passo posterior a visita no passado avisa
            r = self._post(iid, "catch-up", {"steps": steps[:3]})
            self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "DATE_CONFIRMATION_REQUIRED"))
            self.assertEqual([w["code"] for w in r.json()["error"]["details"]["warnings"]], ["DATE_IN_PAST"])
            self.assertEqual(self._get(iid)["stage"], "pendente")
            # confirmando, grava
            ok = self._post(iid, "catch-up", {"steps": steps[:3], "confirm_dates": True})
            self.assertEqual((ok.status_code, ok.json()["stage"], ok.json()["visit_date"]), (200, "inloco", visit))
            # com approve depois a visita ja aconteceu: a data passada nao e aviso e nao precisa confirmar
            # PD-1195 com NQT e visita proprias: NQT repetido e a mesma visita da PD-1180 geram 409 (nao e o caso testado)
            other = self._create("PD-1195").json()["id"]
            other_steps = [
                {"action": "request", "pd_registered": True}, {"action": "nqt", "nqt_code": "N-8"},
                {"action": "decision", "decision": "inloco", "visit_date": "2030-03-11"},
                {"action": "approve", "occurred_on": approved},
            ]
            done = self._post(other, "catch-up", {"steps": other_steps})
            self.assertEqual((done.status_code, done.json()["stage"], done.json()["visit_date"]), (200, "doc", "2030-03-11"), done.text)

    def test_reschedule_visit_keeps_attempt_and_logs_from_to(self):
        iid = self._to_nqt("PD-1195", "NQT-0418")
        self.assertEqual(self._post(iid, "reschedule-visit", {"visit_date": "2031-05-14", "reason": "x"}).status_code, 409)  # ainda nao esta in loco
        self._post(iid, "decision", {"decision": "inloco", "visit_date": "2031-05-13"})
        self.assertEqual(self._post(iid, "reschedule-visit", {"visit_date": "2031-05-14"}).status_code, 422)  # motivo obrigatorio
        self.assertEqual(self._post(iid, "reschedule-visit", {"visit_date": "2031-05-13", "reason": "x"}).status_code, 422)  # nao mudou
        past = self._post(iid, "reschedule-visit", {"visit_date": "2020-01-07", "reason": "x"})
        self.assertEqual((past.status_code, past.json()["error"]["code"]), (409, "DATE_CONFIRMATION_REQUIRED"))
        out = self._post(iid, "reschedule-visit", {"visit_date": "2031-05-14", "reason": "Equatorial pediu outro dia"}).json()
        self.assertEqual((out["stage"], out["attempt"], out["visit_date"]), ("inloco", 1, "2031-05-14"))
        top = out["events"][0]
        self.assertEqual((top["kind"], top["reason"], top["text"]), ("visit_rescheduled", "Equatorial pediu outro dia", "Visita in loco remarcada de 13/05/2031 para 14/05/2031"))

    def test_correct_occurred_on_recalculates_since_only_for_current_stage(self):
        iid = self._create().json()["id"]
        self._post(iid, "request", {"pd_registered": True, "occurred_on": self._ago(9)})
        detail = self._post(iid, "nqt", {"nqt_code": "NQT-5", "occurred_on": self._ago(4)}).json()
        nqt_event, request_event = detail["events"][0], detail["events"][1]
        url = lambda e: f"events/{e['id']}/occurred-on"  # noqa: E731
        self.assertEqual(self._post(iid, url(nqt_event), {"occurred_on": self._ago(2)}).status_code, 422)  # motivo obrigatorio
        # evento de etapa anterior: o "desde" nao muda
        older = self._post(iid, url(request_event), {"occurred_on": self._ago(11), "reason": "data errada"}).json()
        self.assertEqual(older["stage_since_date"], self._ago(4))
        self.assertEqual([e["occurred_on"] for e in older["events"] if e["kind"] == "transition"][:2], [self._ago(4), self._ago(11)])
        self.assertIn(f"de {(calendar_rules.local_today() - timedelta(days=9)).strftime('%d/%m/%Y')} para", older["events"][0]["text"])
        self.assertEqual((older["events"][0]["kind"], older["events"][0]["reason"]), ("date_correction", "data errada"))
        # evento da etapa atual: recalcula o "desde" e os dias
        cur = self._post(iid, url(nqt_event), {"occurred_on": self._ago(7), "reason": "registrado depois"}).json()
        self.assertEqual((cur["stage_since_date"], cur["days_in_stage"]), (self._ago(7), 7))
        # mesma data, anotacao/correcao e evento de outra inspecao nao podem ser corrigidos
        self.assertEqual(self._post(iid, url(nqt_event), {"occurred_on": self._ago(7), "reason": "x"}).status_code, 422)
        self.assertEqual(self._post(iid, url(cur["events"][0]), {"occurred_on": self._ago(1), "reason": "x"}).status_code, 422)
        other = self._create("PD-1195").json()["id"]
        r = self._post(other, url(nqt_event), {"occurred_on": self._ago(1), "reason": "x"})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (404, "INSPECTION_EVENT_NOT_FOUND"))

    # --- permissoes ----------------------------------------------------------------------

    def test_permissions_are_enforced(self):
        iid = self._create().json()["id"]
        calls = [
            ("get", "/api/v1/inspections", None),
            ("get", f"/api/v1/inspections/{iid}", None),
            ("get", "/api/v1/inspections/finished", None),
        ]
        for method, url, _ in calls:
            self.assertEqual(self.client.get(url).status_code, 401)
            self.assertEqual(self.client.get(url, headers=self._h("none")).status_code, 403, url)
            self.assertEqual(self.client.get(url, headers=self._h("viewer")).status_code, 200, url)
        denied = self.client.post("/api/v1/inspections", json={"pd_code": "PD-1195"}, headers=self._h("viewer"))
        self.assertEqual((denied.status_code, denied.json()["error"]["code"]), (403, "PERMISSION_DENIED"))
        self.assertEqual(self._post(iid, "nqt", {"nqt_code": "N1"}, who="viewer").status_code, 403)
        self.assertEqual(self._post(iid, "nqt", {"nqt_code": "N1"}, who="none").status_code, 403)
        self.assertEqual(self._get(iid)["stage"], "pendente")
        self.assertEqual(self._post(iid, "request", {"pd_registered": True}, who="viewer").status_code, 403)
        for path, body in (("catch-up", {"steps": [{"action": "approve"}]}), ("reschedule-visit", {"visit_date": "2031-05-14", "reason": "x"}), ("events/1/occurred-on", {"occurred_on": "2031-05-14", "reason": "x"})):
            for who in ("viewer", "none"):
                self.assertEqual(self._post(iid, path, body, who=who).status_code, 403, (path, who))

    def test_unknown_inspection_is_404(self):
        resp = self.client.get("/api/v1/inspections/999", headers=self._h())
        self.assertEqual((resp.status_code, resp.json()["error"]["code"]), (404, "INSPECTION_NOT_FOUND"))


if __name__ == "__main__":
    unittest.main()
