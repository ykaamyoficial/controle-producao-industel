"""Fase 1 da replica local: change_log + endpoints /sync contra PostgreSQL real."""

from __future__ import annotations

import asyncio
import os
import unittest

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.main import create_app
from api.app.modules.auth.models import Permission, Role, User
from api.app.modules.auth.permissions import ADMIN_PERMISSION_CODES, FISCAL_VIEW
from api.app.modules.auth.security import hash_password
from api.app.modules.auth.tokens import utcnow
from api.app.modules.proposals.models import ExpeditionItem, Proposal
from api.app.modules.sync.registry import SYNC_ENTITIES, SYNC_SCHEMA_VERSION
from api.tests.test_proposals_integration import (
    TEST_DATABASE_URL,
    _alembic_config,
    _integration_enabled,
    _item_payload,
    _proposal_payload,
)

PASSWORD = "Senha forte proposta 123"
TRUNCATE = "TRUNCATE TABLE change_log, security_events, auth_sessions, fiscal_events, fiscal_invoice_items, fiscal_invoices, fiscal_items, fiscal_records, expedition_events, expedition_items, galvanization_load_events, galvanization_load_items, galvanization_loads, proposal_events, proposal_items, proposals, sync_runs, role_permissions, user_roles, users, roles RESTART IDENTITY CASCADE"


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class SyncIntegrationTests(unittest.TestCase):
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
        async def _cleanup():
            async with get_engine().begin() as conn:
                await conn.execute(text(TRUNCATE))

        asyncio.run(_cleanup())
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
        self.headers = self._login("admin")

    async def _seed_users(self):
        async with get_engine().begin() as conn:
            await conn.execute(text(TRUNCATE))
        async with get_sessionmaker()() as session:
            admin_permissions = (await session.execute(select(Permission).where(Permission.code.in_(ADMIN_PERMISSION_CODES)))).scalars().all()
            admin_role = Role(code="admin", name="Administrador", active=True, system_role=True)
            admin_role.permissions.extend(admin_permissions)
            fiscal_role = Role(code="fiscal_only", name="Fiscal", active=True, system_role=False)
            fiscal_role.permissions.extend([permission for permission in admin_permissions if permission.code == FISCAL_VIEW])
            empty_role = Role(code="sem_acesso", name="Sem acesso", active=True, system_role=False)
            for username, role, superuser in (("admin", admin_role, True), ("fiscal", fiscal_role, False), ("ninguem", empty_role, False)):
                user = User(username=username, display_name=username, password_hash=hash_password(PASSWORD), active=True, is_superuser=superuser, password_changed_at=utcnow())
                user.roles.append(role)
                session.add(user)
            await session.commit()

    def _login(self, username):
        login = self.client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
        self.assertEqual(login.status_code, 200, login.text)
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    def _get(self, url, headers=None, **params):
        response = self.client.get(url, params=params, headers=headers or self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _create(self, number, items=None):
        response = self.client.post("/api/v1/proposals", json=_proposal_payload(number, items), headers=self.headers)
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def _ready_for_expedition(self, number):
        proposal = self._create(number, [_item_payload("1", requires_galvanization=False)])
        post = lambda url, body: self.client.post(url, json=body, headers=self.headers).json()  # noqa: E731
        released = post(f"/api/v1/proposals/{proposal['id']}/status", {"version": proposal["version"], "to_area": "PRODUCAO", "to_status": "LIBERADO_PRODUCAO", "reason": "Liberacao"})
        started = post(f"/api/v1/production/proposals/{proposal['id']}/start", {"version": released["version"]})
        done = post(f"/api/v1/production/proposals/{proposal['id']}/complete-items", {"version": started["version"]})
        self.assertEqual(done["current_area"], "EXPEDICAO", done)
        return done

    def _all_changes(self, since=0, headers=None, limit=500):
        changes, cursor = [], since
        while True:
            page = self._get("/api/v1/sync/changes", headers=headers, since=cursor, limit=limit)
            self.assertFalse(page["resync_required"])
            changes.extend(page["changes"])
            self.assertGreaterEqual(page["next_seq"], cursor)
            cursor = page["next_seq"]
            if not page["has_more"]:
                return changes, cursor

    # ---- captura ------------------------------------------------------------
    def test_empty_database_has_head_zero(self):
        head = self._get("/api/v1/sync/head")
        self.assertEqual(head["seq"], 0)
        self.assertEqual(head["min_seq_available"], 0)
        self.assertEqual(head["schema_version"], SYNC_SCHEMA_VERSION)
        self.assertEqual(head["entities"], [entity.name for entity in SYNC_ENTITIES])
        page = self._get("/api/v1/sync/changes", since=0)
        self.assertEqual((page["changes"], page["next_seq"], page["has_more"], page["resync_required"]), ([], 0, False, False))

    def test_write_generates_events_with_current_row(self):
        proposal = self._create("SYNC-1", [_item_payload("1"), _item_payload("2")])
        head = self._get("/api/v1/sync/head")
        self.assertGreater(head["seq"], 0)
        changes, cursor = self._all_changes()
        self.assertEqual(cursor, head["seq"])
        self.assertEqual([change["seq"] for change in changes], sorted(change["seq"] for change in changes))
        by_entity = {}
        for change in changes:
            by_entity.setdefault(change["entity"], []).append(change)
        self.assertEqual([change["id"] for change in by_entity["proposals"]], [proposal["id"]])
        self.assertEqual(len(by_entity["proposal_items"]), 2)
        row = by_entity["proposals"][0]["row"]
        self.assertEqual(by_entity["proposals"][0]["op"], "upsert")
        self.assertEqual(row["proposal_number"], "SYNC-1")
        self.assertEqual(row["version"], proposal["version"])
        self.assertEqual(row["proposal_date"], "2026-07-20")
        # Derivados materializados na escrita tambem entram no log.
        self.assertIn("fiscal_records", by_entity)
        self.assertIn("fiscal_items", by_entity)

    def test_client_behind_receives_only_what_it_missed(self):
        self._create("SYNC-A")
        _, cursor_a = self._all_changes()
        second = self._create("SYNC-B")
        third = self._create("SYNC-C")
        changes, cursor = self._all_changes(since=cursor_a)
        self.assertGreater(cursor, cursor_a)
        self.assertTrue(all(change["seq"] > cursor_a for change in changes))
        self.assertEqual(sorted(change["id"] for change in changes if change["entity"] == "proposals"), [second["id"], third["id"]])
        # Ja em dia: nada novo e o cursor nao anda.
        again, same = self._all_changes(since=cursor)
        self.assertEqual((again, same), ([], cursor))

    def test_pagination_does_not_skip_or_repeat(self):
        for index in range(4):
            self._create(f"SYNC-P{index}")
        full, cursor_full = self._all_changes()
        paged, cursor_paged = self._all_changes(limit=3)
        self.assertEqual(cursor_paged, cursor_full)
        key = lambda change: (change["entity"], change["id"])  # noqa: E731
        # A mesma linha pode reaparecer em paginas diferentes; o estado final e o mesmo.
        self.assertEqual({key(change): change["row"] for change in paged}, {key(change): change["row"] for change in full})

    def test_repeated_updates_collapse_to_latest_state(self):
        proposal = self._create("SYNC-U")
        _, cursor = self._all_changes()
        updated = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/status",
            json={"version": proposal["version"], "to_area": "PRODUCAO", "to_status": "LIBERADO_PRODUCAO", "reason": "Liberacao"},
            headers=self.headers,
        ).json()
        self.client.post(f"/api/v1/production/proposals/{proposal['id']}/start", json={"version": updated["version"]}, headers=self.headers)
        changes, _ = self._all_changes(since=cursor)
        proposal_changes = [change for change in changes if change["entity"] == "proposals"]
        self.assertEqual(len(proposal_changes), 1)
        current = self._get(f"/api/v1/proposals/{proposal['id']}")
        self.assertEqual(proposal_changes[0]["row"]["version"], current["version"])
        self.assertEqual(proposal_changes[0]["row"]["current_status"], current["current_status"])

    def test_reads_do_not_generate_events(self):
        self._ready_for_expedition("SYNC-R")
        before = self._get("/api/v1/sync/head")["seq"]
        for url in ("/api/v1/proposals", "/api/v1/shipping/proposals", "/api/v1/fiscal/records", "/api/v1/fiscal/indicators", "/api/v1/sync/changes", "/api/v1/sync/head"):
            self._get(url)
        self._get("/api/v1/sync/snapshot", entity="proposals")
        self.assertEqual(self._get("/api/v1/sync/head")["seq"], before)

    def test_rollback_does_not_generate_events(self):
        proposal = self._create("SYNC-RB")
        before = self._get("/api/v1/sync/head")["seq"]

        async def _change_and_rollback():
            async with get_sessionmaker()() as session:
                row = await session.get(Proposal, proposal["id"])
                row.notes = "nao deve persistir"
                await session.flush()
                await session.rollback()
                # Commit seguinte na mesma sessao nao pode ressuscitar o evento.
                await session.commit()

        asyncio.run(_change_and_rollback())
        self.assertEqual(self._get("/api/v1/sync/head")["seq"], before)

    def test_delete_becomes_tombstone(self):
        done = self._ready_for_expedition("SYNC-D")
        _, cursor = self._all_changes()

        async def _delete():
            async with get_sessionmaker()() as session:
                item = (await session.execute(select(ExpeditionItem).where(ExpeditionItem.proposal_id == done["id"]))).scalars().first()
                item_id = item.id
                await session.execute(text("DELETE FROM expedition_events WHERE expedition_item_id = :id"), {"id": item_id})
                await session.delete(item)
                await session.commit()
                return item_id

        item_id = asyncio.run(_delete())
        page = self._get("/api/v1/sync/changes", since=cursor)
        tombstones = [change for change in page["changes"] if change["entity"] == "expedition_items" and change["id"] == item_id]
        self.assertEqual(len(tombstones), 1)
        self.assertEqual((tombstones[0]["op"], tombstones[0]["row"]), ("delete", None))

    def test_commit_waits_for_the_sequence_lock(self):
        # A ordem dos seq so e a ordem dos commits porque cada escrita segura o
        # advisory lock do INSERT no change_log ate o COMMIT.
        from api.app.modules.sync.capture import _SEQ_LOCK_KEY

        proposal = self._create("SYNC-LOCK")
        before = self._get("/api/v1/sync/head")["seq"]

        async def _scenario():
            async def _write():
                async with get_sessionmaker()() as session:
                    row = await session.get(Proposal, proposal["id"])
                    row.notes = "escrita concorrente"
                    await session.commit()

            async with get_engine().connect() as holder:
                transaction = await holder.begin()
                await holder.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SEQ_LOCK_KEY})
                writer = asyncio.create_task(_write())
                await asyncio.sleep(0.7)
                blocked = not writer.done()
                await transaction.rollback()
            await asyncio.wait_for(writer, timeout=10)
            await dispose_engine()
            return blocked

        self.assertTrue(asyncio.run(_scenario()), "o commit nao esperou o lock de sequencia")
        self.assertEqual(self._get("/api/v1/sync/head")["seq"], before + 1)

    # ---- resync -------------------------------------------------------------
    def test_cursor_older_than_retained_log_requires_resync(self):
        for index in range(3):
            self._create(f"SYNC-X{index}")
        head = self._get("/api/v1/sync/head")["seq"]

        async def _purge():
            async with get_engine().begin() as conn:
                await conn.execute(text("DELETE FROM change_log WHERE seq <= :cut"), {"cut": head - 2})

        asyncio.run(_purge())
        self.assertEqual(self._get("/api/v1/sync/head")["min_seq_available"], head - 1)
        stale = self._get("/api/v1/sync/changes", since=0)
        self.assertTrue(stale["resync_required"])
        self.assertEqual((stale["changes"], stale["next_seq"]), ([], 0))
        # Cursor exatamente na borda ainda consegue seguir incremental.
        edge = self._get("/api/v1/sync/changes", since=head - 2)
        self.assertFalse(edge["resync_required"])
        self.assertEqual(edge["next_seq"], head)

    def test_cursor_ahead_of_database_requires_resync(self):
        self._create("SYNC-AHEAD")
        head = self._get("/api/v1/sync/head")["seq"]
        self.assertTrue(self._get("/api/v1/sync/changes", since=head + 50)["resync_required"])

    # ---- snapshot -----------------------------------------------------------
    def test_snapshot_pages_through_every_row(self):
        created = [self._create(f"SYNC-S{index}")["id"] for index in range(5)]
        ids, after = [], 0
        while True:
            page = self._get("/api/v1/sync/snapshot", entity="proposals", after_id=after, limit=2)
            ids.extend(row["id"] for row in page["rows"])
            after = page["next_after_id"]
            if not page["has_more"]:
                break
        self.assertEqual(ids, sorted(created))
        self.assertEqual(self._get("/api/v1/sync/snapshot", entity="proposals", after_id=after)["rows"], [])

    def test_snapshot_then_changes_reaches_same_state_as_database(self):
        self._ready_for_expedition("SYNC-FULL-1")
        head = self._get("/api/v1/sync/head")
        replica = {}
        for entity in head["entities"]:
            after = 0
            while True:
                page = self._get("/api/v1/sync/snapshot", entity=entity, after_id=after, limit=3)
                for row in page["rows"]:
                    replica[(entity, row["id"])] = row
                after = page["next_after_id"]
                if not page["has_more"]:
                    break
        self._ready_for_expedition("SYNC-FULL-2")
        changes, _ = self._all_changes(since=head["seq"])
        for change in changes:
            if change["op"] == "delete":
                replica.pop((change["entity"], change["id"]), None)
            else:
                replica[(change["entity"], change["id"])] = change["row"]
        expected = {}
        for entity in head["entities"]:
            for row in self._get("/api/v1/sync/snapshot", entity=entity, limit=5000)["rows"]:
                expected[(entity, row["id"])] = row
        self.assertEqual(replica, expected)

    # ---- aviso em tempo real ------------------------------------------------
    def test_websocket_announces_head_on_connect_and_after_each_write(self):
        self._create("SYNC-WS-0")
        head = self._get("/api/v1/sync/head")["seq"]
        with TestClient(create_app()) as client:
            headers = {"Authorization": self.headers["Authorization"]}
            with client.websocket_connect("/api/v1/sync/ws", headers=headers) as websocket:
                self.assertEqual(websocket.receive_json(), {"type": "sync.head", "seq": head})
                created = client.post("/api/v1/proposals", json=_proposal_payload("SYNC-WS-1"), headers=headers)
                self.assertLess(created.status_code, 300, created.text)
                notice = websocket.receive_json()
                new_head = client.get("/api/v1/sync/head", headers=headers).json()["seq"]
                self.assertEqual(notice, {"type": "sync.head", "seq": new_head})
                self.assertGreater(new_head, head)

    def test_websocket_rejects_missing_or_invalid_token(self):
        from starlette.websockets import WebSocketDisconnect

        for headers in ({}, {"Authorization": "Bearer token-invalido"}):
            with self.assertRaises(WebSocketDisconnect) as raised:
                with self.client.websocket_connect("/api/v1/sync/ws", headers=headers):
                    pass
            self.assertEqual(raised.exception.code, 4401)

    # ---- permissoes ---------------------------------------------------------
    def test_requires_authentication(self):
        for url in ("/api/v1/sync/head", "/api/v1/sync/changes", "/api/v1/sync/snapshot?entity=proposals"):
            self.assertEqual(self.client.get(url).status_code, 401, url)

    def test_user_only_receives_entities_it_may_view(self):
        self._ready_for_expedition("SYNC-PERM")
        admin_head = self._get("/api/v1/sync/head")
        fiscal = self._login("fiscal")
        head = self._get("/api/v1/sync/head", headers=fiscal)
        self.assertEqual(head["entities"], ["proposals", "proposal_items", "fiscal_records", "fiscal_items", "fiscal_invoices", "fiscal_invoice_items"])
        changes, cursor = self._all_changes(headers=fiscal)
        entities = {change["entity"] for change in changes}
        self.assertIn("fiscal_records", entities)
        self.assertNotIn("expedition_items", entities)
        # O cursor acompanha o head mesmo pulando eventos que o usuario nao ve.
        self.assertEqual(cursor, admin_head["seq"])
        denied = self.client.get("/api/v1/sync/snapshot", params={"entity": "expedition_items"}, headers=fiscal)
        self.assertEqual(denied.status_code, 403, denied.text)
        unknown = self.client.get("/api/v1/sync/snapshot", params={"entity": "users"}, headers=self.headers)
        self.assertEqual(unknown.status_code, 403, unknown.text)

    def test_user_without_view_permission_receives_nothing(self):
        self._create("SYNC-NONE")
        nobody = self._login("ninguem")
        self.assertEqual(self._get("/api/v1/sync/head", headers=nobody)["entities"], [])
        changes, cursor = self._all_changes(headers=nobody)
        self.assertEqual(changes, [])
        self.assertEqual(cursor, self._get("/api/v1/sync/head")["seq"])


if __name__ == "__main__":
    unittest.main()
