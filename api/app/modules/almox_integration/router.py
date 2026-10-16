"""Conciliação: o Almox+ pergunta à produção o estado das propostas (corrige webhook perdido).

Autenticada por assinatura HMAC com o segredo compartilhado (``ALMOX_INTEGRATION_SECRET``), não
por usuário: quem chama é o outro sistema. Sem segredo configurado o endpoint fica desligado.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core import error_codes
from api.app.core.config import get_settings
from api.app.core.exceptions import ApiError, AuthenticationError
from api.app.database.session import get_db_session
from api.app.modules.almox_integration.repository import listar_estados
from api.app.modules.almox_integration.signing import verify

router = APIRouter(prefix="/integrations/almox", tags=["almox-integration"])

MAX_NUMEROS = 200


def _segredo() -> str:
    return get_settings().almox_integration_secret


async def verificar_assinatura(request: Request) -> None:
    segredo = _segredo()
    if not segredo:
        raise ApiError(
            error_codes.CONFIGURATION_ERROR,
            "A integracao com o Almox+ nao esta ativada.",
            status_code=503,
        )
    assinado = verify(
        segredo,
        request.headers.get("X-Timestamp", ""),
        request.headers.get("X-Signature", ""),
        request.url.query.encode(),
    )
    if not assinado:
        raise AuthenticationError(error_codes.TOKEN_INVALID, "Assinatura invalida.")


@router.get("/proposals", dependencies=[Depends(verificar_assinatura)])
async def estados_das_propostas(
    estado: Literal["LIBERADA", "RETIRADA", "CONCLUIDA"] | None = Query(default=None),
    numero: list[str] = Query(default_factory=list),
    session: AsyncSession = Depends(get_db_session),
):
    """Propostas em um ``estado``, ou o estado de cada ``numero`` pedido (``DESCONHECIDA`` /
    ``NAO_LIBERADA`` quando não há estado)."""
    if estado is None and not numero:
        raise ApiError(
            error_codes.VALIDATION_ERROR, "Informe o estado ou ao menos um numero.", status_code=422
        )
    if len(numero) > MAX_NUMEROS:
        raise ApiError(
            error_codes.VALIDATION_ERROR,
            f"No maximo {MAX_NUMEROS} numeros por consulta.",
            status_code=422,
        )
    return {
        "gerado_em": datetime.now(UTC).isoformat(),
        "items": await listar_estados(session, estado=estado, numeros=numero),
    }
