"""Reuso de refresh token registrado uma vez por familia, e retencao dos dados de login."""

from __future__ import annotations

import asyncio
import os
import unittest
from datetime import UTC, datetime, timedelta

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.main import create_app
from api.app.modules.auth import retention
from api.app.modules.auth.models import AuthSession, Permission, Role, SecurityEvent, User
from api.app.modules.auth.permissions import ADMIN_PERMISSION_CODES
from api.app.modules.auth.security import hash_password
from api.app.modules.auth.tokens import utcnow
from api.tests.test_proposals_integration import TEST_DATABASE_URL, _alembic_config, _integration_enabled

PASSWORD = "Senha forte proposta 123"
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class AuthRetentionTests(unittest.TestCase):
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
                await conn.execute(text("TRUNCATE TABLE security_events, auth_sessions, role_permissions, user_roles, users, roles RESTART IDENTITY CASCADE"))

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
        asyncio.run(self._seed())
        self.client = TestClient(create_app())

    async def _seed(self):
        async with get_engine().begin() as conn:
            await conn.execute(text("TRUNCATE TABLE security_events, auth_sessions, role_permissions, user_roles, users, roles RESTART IDENTITY CASCADE"))
        async with get_sessionmaker()() as session:
            permissions = (await session.execute(select(Permission).where(Permission.code.in_(ADMIN_PERMISSION_CODES)))).scalars().all()
            role = Role(code="admin", name="Administrador", active=True, system_role=True)
            role.permissions.extend(permissions)
            user = User(username="admin", display_name="Administrador", password_hash=hash_password(PASSWORD), active=True, is_superuser=True, password_changed_at=utcnow())
            user.roles.append(role)
            session.add(user)
            await session.commit()

    # ---- helpers ------------------------------------------------------------
    def _login(self):
        response = self.client.post("/api/v1/auth/login", json={"username": "admin", "password": PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _refresh(self, token):
        return self.client.post("/api/v1/auth/refresh", json={"refresh_token": token})

    @staticmethod
    def _run(coro_fn):
        async def runner():
            async with get_sessionmaker()() as session:
                return await coro_fn(session)

        return asyncio.run(runner())

    def _count_events(self, event_type):
        return self._run(lambda s: _scalar(s, select(func.count()).select_from(SecurityEvent).where(SecurityEvent.event_type == event_type)))

    # ---- reuso registrado uma vez ------------------------------------------
    def test_first_reuse_revokes_the_family_and_logs_one_event(self):
        first = self._login()
        second = self._refresh(first["refresh_token"]).json()
        self.assertEqual(self._count_events("TOKEN_REUSE_DETECTED"), 0)
        reused = self._refresh(first["refresh_token"])  # token ja rotacionado
        self.assertEqual(reused.status_code, 401, reused.text)
        self.assertEqual(reused.json()["error"]["code"], "REFRESH_TOKEN_REUSED")
        self.assertEqual(self._count_events("TOKEN_REUSE_DETECTED"), 1)
        # A familia inteira morreu: o token novo tambem deixa de valer.
        newest = self._refresh(second["refresh_token"])
        self.assertEqual(newest.status_code, 401)
        reasons = self._run(lambda s: _all(s, select(AuthSession.revoke_reason).order_by(AuthSession.id)))
        self.assertEqual(set(reasons), {"reuse_detected"})

    def test_repeating_the_same_dead_token_adds_no_events_and_no_writes(self):
        first = self._login()
        self._refresh(first["refresh_token"])
        self._refresh(first["refresh_token"])  # primeiro reuso: evento + revogacao
        before = self._run(lambda s: _all(s, select(AuthSession.id, AuthSession.revoked_at, AuthSession.revoke_reason).order_by(AuthSession.id)))
        events_before = self._count_events("TOKEN_REUSE_DETECTED")
        for _ in range(5):
            response = self._refresh(first["refresh_token"])
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["error"]["code"], "REFRESH_TOKEN_REUSED")
        self.assertEqual(self._count_events("TOKEN_REUSE_DETECTED"), events_before)
        self.assertEqual(self._run(lambda s: _all(s, select(AuthSession.id, AuthSession.revoked_at, AuthSession.revoke_reason).order_by(AuthSession.id))), before)

    def test_a_new_login_after_the_dead_token_starts_a_healthy_session(self):
        first = self._login()
        self._refresh(first["refresh_token"])
        self._refresh(first["refresh_token"])
        fresh = self._login()
        self.assertEqual(self._refresh(fresh["refresh_token"]).status_code, 200)

    def test_unknown_token_is_still_invalid_without_events(self):
        response = self._refresh("x" * 60)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self._count_events("TOKEN_REUSE_DETECTED"), 0)

    # ---- retencao -----------------------------------------------------------
    async def _plant(self, session):
        user_id = (await session.execute(select(User.id))).scalars().first()

        def auth(index, *, expires, revoked=None, reason=None):
            return AuthSession(user_id=user_id, refresh_token_hash=f"hash-{index}", token_family=f"fam-{index}", expires_at=expires, revoked_at=revoked, revoke_reason=reason)

        d = lambda days: NOW - timedelta(days=days)  # noqa: E731
        session.add_all([
            auth(1, expires=d(60), revoked=d(65), reason="rotated"),        # velha e expirada -> apaga
            auth(2, expires=d(40), revoked=None),                           # expirada sem revogar, ha 40 d -> apaga
            auth(3, expires=d(31), revoked=d(38), reason="reuse_detected"), # -> apaga
            auth(4, expires=d(20), revoked=d(25), reason="rotated"),        # expirada mas recente (<30 d) -> fica
            auth(5, expires=d(35), revoked=d(10), reason="logout_all"),     # revogada ha 10 d -> fica
            auth(6, expires=NOW + timedelta(days=5), revoked=None),         # ativa -> fica
            auth(7, expires=NOW + timedelta(days=5), revoked=d(40), reason="rotated"),  # revogada ha 40 d mas AINDA valida (nao expirou) -> fica
        ])
        for index, (event_type, days) in enumerate([
            ("TOKEN_REFRESHED", 45), ("TOKEN_REUSE_DETECTED", 31), ("TOKEN_REFRESHED", 29), ("TOKEN_REUSE_DETECTED", 1),
            ("LOGIN_SUCCESS", 400), ("LOGOUT", 400), ("PASSWORD_CHANGED", 400),
            ("PRODUCTION_ITEM_FLOW_UPDATED", 400), ("GALVANIZATION_ITEM_SENT", 400), ("EXPEDITION_ITEM_SEPARATED", 400),
        ]):
            session.add(SecurityEvent(event_type=event_type, actor_user_id=user_id, target_user_id=user_id, success=True, created_at=d(days)))
        await session.commit()

    async def _snapshot(self, session):
        sessions = sorted((await session.execute(select(AuthSession.refresh_token_hash))).scalars())
        events = sorted((await session.execute(select(SecurityEvent.event_type, func.count()).group_by(SecurityEvent.event_type))).all())
        return sessions, events

    def test_purge_only_removes_expired_sessions_and_old_token_noise(self):
        self._run(self._plant)
        result = asyncio.run(retention.purge_auth_data(session_days=30, token_event_days=30, now=NOW))
        self.assertEqual((result.sessions, result.token_events, result.dry_run), (3, 2, False))
        sessions, events = self._run(self._snapshot)
        self.assertEqual(sessions, ["hash-4", "hash-5", "hash-6", "hash-7"])
        remaining = dict(events)
        # Ruido recente fica; auditoria e acoes de negocio, de qualquer idade, ficam.
        self.assertEqual(remaining["TOKEN_REFRESHED"], 1)
        self.assertEqual(remaining["TOKEN_REUSE_DETECTED"], 1)
        for kept in ("LOGIN_SUCCESS", "LOGOUT", "PASSWORD_CHANGED", "PRODUCTION_ITEM_FLOW_UPDATED", "GALVANIZATION_ITEM_SENT", "EXPEDITION_ITEM_SEPARATED"):
            self.assertEqual(remaining[kept], 1, kept)

    def test_dry_run_counts_without_deleting(self):
        self._run(self._plant)
        before = self._run(self._snapshot)
        result = asyncio.run(retention.purge_auth_data(session_days=30, token_event_days=30, now=NOW, dry_run=True))
        self.assertEqual((result.sessions, result.token_events, result.dry_run), (3, 2, True))
        self.assertEqual(self._run(self._snapshot), before)

    def test_purge_is_idempotent_and_works_in_small_batches(self):
        self._run(self._plant)
        first = asyncio.run(retention.purge_auth_data(session_days=30, token_event_days=30, now=NOW, batch_size=1))
        self.assertEqual((first.sessions, first.token_events), (3, 2))
        second = asyncio.run(retention.purge_auth_data(session_days=30, token_event_days=30, now=NOW, batch_size=1))
        self.assertEqual((second.sessions, second.token_events), (0, 0))

    def test_longer_deadlines_remove_less(self):
        self._run(self._plant)
        result = asyncio.run(retention.purge_auth_data(session_days=60, token_event_days=40, now=NOW))
        self.assertEqual((result.sessions, result.token_events), (1, 1))  # so a sessao 1 e o evento de 45 dias

    def test_the_cli_command_only_counts_unless_told_to_apply(self):
        import argparse

        from api.app import cli

        self._run(self._plant)
        before = self._run(self._snapshot)
        # prazos longos: nada ultrapassa; --apply ausente: nada apagado de qualquer forma
        asyncio.run(cli.purge_auth_data_command(argparse.Namespace(apply=False, session_days=1, token_event_days=1)))
        self.assertEqual(self._run(self._snapshot), before)


async def _scalar(session, statement):
    return (await session.execute(statement)).scalar_one()


async def _all(session, statement):
    return [tuple(row) if len(row) > 1 else row[0] for row in (await session.execute(statement)).all()]


if __name__ == "__main__":
    unittest.main()
