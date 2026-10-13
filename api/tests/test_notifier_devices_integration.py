from __future__ import annotations

import asyncio
import os
import unittest
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from api.app.core.config import get_settings
from api.app.core.exceptions import AuthenticationError
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.modules.auth import repository
from api.app.modules.auth.models import Permission, Role, User
from api.app.modules.auth.permissions import ADMIN_PERMISSION_CODES
from api.app.modules.auth.security import hash_password
from api.app.modules.auth.tokens import create_access_token, decode_access_token, utcnow
from api.app.modules.notifications import device_service
from api.app.modules.notifications import service as notifications_service
from api.app.modules.notifications.models import NotificationDevice
from api.app.modules.notifications.schemas import NotifierDeviceRegisterPayload


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


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class NotifierDeviceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {key: os.environ.get(key) for key in ("DATABASE_URL", "APP_ENV", "SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "notifier-device-secret-key-more-than-32-chars"
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
        asyncio.run(self._truncate())

    async def _truncate(self):
        async with get_engine().begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE TABLE notification_devices, notification_deliveries, notification_preferences, "
                    "notification_user_settings, notifications, auth_sessions, "
                    "role_permissions, user_roles, users, roles RESTART IDENTITY CASCADE"
                )
            )

    async def _make_user(self, session, username: str) -> User:
        role = (await session.execute(select(Role).where(Role.code == "admin"))).scalars().first()
        if role is None:
            perms = (await session.execute(select(Permission).where(Permission.code.in_(ADMIN_PERMISSION_CODES)))).scalars().all()
            role = Role(code="admin", name="Administrador", active=True, system_role=True)
            role.permissions.extend(perms)
            session.add(role)
            await session.flush()
        user = User(
            username=username,
            display_name=username.title(),
            password_hash=hash_password("Senha forte notif 123"),
            active=True,
            password_changed_at=utcnow(),
        )
        user.roles.append(role)
        session.add(user)
        await session.flush()
        return user

    def _register(self, user, installation_id="inst-0001-aaaa", os_user="heriq"):
        return NotifierDeviceRegisterPayload(installation_id=installation_id, os_user=os_user, device_name="PC-01")

    def test_register_exchange_and_token_is_not_a_normal_access_token(self):
        async def _run():
            async with get_sessionmaker()() as session:
                user = await self._make_user(session, "joao")
                await session.commit()
                registered = await device_service.register_device(session, user, self._register(user))
                self.assertEqual(registered.user.username, "joao")

                token = await device_service.exchange_token(session, registered.device_token)
                self.assertEqual(token.user.id, user.id)
                # o token do agente nunca vale como access token comum
                with self.assertRaises(AuthenticationError):
                    decode_access_token(token.access_token)
                # e um access token comum nao vale como token do agente
                normal, _exp, _jti = create_access_token(user.id)
                with self.assertRaises(AuthenticationError):
                    await device_service.authenticate_notifier(session, normal)

                authed, _exp = await device_service.authenticate_notifier(session, token.access_token)
                self.assertEqual(authed.id, user.id)

        asyncio.run(_run())

    def test_exchange_does_not_rotate_so_two_processes_never_race(self):
        async def _run():
            async with get_sessionmaker()() as session:
                user = await self._make_user(session, "joao")
                await session.commit()
                registered = await device_service.register_device(session, user, self._register(user))
                first = await device_service.exchange_token(session, registered.device_token)
                second = await device_service.exchange_token(session, registered.device_token)
                self.assertEqual(first.user.id, second.user.id)
                rows = (await session.execute(select(NotificationDevice))).scalars().all()
                self.assertEqual(len(rows), 1)
                self.assertIsNone(rows[0].revoked_at)

        asyncio.run(_run())

    def test_last_login_wins_on_same_installation_and_windows_user(self):
        async def _run():
            async with get_sessionmaker()() as session:
                joao = await self._make_user(session, "joao")
                maria = await self._make_user(session, "maria")
                await session.commit()
                old = await device_service.register_device(session, joao, self._register(joao))
                old_access = (await device_service.exchange_token(session, old.device_token)).access_token

                new = await device_service.register_device(session, maria, self._register(maria))
                self.assertEqual(new.user.username, "maria")

                with self.assertRaises(AuthenticationError):
                    await device_service.exchange_token(session, old.device_token)
                # o token curto ja emitido tambem cai na hora, sem esperar vencer
                with self.assertRaises(AuthenticationError):
                    await device_service.authenticate_notifier(session, old_access)
                ok = await device_service.exchange_token(session, new.device_token)
                self.assertEqual(ok.user.username, "maria")

        asyncio.run(_run())

    def test_other_windows_user_or_other_machine_is_not_replaced(self):
        async def _run():
            async with get_sessionmaker()() as session:
                joao = await self._make_user(session, "joao")
                maria = await self._make_user(session, "maria")
                await session.commit()
                a = await device_service.register_device(session, joao, self._register(joao, os_user="heriq"))
                await device_service.register_device(session, maria, self._register(maria, os_user="outro"))
                await device_service.register_device(session, maria, self._register(maria, installation_id="inst-0002-bbbb"))
                still = await device_service.exchange_token(session, a.device_token)
                self.assertEqual(still.user.username, "joao")

        asyncio.run(_run())

    def test_deactivating_user_or_logout_all_revokes_device(self):
        async def _run():
            async with get_sessionmaker()() as session:
                user = await self._make_user(session, "joao")
                await session.commit()
                registered = await device_service.register_device(session, user, self._register(user))
                await repository.revoke_user_sessions(session, user.id, "user_deactivated")
                await session.commit()
                with self.assertRaises(AuthenticationError):
                    await device_service.exchange_token(session, registered.device_token)

        asyncio.run(_run())

    def test_expired_and_unknown_credentials_are_refused(self):
        async def _run():
            async with get_sessionmaker()() as session:
                user = await self._make_user(session, "joao")
                await session.commit()
                registered = await device_service.register_device(session, user, self._register(user))
                device = (await session.execute(select(NotificationDevice))).scalars().one()
                device.expires_at = utcnow() - timedelta(seconds=1)
                await session.commit()
                with self.assertRaises(AuthenticationError):
                    await device_service.exchange_token(session, registered.device_token)
                with self.assertRaises(AuthenticationError):
                    await device_service.exchange_token(session, "token-que-nao-existe-de-jeito-nenhum")

        asyncio.run(_run())

    def test_exchange_slides_the_expiry_window(self):
        async def _run():
            async with get_sessionmaker()() as session:
                user = await self._make_user(session, "joao")
                await session.commit()
                registered = await device_service.register_device(session, user, self._register(user))
                device = (await session.execute(select(NotificationDevice))).scalars().one()
                device.expires_at = utcnow() + timedelta(days=2)
                await session.commit()
                await device_service.exchange_token(session, registered.device_token)
                await session.refresh(device)
                self.assertGreater(device.expires_at, utcnow() + timedelta(days=80))

        asyncio.run(_run())

    def test_catch_up_for_tray_skips_suppressed_deliveries(self):
        async def _run():
            async with get_sessionmaker()() as session:
                actor = await self._make_user(session, "actor")
                user = await self._make_user(session, "joao")
                await session.commit()
                await notifications_service.emit(
                    session, user_ids=[user.id], category="PROPOSTA_STATUS", title="visivel", dedup_key="k:1", actor_user_id=actor.id
                )
                await notifications_service.emit(
                    session, user_ids=[user.id], category="PROPOSTA_STATUS", title="silenciada", dedup_key="k:2", actor_user_id=actor.id
                )
                await session.commit()
                await session.execute(
                    text(
                        "UPDATE notification_deliveries SET status='suprimido_preferencia' "
                        "WHERE channel='tray' AND notification_id = (SELECT id FROM notifications WHERE title='silenciada')"
                    )
                )
                await session.commit()
                tray = await notifications_service.catch_up(session, user, since_id=0, channel="tray")
                self.assertEqual([item.title for item in tray.items], ["visivel"])
                everything = await notifications_service.catch_up(session, user, since_id=0)
                self.assertEqual(len(everything.items), 2)
                summary = await notifications_service.unread_summary(session, user)
                self.assertEqual(summary.latest_id, everything.items[-1].id)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
