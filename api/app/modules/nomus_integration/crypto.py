from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from api.app.core import error_codes
from api.app.core.exceptions import ApiError


def _fernet(encryption_key: str) -> Fernet:
    derived = hashlib.sha256(encryption_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_secret(value: str, *, encryption_key: str) -> str:
    return _fernet(encryption_key).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str, *, encryption_key: str) -> str:
    try:
        return _fernet(encryption_key).decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ApiError(
            error_codes.CONFIGURATION_ERROR,
            "Nao foi possivel decifrar a chave da API do Nomus (NOMUS_ENCRYPTION_KEY pode ter mudado).",
            status_code=503,
        ) from exc
