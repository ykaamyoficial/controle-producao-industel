from __future__ import annotations

import os
import time
import unittest

from api.app.core import error_codes
from api.app.core.config import get_settings
from api.app.core.exceptions import ApiError, AuthenticationError
from api.app.modules.auth.models import Permission, Role, User
from api.app.modules.auth.security import hash_password, password_needs_rehash, validate_password_policy, verify_password
from api.app.modules.auth.service import effective_permissions, is_locked, public_user
from api.app.modules.users.schemas import UserCreate, UserUpdate
from api.app.modules.auth.tokens import create_access_token, decode_access_token, generate_refresh_token, hash_refresh_token, utcnow


class AuthSecurityUnitTests(unittest.TestCase):
    def setUp(self):
        self.previous = {
            "SECRET_KEY": os.environ.get("SECRET_KEY"),
            "ACCESS_TOKEN_EXPIRE_MINUTES": os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES"),
            "PASSWORD_MIN_LENGTH": os.environ.get("PASSWORD_MIN_LENGTH"),
        }
        os.environ["SECRET_KEY"] = "unit-tests-secret-key-with-more-than-32-chars"
        os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "15"
        os.environ["PASSWORD_MIN_LENGTH"] = "10"
        get_settings.cache_clear()

    def tearDown(self):
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()

    def test_password_hash_uses_argon2_and_verifies(self):
        password_hash = hash_password("uma senha longa segura")
        self.assertTrue(password_hash.startswith("$argon2"))
        self.assertTrue(verify_password("uma senha longa segura", password_hash))
        self.assertFalse(verify_password("senha errada", password_hash))
        self.assertFalse(password_needs_rehash(password_hash))

    def test_password_policy_rejects_weak_passwords(self):
        with self.assertRaises(ApiError) as raised:
            validate_password_policy("1234567890")
        self.assertEqual(raised.exception.code, error_codes.PASSWORD_POLICY_VIOLATION)

    def test_access_token_claims_and_decode(self):
        token, expires_at, jti = create_access_token(10, session_id=55)
        payload = decode_access_token(token)
        self.assertEqual(payload["sub"], "10")
        self.assertEqual(payload["sid"], "55")
        self.assertEqual(payload["type"], "access")
        self.assertEqual(payload["jti"], jti)
        self.assertGreater(expires_at, utcnow())

    def test_expired_access_token_is_rejected(self):
        os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "1"
        get_settings.cache_clear()
        token, _expires_at, _jti = create_access_token(1)
        payload = decode_access_token(token)
        payload["exp"] = int(time.time()) - 1
        import jwt

        settings = get_settings()
        expired = jwt.encode(payload, settings.secret_key, algorithm="HS256")
        with self.assertRaises(AuthenticationError) as raised:
            decode_access_token(expired)
        self.assertEqual(raised.exception.code, error_codes.TOKEN_EXPIRED)

    def test_refresh_token_is_random_and_hashed(self):
        first = generate_refresh_token()
        second = generate_refresh_token()
        self.assertNotEqual(first, second)
        self.assertNotIn(first, hash_refresh_token(first))
        self.assertEqual(hash_refresh_token(first), hash_refresh_token(first))

    def test_effective_permissions_ignore_inactive_roles_and_permissions(self):
        allowed = Permission(id=1, code="users.view", name="Ver usuarios", module="users", active=True)
        inactive = Permission(id=2, code="audit.view", name="Auditoria", module="audit", active=False)
        role = Role(id=1, code="operator", name="Operador", active=True, system_role=False)
        role.permissions = [allowed, inactive]
        inactive_role = Role(id=2, code="inactive", name="Inativo", active=False, system_role=False)
        inactive_role.permissions = [Permission(id=3, code="system.admin", name="Admin", module="system", active=True)]
        user = User(id=1, username="teste", display_name="Teste", password_hash="x", active=True, is_superuser=False)
        user.roles = [role, inactive_role]
        self.assertEqual(effective_permissions(user), {"users.view"})

    def test_user_schemas_accept_desktop_permission_codes(self):
        create = UserCreate(
            username="operador",
            display_name="Operador Geral",
            password="Senha forte 123",
            permission_codes=["proposals.view", "production.update"],
        )
        update = UserUpdate(username="operador2", permission_codes=["galvanization.view"], is_superuser=False)

        self.assertEqual(create.permission_codes, ["proposals.view", "production.update"])
        self.assertEqual(update.username, "operador2")
        self.assertEqual(update.permission_codes, ["galvanization.view"])

    def test_locked_account_detection(self):
        user = User(id=1, username="teste", display_name="Teste", password_hash="x", active=True, is_superuser=False)
        user.roles = []
        user.locked_until = utcnow()
        self.assertFalse(is_locked(user))


if __name__ == "__main__":
    unittest.main()
