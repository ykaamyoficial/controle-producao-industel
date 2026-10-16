"""Consulta do estado das propostas para a conciliação do Almox+."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.modules.almox_integration.state import ESTADOS, LIBERADA, RETIRADA, almox_state
from api.app.modules.proposals.domain import INITIAL_STATUS
from api.app.modules.proposals.models import Proposal

LIMITE_RESULTADOS = 5000
#: Resposta para um número pedido que a produção não conhece, ou que ainda não foi liberado.
NAO_LIBERADA = "NAO_LIBERADA"
DESCONHECIDA = "DESCONHECIDA"


def _item(proposal: Proposal, estado: str) -> dict[str, Any]:
    return {
        "numero_proposta_nomus": proposal.proposal_number,
        "estado": estado,
        "atualizado_em": proposal.updated_at.isoformat() if proposal.updated_at else None,
    }


async def listar_estados(
    session: AsyncSession, *, estado: str | None, numeros: list[str]
) -> list[dict[str, Any]]:
    """Estado das propostas pedidas por número ou, sem números, de todas num ``estado``."""
    if numeros:
        return await _por_numeros(session, numeros)
    assert estado in ESTADOS
    consulta = select(Proposal).where(Proposal.active.is_(True), Proposal.is_partial.is_(False))
    if estado == RETIRADA:
        consulta = consulta.where(Proposal.is_cancelled.is_(True))
    elif estado == LIBERADA:
        consulta = consulta.where(
            Proposal.is_cancelled.is_(False),
            Proposal.is_completed.is_(False),
            Proposal.current_status.is_not(None),
            Proposal.current_status != INITIAL_STATUS,
        )
    else:
        consulta = consulta.where(Proposal.is_cancelled.is_(False))
    consulta = consulta.order_by(Proposal.updated_at.desc()).limit(LIMITE_RESULTADOS)
    propostas = (await session.scalars(consulta)).all()
    return [_item(p, estado) for p in propostas if almox_state(p) == estado]


async def _por_numeros(session: AsyncSession, numeros: list[str]) -> list[dict[str, Any]]:
    pedidos = {numero.strip().lower(): numero for numero in numeros if numero.strip()}
    consulta = select(Proposal).where(
        Proposal.active.is_(True),
        Proposal.is_partial.is_(False),
        func.lower(Proposal.proposal_number).in_(list(pedidos)),
    )
    encontradas = {
        p.proposal_number.strip().lower(): p for p in (await session.scalars(consulta)).all()
    }
    itens: list[dict[str, Any]] = []
    for chave, pedido in pedidos.items():
        proposta = encontradas.get(chave)
        if proposta is None:
            itens.append(
                {"numero_proposta_nomus": pedido, "estado": DESCONHECIDA, "atualizado_em": None}
            )
        else:
            itens.append(_item(proposta, almox_state(proposta) or NAO_LIBERADA))
    return itens
