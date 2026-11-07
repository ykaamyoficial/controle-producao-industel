"""Base dos testes de integracao do Almoxarifado (entrada por numero, baixa, itens).

Cria propostas pela API e ajusta direto no banco o que a API de entrada ainda nao faz
(status do Almoxarifado, baixa, mae/filha, cancelamento), para cada teste montar o cenario
exato que quer.
"""

from __future__ import annotations

import asyncio
import os
import unittest

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update

from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.main import create_app
from api.app.modules.auth.models import Permission, Role, User
from api.app.modules.auth.permissions import ADMIN_PERMISSION_CODES
from api.app.modules.auth.security import hash_password
from api.app.modules.auth.tokens import utcnow
from api.app.modules.proposals.models import Proposal
from api.tests.test_expedition_fiscal_read_path import TRUNCATE
from api.tests.test_proposals_integration import (
    TEST_DATABASE_URL,
    _alembic_config,
    _integration_enabled,
    _item_payload,
    _proposal_payload,
)

__all__ = ["WarehouseApiTestCase", "_integration_enabled", "_item_payload"]


class WarehouseApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {key: os.environ.get(key) for key in ("DATABASE_URL", "APP_ENV", "SECRET_KEY")}
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
        self.headers = self._login("admin")

    async def _seed_admin(self):
        async with get_engine().begin() as conn:
            await conn.execute(text(TRUNCATE))
        async with get_sessionmaker()() as session:
            permissions = (await session.execute(select(Permission).where(Permission.code.in_(ADMIN_PERMISSION_CODES)))).scalars().all()
            role = Role(code="admin", name="Administrador", active=True, system_role=True)
            role.permissions.extend(permissions)
            user = User(username="admin", display_name="Administrador", password_hash=hash_password("Senha forte proposta 123"), active=True, is_superuser=True, password_changed_at=utcnow())
            user.roles.append(role)
            session.add(user)
            await session.commit()

    def _login(self, username, password="Senha forte proposta 123"):
        login = self.client.post("/api/v1/auth/login", json={"username": username, "password": password})
        self.assertEqual(login.status_code, 200, login.text)
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    def _seed_user(self, username, permission_codes):
        """Usuario comum (nao superusuario) com so as permissoes dadas."""

        async def go():
            async with get_sessionmaker()() as session:
                permissions = (await session.execute(select(Permission).where(Permission.code.in_(permission_codes)))).scalars().all()
                role = Role(code=f"role-{username}", name=username, active=True, system_role=False)
                role.permissions.extend(permissions)
                user = User(username=username, display_name=username, password_hash=hash_password("Senha forte proposta 123"), active=True, is_superuser=False, password_changed_at=utcnow())
                user.roles.append(role)
                session.add(user)
                await session.commit()

        asyncio.run(go())
        return self._login(username)

    # ---- cenario ------------------------------------------------------------
    def _request(self, method, url, headers=None, **kwargs):
        return self.client.request(method, url, headers=headers or self.headers, **kwargs)

    def _make(self, number, *, items=1, **fields) -> int:
        """Cria a proposta pela API e grava `fields` direto na linha (status, baixa, mae, ...)."""
        payload = _proposal_payload(number, [_item_payload(str(i + 1)) for i in range(items)])
        response = self.client.post("/api/v1/proposals", json=payload, headers=self.headers)
        self.assertLess(response.status_code, 300, response.text)
        proposal_id = int(response.json()["id"])
        if fields:
            self._set(proposal_id, **fields)
        return proposal_id

    def _set(self, proposal_id, **fields):
        async def go():
            async with get_sessionmaker()() as session:
                await session.execute(update(Proposal).where(Proposal.id == proposal_id).values(**fields))
                await session.commit()

        asyncio.run(go())

    def _row(self, proposal_id) -> Proposal:
        async def go():
            async with get_sessionmaker()() as session:
                row = (await session.execute(select(Proposal).where(Proposal.id == proposal_id))).scalar_one()
                session.expunge_all()
                return row

        return asyncio.run(go())

    def _warehouse_list(self, **params):
        response = self.client.get("/api/v1/warehouse/proposals", params={"limit": 200, **params}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def _warehouse_numbers(self, **params):
        return {row["proposal_number"] for row in self._warehouse_list(**params)["items"]}
