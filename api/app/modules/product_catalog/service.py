from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import anyio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.database.session import get_sessionmaker
from api.app.modules.nomus_integration import service as nomus_integration_service
from api.app.modules.nomus_integration.pipeline.nomus_api_client import NomusApiClient, NomusApiClientError
from api.app.modules.nomus_integration.pipeline.nomus_api_importer import (
    NomusApiAmbiguousOrderError,
    NomusApiImportError,
    NomusApiImporter,
    NomusApiOrderNotFoundError,
)
from api.app.modules.product_catalog.models import ProductCatalogEntry

log = logging.getLogger("product_catalog")

STATUS_SYNCED = "SYNCED"
STATUS_NO_WEIGHT = "NO_WEIGHT"
STATUS_NOT_FOUND = "NOT_FOUND"
STATUS_PENDING = "PENDING"

SOURCE_CACHE = "CACHE"
SOURCE_NOMUS = "NOMUS"
SOURCE_NONE = "NONE"

_WEIGHT_QUANTIZE = Decimal("0.0001")


@dataclass(frozen=True)
class ResolvedWeight:
    product_code: str
    net_unit_weight: Decimal | None
    status: str
    source: str


def normalize_product_code(value: str | None) -> str | None:
    """Codigo de produto e sempre string de negocio: sem strip acidental perdido,
    sem cast para numero (perderia zeros a esquerda), sem remover pontuacao."""
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


async def resolve_weights(
    session: AsyncSession,
    *,
    proposal_number: str | None,
    codes: list[str | None],
) -> dict[str, ResolvedWeight]:
    """Resolver oficial de peso por codigo de produto para uma proposta.

    Ordem: cache local (product_catalog_entries) primeiro; para codigos sem
    cache, tenta resolver via o pedido/proposta Nomus (proposal_number) numa
    unica chamada, deduplicando codigos repetidos. Codigos que nao resolvem
    por nenhuma via ficam PENDING - nunca 0 kg.
    """
    normalized_codes = _dedupe([normalize_product_code(code) for code in codes])
    if not normalized_codes:
        return {}

    resolved: dict[str, ResolvedWeight] = {}
    cache_entries = await resolve_from_cache(session, normalized_codes)
    missing: list[str] = []
    for code in normalized_codes:
        entry = cache_entries.get(code)
        if entry is not None and entry.net_unit_weight is not None:
            resolved[code] = ResolvedWeight(code, entry.net_unit_weight, STATUS_SYNCED, SOURCE_CACHE)
        else:
            missing.append(code)

    if missing and proposal_number:
        nomus_resolved = await resolve_via_nomus_proposal(session, proposal_number=proposal_number, codes=missing)
        resolved.update(nomus_resolved)

    for code in normalized_codes:
        if code not in resolved:
            resolved[code] = ResolvedWeight(code, None, STATUS_PENDING, SOURCE_NONE)
    return resolved


async def resolve_from_cache(session: AsyncSession, codes: list[str]) -> dict[str, ProductCatalogEntry]:
    normalized = _dedupe([normalize_product_code(code) for code in codes])
    if not normalized:
        return {}
    result = await session.execute(select(ProductCatalogEntry).where(ProductCatalogEntry.product_code.in_(normalized)))
    return {entry.product_code: entry for entry in result.scalars().all()}


