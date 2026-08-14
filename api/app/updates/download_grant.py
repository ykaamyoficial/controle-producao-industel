"""Token de download curto e escopado (Fase 12, Secao 20).

Reutiliza a mesma infraestrutura de assinatura ja usada pelos access tokens
de sessao (api.app.modules.auth.tokens: PyJWT + settings.secret_key) em vez
de criar um segundo sistema de autenticacao -- mas com um `type` proprio
("update_download"), curto (UPDATE_DOWNLOAD_GRANT_EXPIRE_SECONDS), somente
leitura, vinculado a uma unica versao e sem qualquer permissao
administrativa. Um token de sessao normal (type=access) nunca e aceito aqui,
e um grant nunca e aceito no lugar de um access token (ver
api.app.modules.auth.tokens.decode_access_token, que exige type=="access").
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

from api.app.core.config import get_settings
from api.app.updates.exceptions import DownloadGrantInvalidError

_GRANT_TYPE = "update_download"


def mint_download_grant(version: str, *, channel: str = "PRODUCTION", expires_in_seconds: int | None = None) -> str:
    """`channel` (Fase 15, Secao 17): o canal resolvido para o cliente NO
    MOMENTO da descoberta -- o grant nunca e emitido para um canal maior do
    que o cliente realmente tem direito de ver. Default "PRODUCTION" para
    nao quebrar nenhum chamador anterior a Fase 15."""
    settings = get_settings()
    ttl = expires_in_seconds if expires_in_seconds is not None else settings.update_download_grant_expire_seconds
    issued_at = datetime.now(UTC)
    payload: dict[str, Any] = {
        "type": _GRANT_TYPE,
        "version": version,
        "channel": channel,
        "jti": uuid.uuid4().hex,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + timedelta(seconds=ttl)).timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def verify_download_grant(token: str, *, expected_version: str) -> dict[str, Any]:
    """Devolve o payload validado (Fase 15: quem chama pode ler `channel`
    para revalidar elegibilidade contra o estado ATUAL da promocao -- o
    grant nunca e a unica fonte de verdade, so evita reautenticar a cada
    download, ver api.app.updates.router.require_release_access)."""
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
        raise DownloadGrantInvalidError("Token de download expirado.") from exc
    except InvalidTokenError as exc:
        raise DownloadGrantInvalidError("Token de download invalido.") from exc

    if payload.get("type") != _GRANT_TYPE:
        raise DownloadGrantInvalidError("Token nao e um grant de download valido.")
    if payload.get("version") != expected_version:
        raise DownloadGrantInvalidError("Token de download nao corresponde a esta versao.")
    return payload
