from __future__ import annotations

import asyncio
import os
import unittest
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.modules.nomus_integration.pipeline.nomus_api_importer import NomusApiOrderNotFoundError
from api.app.modules.nomus_integration.schemas import NomusSettingsOut
from api.app.modules.product_catalog import service as product_catalog_service
from api.app.modules.product_catalog.models import ProductCatalogEntry
from api.app.modules.proposal_import.pipeline.schemas import ImportedProposalData, ImportedProposalItem, StandardProposalImportResult


ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "api"
TEST_DATABASE_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL", "")


def _database_name(url: str) -> str:
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    return parsed.path.lstrip("/")


def _integration_enabled() -> bool:
    return bool(TEST_DATABASE_URL) and os.environ.get("APP_ENV") == "test" and "test" in _database_name(TEST_DATABASE_URL).lower()


def _alembic_config() -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    return config


@dataclass(frozen=True)
class _FakeItem:
    unit_weight: Decimal | None
    total_weight: Decimal | None
    quantity: Decimal | None


class NormalizeAndDeriveWeightTests(unittest.TestCase):
    """Testes puros, sem banco: normalizacao de codigo e calculo de peso unitario."""

    def test_strips_accidental_whitespace(self):
        self.assertEqual(product_catalog_service.normalize_product_code("  450.830  "), "450.830")

    def test_preserves_leading_zeros(self):
        self.assertEqual(product_catalog_service.normalize_product_code("00123"), "00123")

    def test_preserves_dots_and_hyphens(self):
        self.assertEqual(product_catalog_service.normalize_product_code("450-830.01"), "450-830.01")

    def test_empty_and_none_become_none(self):
        self.assertIsNone(product_catalog_service.normalize_product_code(""))
        self.assertIsNone(product_catalog_service.normalize_product_code("   "))
        self.assertIsNone(product_catalog_service.normalize_product_code(None))

    def test_never_casts_to_float(self):
        # "300.25" com cast para float perderia significado de codigo; deve permanecer string identica.
        self.assertEqual(product_catalog_service.normalize_product_code("300.25"), "300.25")
        self.assertIsInstance(product_catalog_service.normalize_product_code("300.25"), str)

    def test_derive_prefers_explicit_unit_weight(self):
        item = _FakeItem(unit_weight=Decimal("15.75"), total_weight=Decimal("999"), quantity=Decimal("2"))
        self.assertEqual(product_catalog_service._derive_unit_weight(item), Decimal("15.75"))

    def test_derive_treats_zero_as_unknown(self):
        item = _FakeItem(unit_weight=Decimal("0"), total_weight=Decimal("0"), quantity=Decimal("2"))
        self.assertIsNone(product_catalog_service._derive_unit_weight(item))

    def test_derive_falls_back_to_total_over_quantity(self):
        item = _FakeItem(unit_weight=None, total_weight=Decimal("31.50"), quantity=Decimal("2"))
        self.assertEqual(product_catalog_service._derive_unit_weight(item), Decimal("15.7500"))

    def test_derive_returns_none_without_quantity(self):
        item = _FakeItem(unit_weight=None, total_weight=Decimal("31.50"), quantity=None)
        self.assertIsNone(product_catalog_service._derive_unit_weight(item))

    def test_derive_returns_none_when_quantity_is_zero(self):
        item = _FakeItem(unit_weight=None, total_weight=Decimal("31.50"), quantity=Decimal("0"))
        self.assertIsNone(product_catalog_service._derive_unit_weight(item))

    def test_derive_returns_none_when_nothing_known(self):
        item = _FakeItem(unit_weight=None, total_weight=None, quantity=Decimal("2"))
        self.assertIsNone(product_catalog_service._derive_unit_weight(item))


def _fake_settings(*, enabled: bool) -> NomusSettingsOut:
    return NomusSettingsOut(
        enabled=enabled,
        base_url="https://fake.nomus.example",
        api_key_configured=enabled,
        masked_api_key="****" if enabled else None,
        last_tested_at=None,
        last_test_status=None,
        last_test_message=None,
    )