async def resolve_via_nomus_proposal(
    session: AsyncSession,
    *,
    proposal_number: str | None,
    codes: list[str | None],
) -> dict[str, ResolvedWeight]:
    normalized_codes = _dedupe([normalize_product_code(code) for code in codes])
    if not normalized_codes or not proposal_number:
        return {}

    try:
        settings_out = await nomus_integration_service.load_settings(session)
        if not settings_out.enabled:
            return {}
        api_key = await nomus_integration_service.get_decrypted_api_key(session)
        if not api_key:
            return {}
        client = NomusApiClient(base_url=settings_out.base_url, api_key=api_key)
        importer = NomusApiImporter(client)
        result = await anyio.to_thread.run_sync(importer.fetch_proposal, proposal_number)
    except (NomusApiOrderNotFoundError, NomusApiAmbiguousOrderError) as exc:
        log.info("Peso Nomus nao resolvido por pedido | proposta=%s | motivo=%s", proposal_number, exc)
        return {}
    except (NomusApiImportError, NomusApiClientError) as exc:
        log.warning("Falha ao resolver pesos via pedido Nomus | proposta=%s | erro=%s", proposal_number, exc)
        return {}
    except OSError:
        log.warning("Falha de rede ao resolver pesos via pedido Nomus | proposta=%s", proposal_number)
        return {}
    except Exception:
        # Peso e enriquecimento auxiliar. Resposta incompleta, timeout de uma
        # dependencia ou erro de parsing nunca deve impedir o fluxo oficial.
        log.exception("Falha inesperada ao enriquecer pesos via Nomus | proposta=%s", proposal_number)
        return {}

    items_by_code: dict[str, list] = {}
    for item in result.items:
        code = normalize_product_code(item.product_code)
        if code:
            items_by_code.setdefault(code, []).append(item)

    resolved: dict[str, ResolvedWeight] = {}
    now = datetime.now(timezone.utc)
    for code in normalized_codes:
        matches = items_by_code.get(code)
        if not matches:
            resolved[code] = ResolvedWeight(code, None, STATUS_NOT_FOUND, SOURCE_NOMUS)
            continue
        unit_weight = _derive_unit_weight(matches[0])
        if unit_weight is None:
            resolved[code] = ResolvedWeight(code, None, STATUS_NO_WEIGHT, SOURCE_NOMUS)
            continue
        resolved[code] = ResolvedWeight(code, unit_weight, STATUS_SYNCED, SOURCE_NOMUS)
        await _upsert_catalog_entry(
            code,
            net_unit_weight=unit_weight,
            description=getattr(matches[0], "description", None),
            unit_of_measure=getattr(matches[0], "unit", None),
            proposal_number=proposal_number,
            synced_at=now,
        )
    return resolved


def _derive_unit_weight(item) -> Decimal | None:
    unit_weight = getattr(item, "unit_weight", None)
    if unit_weight is not None and unit_weight > 0:
        return unit_weight.quantize(_WEIGHT_QUANTIZE)
    total_weight = getattr(item, "total_weight", None)
    quantity = getattr(item, "quantity", None)
    if total_weight is None or not quantity or quantity <= 0:
        return None
    try:
        derived = (total_weight / quantity).quantize(_WEIGHT_QUANTIZE)
        return derived if derived > 0 else None
    except (InvalidOperation, ZeroDivisionError):
        return None


async def _upsert_catalog_entry(
    product_code: str,
    *,
    net_unit_weight: Decimal,
    description: str | None,
    unit_of_measure: str | None,
    proposal_number: str,
    synced_at: datetime,
) -> None:
    """Grava o peso aprendido numa transacao propria, independente da sessao/
    transacao do chamador (secao 18: catalogo pode ser atualizado em transacao
    separada). Assim o cache fica disponivel mesmo se a operacao que originou
    a resolucao (ex.: preview de PDF, ou uma criacao de proposta que falhou
    por outro motivo) nunca commitar."""
    session_factory = get_sessionmaker()
    async with session_factory() as catalog_session:
        result = await catalog_session.execute(select(ProductCatalogEntry).where(ProductCatalogEntry.product_code == product_code))
        entry = result.scalar_one_or_none()
        if entry is None:
            entry = ProductCatalogEntry(product_code=product_code)
            catalog_session.add(entry)
        entry.net_unit_weight = net_unit_weight
        entry.description = description or entry.description
        entry.unit_of_measure = unit_of_measure or entry.unit_of_measure
        entry.source_proposal_number = proposal_number
        entry.sync_status = STATUS_SYNCED
        entry.last_synced_at = synced_at
        entry.last_error_code = None
        entry.last_error_at = None
        await catalog_session.commit()


def _dedupe(values: list[str | None]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        if value and value not in seen:
            seen[value] = None
    return list(seen.keys())
