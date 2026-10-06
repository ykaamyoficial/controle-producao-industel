"""Entidades replicadas para os Desktops e a permissao exigida para le-las.

Para replicar uma nova entidade basta registra-la aqui: a captura
(`capture.py`) e os endpoints passam a cobri-la. Mudar colunas de uma
entidade registrada ou esta lista exige subir `SYNC_SCHEMA_VERSION`, o que
faz cada Desktop descartar a replica e refazer a carga inicial.

Ficam fora de proposito: usuarios/perfis/sessoes, eventos de seguranca,
chat e anexos (permissao por linha e volume) e as tabelas `*_events`
(historico append-only, lido sob demanda pela API).
"""

from __future__ import annotations

from dataclasses import dataclass

from api.app.database.base import Base
from api.app.modules.auth.permissions import (
    EXPEDITION_VIEW,
    FISCAL_VIEW,
    GALVANIZATION_VIEW,
    PRODUCTION_VIEW,
    PROPOSALS_VIEW,
)
from api.app.modules.proposals.models import (
    ExpeditionItem,
    FiscalInvoice,
    FiscalInvoiceItem,
    FiscalItem,
    FiscalRecord,
    GalvanizationLoad,
    GalvanizationLoadItem,
    Proposal,
    ProposalItem,
)

SYNC_SCHEMA_VERSION = 1

_ANY_OPERATIONAL_VIEW = (PROPOSALS_VIEW, PRODUCTION_VIEW, GALVANIZATION_VIEW, EXPEDITION_VIEW, FISCAL_VIEW)


@dataclass(frozen=True)
class SyncEntity:
    name: str
    model: type[Base]
    # Basta UMA das permissoes (as telas operacionais leem proposta/itens).
    permissions: tuple[str, ...]


SYNC_ENTITIES: tuple[SyncEntity, ...] = (
    SyncEntity("proposals", Proposal, _ANY_OPERATIONAL_VIEW),
    SyncEntity("proposal_items", ProposalItem, _ANY_OPERATIONAL_VIEW),
    SyncEntity("galvanization_loads", GalvanizationLoad, (GALVANIZATION_VIEW,)),
    SyncEntity("galvanization_load_items", GalvanizationLoadItem, (GALVANIZATION_VIEW,)),
    SyncEntity("expedition_items", ExpeditionItem, (EXPEDITION_VIEW,)),
    SyncEntity("fiscal_records", FiscalRecord, (FISCAL_VIEW,)),
    SyncEntity("fiscal_items", FiscalItem, (FISCAL_VIEW,)),
    SyncEntity("fiscal_invoices", FiscalInvoice, (FISCAL_VIEW,)),
    SyncEntity("fiscal_invoice_items", FiscalInvoiceItem, (FISCAL_VIEW,)),
)

ENTITY_BY_NAME: dict[str, SyncEntity] = {entity.name: entity for entity in SYNC_ENTITIES}
ENTITY_BY_MODEL: dict[type[Base], SyncEntity] = {entity.model: entity for entity in SYNC_ENTITIES}