def _fake_result(*, proposal_number: str, items: list[ImportedProposalItem]) -> StandardProposalImportResult:
    return StandardProposalImportResult(
        proposal=ImportedProposalData(proposal_number=proposal_number),
        items=items,
        field_confidences={},
        overall_confidence=Decimal("1.0"),
    )


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class ProductCatalogResolverIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV"), "SECRET_KEY": os.environ.get("SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "product-catalog-resolver-secret-key-32-chars"
        get_settings.cache_clear()
        get_engine.cache_clear()
        command.downgrade(_alembic_config(), "base")
        command.upgrade(_alembic_config(), "head")

    @classmethod
    def tearDownClass(cls):
        command.upgrade(_alembic_config(), "head")
        asyncio.run(dispose_engine())
        for key, value in cls.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        get_engine.cache_clear()

    def setUp(self):
        asyncio.run(self._truncate())

    async def _truncate(self):
        from sqlalchemy import text

        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE product_catalog_entries RESTART IDENTITY CASCADE"))

    def test_cache_hit_never_calls_nomus(self):
        async def run():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                session.add(ProductCatalogEntry(product_code="450.830", net_unit_weight=Decimal("15.7500"), sync_status="SYNCED"))
                await session.commit()

            with patch.object(product_catalog_service, "resolve_via_nomus_proposal", new=AsyncMock(side_effect=AssertionError("nao deveria chamar Nomus"))):
                async with session_factory() as session:
                    resolved = await product_catalog_service.resolve_weights(session, proposal_number="CP00001", codes=["450.830"])

            self.assertEqual(resolved["450.830"].net_unit_weight, Decimal("15.7500"))
            self.assertEqual(resolved["450.830"].status, product_catalog_service.STATUS_SYNCED)
            self.assertEqual(resolved["450.830"].source, product_catalog_service.SOURCE_CACHE)

        asyncio.run(run())

    def test_disabled_integration_returns_empty_without_error(self):
        async def run():
            session_factory = get_sessionmaker()
            with patch.object(product_catalog_service.nomus_integration_service, "load_settings", new=AsyncMock(return_value=_fake_settings(enabled=False))):
                async with session_factory() as session:
                    resolved = await product_catalog_service.resolve_via_nomus_proposal(session, proposal_number="CP00002", codes=["450.830"])
            self.assertEqual(resolved, {})

        asyncio.run(run())

    def test_order_not_found_returns_empty_without_error(self):
        async def run():
            session_factory = get_sessionmaker()
            with patch.object(product_catalog_service.nomus_integration_service, "load_settings", new=AsyncMock(return_value=_fake_settings(enabled=True))), \
                 patch.object(product_catalog_service.nomus_integration_service, "get_decrypted_api_key", new=AsyncMock(return_value="fake-key")), \
                 patch.object(product_catalog_service, "NomusApiImporter") as mock_importer_cls:
                mock_importer_cls.return_value.fetch_proposal.side_effect = NomusApiOrderNotFoundError("nao encontrado")
                async with session_factory() as session:
                    resolved = await product_catalog_service.resolve_via_nomus_proposal(session, proposal_number="CP00003", codes=["450.830"])
            self.assertEqual(resolved, {})

        asyncio.run(run())

    def test_resolves_and_caches_weight_from_nomus_order(self):
        async def run():
            session_factory = get_sessionmaker()
            items = [
                ImportedProposalItem(item_number=1, product_code="450.830", description="Item A", quantity=Decimal("2"), unit_weight=Decimal("15.7500"), total_weight=Decimal("31.5000")),
                ImportedProposalItem(item_number=2, product_code="450.398", description="Item B", quantity=Decimal("3"), unit_weight=None, total_weight=None),
            ]
            with patch.object(product_catalog_service.nomus_integration_service, "load_settings", new=AsyncMock(return_value=_fake_settings(enabled=True))), \
                 patch.object(product_catalog_service.nomus_integration_service, "get_decrypted_api_key", new=AsyncMock(return_value="fake-key")), \
                 patch.object(product_catalog_service, "NomusApiImporter") as mock_importer_cls:
                mock_importer_cls.return_value.fetch_proposal.return_value = _fake_result(proposal_number="CP00004", items=items)
                async with session_factory() as session:
                    resolved = await product_catalog_service.resolve_via_nomus_proposal(
                        session, proposal_number="CP00004", codes=["450.830", "450.398", "300.25"]
                    )

            self.assertEqual(resolved["450.830"].net_unit_weight, Decimal("15.7500"))
            self.assertEqual(resolved["450.830"].status, product_catalog_service.STATUS_SYNCED)
            self.assertEqual(resolved["450.398"].status, product_catalog_service.STATUS_NO_WEIGHT)
            self.assertIsNone(resolved["450.398"].net_unit_weight)
            self.assertEqual(resolved["300.25"].status, product_catalog_service.STATUS_NOT_FOUND)
            self.assertIsNone(resolved["300.25"].net_unit_weight)

            # peso sincronizado deve ter sido persistido no catalogo local (aprendido do pedido)
            async with session_factory() as session:
                entry = (await session.execute(select(ProductCatalogEntry).where(ProductCatalogEntry.product_code == "450.830"))).scalar_one()
                self.assertEqual(entry.net_unit_weight, Decimal("15.7500"))
                self.assertEqual(entry.sync_status, "SYNCED")
                self.assertEqual(entry.source_proposal_number, "CP00004")
                # codigos sem peso (NO_WEIGHT/NOT_FOUND) nao poluem o catalogo com entrada negativa
                missing = (await session.execute(select(ProductCatalogEntry).where(ProductCatalogEntry.product_code.in_(["450.398", "300.25"])))).scalars().all()
                self.assertEqual(missing, [])

        asyncio.run(run())

    def test_never_calls_nomus_twice_for_repeated_codes_in_one_call(self):
        async def run():
            session_factory = get_sessionmaker()
            items = [ImportedProposalItem(item_number=1, product_code="450.830", description="Item A", quantity=Decimal("2"), unit_weight=Decimal("15.7500"), total_weight=Decimal("31.5000"))]
            with patch.object(product_catalog_service.nomus_integration_service, "load_settings", new=AsyncMock(return_value=_fake_settings(enabled=True))), \
                 patch.object(product_catalog_service.nomus_integration_service, "get_decrypted_api_key", new=AsyncMock(return_value="fake-key")), \
                 patch.object(product_catalog_service, "NomusApiImporter") as mock_importer_cls:
                mock_importer_cls.return_value.fetch_proposal.return_value = _fake_result(proposal_number="CP00005", items=items)
                async with session_factory() as session:
                    await product_catalog_service.resolve_via_nomus_proposal(
                        session, proposal_number="CP00005", codes=["450.830", "450.830", "450.830"]
                    )
                self.assertEqual(mock_importer_cls.return_value.fetch_proposal.call_count, 1)

        asyncio.run(run())
