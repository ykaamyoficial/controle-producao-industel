from __future__ import annotations

import json
import unittest

from app.services.nomus_api_client import NomusApiClientError
from app.services.nomus_api_importer import NomusApiImporter
from app.services.nomus_batch_import import NomusBatchImportService, NomusBatchTargetState
from app.services.nomus_proposal_locator import NomusProposalLocator


class FakeNomusClient:
    def __init__(self, pages: dict[tuple[str, int], object], errors: dict[tuple[str, int], Exception] | None = None):
        self.pages = pages
        self.errors = errors or {}
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, endpoint, params=None):
        self.calls.append((endpoint, params))
        if endpoint.startswith("produtos/"):
            raise AssertionError("Batch import must not fetch product weights")
        page = int((params or {}).get("pagina") or 1)
        key = (endpoint, page)
        if key in self.errors:
            raise self.errors[key]
        return self.pages.get(key, {"propostas": []})


class NomusBatchImportTests(unittest.TestCase):
    def make_service(self, client: FakeNomusClient, *, neighbor_limit: int = 1, exists_checker=None) -> NomusBatchImportService:
        importer = NomusApiImporter(client, max_search_pages=10)
        locator = NomusProposalLocator(client, page_size=50, neighbor_limit=neighbor_limit, fallback_max_pages=10)
        return NomusBatchImportService(
            importer,
            locator=locator,
            exists_checker=exists_checker,
            endpoints=("propostas",),
        )

    def test_parser_accepts_newline_comma_semicolon_and_tab(self):
        service = self.make_service(FakeNomusClient({}))

        self.assertEqual(
            service.parse_targets("CP05250, CP05251\nCP05252;\tCP05253"),
            ["CP05250", "CP05251", "CP05252", "CP05253"],
        )

    def test_normalization_dedupes_equivalent_inputs_and_reports_duplicate(self):
        client = FakeNomusClient({
            ("propostas", 1): {"propostas": [_proposal("CP 05480")]},
            ("propostas", 5): {"propostas": [_proposal("CP 05250")]},
        })
        result = self.make_service(client).prepare_batch(["CP 05250", "CP05250", "5250"])

        self.assertEqual([target.state for target in result.targets], [
            NomusBatchTargetState.READY,
            NomusBatchTargetState.DUPLICATE_INPUT,
            NomusBatchTargetState.DUPLICATE_INPUT,
        ])
        self.assertEqual(result.targets[0].proposal_number, 5250)
        self.assertEqual(result.targets[1].duplicate_of, "CP05250")
        self.assertEqual(client.calls, [("propostas", {"pagina": 1}), ("propostas", {"pagina": 5})])

    def test_precheck_local_skips_nomus_for_existing_proposal(self):
        client = FakeNomusClient({
            ("propostas", 1): {"propostas": [_proposal("CP 05480")]},
            ("propostas", 4): {"propostas": [_proposal("CP 05301")]},
        })
        exists = lambda proposal: proposal == "CP05302"
        result = self.make_service(client, exists_checker=exists).prepare_batch(["CP05301", "CP05302"])

        self.assertEqual(result.by_identifier()["CP05301"].state, NomusBatchTargetState.READY)
        self.assertEqual(result.by_identifier()["CP05302"].state, NomusBatchTargetState.ALREADY_EXISTS)
        self.assertNotIn("CP05302", json.dumps([call for call in client.calls]))

    def test_reference_grouping_and_page_cache_share_nomus_pages(self):
        client = FakeNomusClient({
            ("propostas", 1): {"propostas": [_proposal("CP 05480"), _proposal("CP 05472")]},
            ("propostas", 2): {"propostas": [_proposal("CP 05425"), _proposal("CP 05410")]},
        })
        result = self.make_service(client).prepare_batch(["CP05480", "CP05472", "CP05425", "CP05410"])

        self.assertEqual(result.counts_by_state().get("READY"), 4)
        self.assertEqual(client.calls, [
            ("propostas", {"pagina": 1}),
            ("propostas", {"pagina": 2}),
        ])
        self.assertEqual(result.metrics.latest_reference_calls, 1)
        self.assertEqual(result.metrics.page_fetches, 2)
        self.assertGreaterEqual(result.metrics.page_cache_hits, 1)
        self.assertEqual(result.metrics.grouped_pages["propostas"], (1, 2))
        self.assertEqual(result.metrics.simulated_individual_page_requests, 4)

    def test_neighbor_lookup_is_shared_between_pending_targets(self):
        client = FakeNomusClient({
            ("propostas", 1): {"propostas": [_proposal("CP 05480")]},
            ("propostas", 5): {"propostas": []},
            ("propostas", 4): {"propostas": []},
            ("propostas", 6): {"propostas": [_proposal("CP 05250"), _proposal("CP 05248")]},
        })
        result = self.make_service(client).prepare_batch(["CP05250", "CP05248"])

        self.assertEqual(result.counts_by_state().get("READY"), 2)
        self.assertEqual(result.by_identifier()["CP05250"].matched_page, 6)
        self.assertEqual(result.by_identifier()["CP05248"].matched_page, 6)
        self.assertEqual(client.calls, [
            ("propostas", {"pagina": 1}),
            ("propostas", {"pagina": 5}),
            ("propostas", {"pagina": 4}),
            ("propostas", {"pagina": 6}),
        ])

    def test_not_found_and_page_error_are_isolated_per_target(self):
        error = NomusApiClientError("server_error", "Falha temporaria do Nomus")
        client = FakeNomusClient(
            {
                ("propostas", 1): {"propostas": [_proposal("CP 05480")]},
                ("propostas", 3): {"propostas": []},
                ("propostas", 4): {"propostas": []},
            },
            errors={("propostas", 2): error},
        )
        result = self.make_service(client, neighbor_limit=0).prepare_batch(["CP05480", "CP05425", "CP05350"])

        self.assertEqual(result.by_identifier()["CP05480"].state, NomusBatchTargetState.READY)
        self.assertEqual(result.by_identifier()["CP05425"].state, NomusBatchTargetState.ERROR)
        self.assertEqual(result.by_identifier()["CP05350"].state, NomusBatchTargetState.NOT_FOUND)

    def test_cancel_before_locating_marks_pending_without_fetching_nomus(self):
        client = FakeNomusClient({
            ("propostas", 1): {"propostas": [_proposal("CP 05480")]},
        })
        result = self.make_service(client).prepare_batch(["CP05480"], is_cancelled=lambda: True)

        self.assertEqual(result.targets[0].state, NomusBatchTargetState.CANCELLED)
        self.assertEqual(client.calls, [])

    def test_batch_preparation_does_not_fetch_products_and_keeps_financial_fields_out(self):
        payload = _proposal("CP 05480")
        payload["valorTotal"] = "99999.99"
        payload["itensProposta"][0]["idProduto"] = 17517
        payload["itensProposta"][0]["valorUnitario"] = "10.00"
        client = FakeNomusClient({("propostas", 1): {"propostas": [payload]}})

        result = self.make_service(client).prepare_batch(["CP05480"])
        prepared = result.by_identifier()["CP05480"].prepared_result

        self.assertIsNotNone(prepared)
        serialized = prepared.to_json().lower()
        self.assertNotIn("valorunitario", serialized)
        self.assertNotIn("valortotal", serialized)
        self.assertNotIn("99999.99", serialized)
        self.assertEqual(client.calls, [("propostas", {"pagina": 1})])


def _proposal(code: str) -> dict:
    return {
        "id": int("".join(ch for ch in code if ch.isdigit()) or "0"),
        "proposta": code,
        "dataHoraAbertura": "2026-06-19T10:00:00",
        "nomeCliente": "CLIENTE TESTE",
        "obraSite": "OBRA TESTE",
        "itensProposta": [
            {
                "item": "1",
                "codigoProduto": "132310001",
                "descricaoProduto": "VIGA OPERACIONAL",
                "nomeUnidadeMedida": "UNIDADE",
                "qtde": "2",
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
