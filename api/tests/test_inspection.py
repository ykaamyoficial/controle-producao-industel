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
            await conn.execute(text("UPDATE inspections SET stage_since = now() - make_interval(days => :d) WHERE id = :i"), {"d": days, "i": iid})

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

    def test_unknown_inspection_is_404(self):
        resp = self.client.get("/api/v1/inspections/999", headers=self._h())
        self.assertEqual((resp.status_code, resp.json()["error"]["code"]), (404, "INSPECTION_NOT_FOUND"))


if __name__ == "__main__":
    unittest.main()
