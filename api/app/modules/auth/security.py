from __future__ import annotations

import hmac
import re

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

from api.app.core import error_codes
from api.app.core.config import get_settings
from api.app.core.exceptions import ApiError


_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16)
_weak_passwords = {"1234567890", "123456789", "password123", "senha12345", "administrador", "admin123456"}


def hash_password(password: str) -> str:
    validate_password_policy(password)
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bool(_hasher.verify(password_hash, password))
    except (VerifyMismatchError, VerificationError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def validate_password_policy(password: str) -> None:
    settings = get_settings()
    if len(password) < settings.password_min_length:
        raise ApiError(error_codes.PASSWORD_POLICY_VIOLATION, "A senha nao atende a politica minima.", status_code=400)
    if len(password) > settings.password_max_length:
        raise ApiError(error_codes.PASSWORD_POLICY_VIOLATION, "A senha excede o tamanho maximo permitido.", status_code=400)
    compact = re.sub(r"\s+", "", password).lower()
    if compact in _weak_passwords or len(set(compact)) <= 2:
        raise ApiError(error_codes.PASSWORD_POLICY_VIOLATION, "A senha nao atende a politica minima.", status_code=400)


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
