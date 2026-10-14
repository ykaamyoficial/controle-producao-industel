"""Selos de remanejamento das listas (Fase D do plano de logistica): so a regra, sem banco.

Uma proposta ganha selo enquanto algum item dela esta "fora do lugar" por causa de um
remanejamento; quando todas as pecas voltam a estar prontas ou entregues ela fica inteira de novo
e o selo some sozinho (decisao do Henrique).

* **Cedeu** (`SUBSTITUIDA` / `PARCIALMENTE_SUBSTITUIDA`): o item entregou pecas prontas a outra
  proposta e ainda espera as pecas que recebeu em troca (a fabricar, aguardando galvanizacao,
  na galvanizacao). Se a proposta ficou sem nenhuma peca pronta na Expedicao ela esta
  "Substituida"; se ainda tem prontas, "Parcialmente substituida".
* **Recebeu** (`RECEBEU`): o item recebeu pecas prontas de outra proposta e ainda tem pecas em
  andamento proprias (e a proposta nao cedeu nada em aberto).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from api.app.modules.proposals.stage_ledger import TOLERANCE, ZERO, ItemStages

SUBSTITUTED = "SUBSTITUIDA"
PARTIALLY_SUBSTITUTED = "PARCIALMENTE_SUBSTITUIDA"
RECEIVED = "RECEBEU"

DIRECTION_GAVE = "CEDEU"
DIRECTION_RECEIVED = "RECEBEU"


def in_flight(stages: ItemStages) -> Decimal:
    """Pecas do item que ainda nao estao prontas nem entregues."""
    return stages.to_produce + stages.awaiting_galvanization + stages.in_galvanization + stages.undefined_flow


def item_gave_open(stages: ItemStages) -> bool:
    """O item cedeu pecas prontas e ainda nao esta inteiro (falta chegar o que recebeu em troca)."""
    return stages.given_away > TOLERANCE and in_flight(stages) > TOLERANCE


def item_received_open(stages: ItemStages) -> bool:
    """O item recebeu pecas prontas e ainda tem pecas em andamento."""
    return stages.received_ready > TOLERANCE and in_flight(stages) > TOLERANCE


def proposal_badge_status(items: Iterable[ItemStages]) -> str | None:
    """Selo da proposta a partir dos estagios de TODOS os itens ativos dela (None = proposta inteira)."""
    items = list(items)
    if any(item_gave_open(item) for item in items):
        ready = sum((item.ready for item in items), ZERO)
        return SUBSTITUTED if ready <= TOLERANCE else PARTIALLY_SUBSTITUTED
    if any(item_received_open(item) for item in items):
        return RECEIVED
    return None
