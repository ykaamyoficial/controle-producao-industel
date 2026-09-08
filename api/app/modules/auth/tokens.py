from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

from api.app.core import error_codes
from api.app.core.config import get_settings
from api.app.core.exceptions import AuthenticationError


def utcnow() -> datetime:
    return datetime.now(UTC)


def create_access_token(user_id: int, session_id: int | None = None) -> tuple[str, datetime, str]:
    settings = get_settings()
    issued_at = utcnow()
    expires_at = issued_at + timedelta(minutes=settings.access_token_expire_minutes)
    jti = uuid.uuid4().hex
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "jti": jti,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "type": "access",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    if session_id is not None:
        payload["sid"] = str(session_id)
    token = jwt.encode(payload, settings.secret_key, algorithm="HS256")
    return token, expires_at, jti


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
    except ExpiredSignatureError as exc:
        raise AuthenticationError(error_codes.TOKEN_EXPIRED, "Token expirado.") from exc
    except InvalidTokenError as exc:
        raise AuthenticationError(error_codes.TOKEN_INVALID, "Token invalido.") from exc
    if payload.get("type") != "access" or not payload.get("sub"):
        raise AuthenticationError(error_codes.TOKEN_INVALID, "Token invalido.")
    return payload


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
