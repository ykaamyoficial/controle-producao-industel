from __future__ import annotations

import unittest

from app.services.nomus_api_client import NomusApiClientError
from app.services.nomus_proposal_locator import NomusProposalLocator, normalize_requested_identifier


class FakeNomusClient:
    def __init__(self, pages: dict[tuple[str, int], object], errors: dict[tuple[str, int], Exception] | None = None):
        self.pages = pages
        self.errors = errors or {}
        self.calls: list[tuple[str, dict[str, int] | None]] = []

    def get(self, endpoint, params=None):
        self.calls.append((endpoint, params))
        page = int((params or {}).get("pagina", 1))
        key = (endpoint, page)
        if key in self.errors:
            raise self.errors[key]
        return self.pages.get(key, {"propostas": []})


class NomusProposalLocatorTests(unittest.TestCase):
    def test_normalizes_prefixed_and_numeric_identifiers_to_same_number(self):
        self.assertEqual(normalize_requested_identifier("CP 05250").number, "5250")
        self.assertEqual(normalize_requested_identifier("CP05250").number, "5250")
        self.assertEqual(normalize_requested_identifier("5250").number, "5250")
        self.assertEqual(normalize_requested_identifier("CP 05250").safe_log, "CP05250")

    def test_estimates_page_from_latest_reference_and_page_size(self):
        locator = NomusProposalLocator(FakeNomusClient({}), page_size=50)

        self.assertEqual(locator.estimate_page(5250, 5480), 5)
        self.assertEqual(locator.estimate_page(5480, 5480), 1)
        self.assertEqual(locator.estimate_page(5500, 5480), 1)

    def test_finds_on_estimated_page_without_scanning_from_page_one(self):
        client = FakeNomusClient(
            {
                ("propostas", 1): {"propostas": [{"proposta": "CP 05480"}]},
                ("propostas", 5): {"propostas": [{"proposta": "CP 05250"}]},
            }
        )
        locator = NomusProposalLocator(client, page_size=50, neighbor_limit=2)

        result = locator.locate_proposal("CP05250", "propostas")

        self.assertTrue(result.found)
        self.assertEqual(result.estimated_page, 5)
        self.assertEqual(result.matched_page, 5)
        self.assertEqual(client.calls, [("propostas", {"pagina": 1}), ("propostas", {"pagina": 5})])

    def test_latest_reference_ignores_external_id_and_internal_raw_id(self):
        client = FakeNomusClient(
            {
                ("propostas", 1): {
                    "propostas": [
                        {"proposta": "CP 04934", "idExterno": "ETCP 05252", "id": 99999},
                    ]
                }
            }
        )
        locator = NomusProposalLocator(client, page_size=50, neighbor_limit=1)

        result = locator.locate_proposal("CP04934", "propostas")

        self.assertTrue(result.found)
        self.assertEqual(result.estimated_page, 1)
        self.assertEqual(result.matched_page, 1)
        self.assertEqual(client.calls, [("propostas", {"pagina": 1})])

    def test_finds_on_previous_neighbor(self):
        client = FakeNomusClient(
            {
                ("propostas", 1): {"propostas": [{"proposta": "CP 05480"}]},
                ("propostas", 5): {"propostas": [{"proposta": "CP 05249"}]},
                ("propostas", 4): {"propostas": [{"proposta": "CP 05250"}]},
            }
        )
        locator = NomusProposalLocator(client, page_size=50, neighbor_limit=2)

        result = locator.locate_proposal("CP05250", "propostas")

        self.assertTrue(result.found)
        self.assertEqual(result.matched_page, 4)
        self.assertEqual(
            client.calls,
            [("propostas", {"pagina": 1}), ("propostas", {"pagina": 5}), ("propostas", {"pagina": 4})],
        )

    def test_finds_on_next_neighbor(self):
        client = FakeNomusClient(
            {
                ("propostas", 1): {"propostas": [{"proposta": "CP 05480"}]},
                ("propostas", 5): {"propostas": [{"proposta": "CP 05249"}]},
                ("propostas", 4): {"propostas": [{"proposta": "CP 05300"}]},
                ("propostas", 6): {"propostas": [{"proposta": "CP 05250"}]},
            }
        )
        locator = NomusProposalLocator(client, page_size=50, neighbor_limit=2)

        result = locator.locate_proposal("CP05250", "propostas")

        self.assertTrue(result.found)
        self.assertEqual(result.matched_page, 6)
        self.assertEqual(
            client.calls,
            [
                ("propostas", {"pagina": 1}),
                ("propostas", {"pagina": 5}),
                ("propostas", {"pagina": 4}),
                ("propostas", {"pagina": 6}),
            ],
        )

    def test_neighbor_pages_never_go_below_one(self):
        locator = NomusProposalLocator(FakeNomusClient({}), neighbor_limit=3)

        self.assertEqual(locator.candidate_pages(1), (1, 2, 3, 4))

    def test_returns_not_found_after_bounded_neighbors(self):
        client = FakeNomusClient(
            {
                ("propostas", 1): {"propostas": [{"proposta": "CP 05480"}]},
                ("propostas", 5): {"propostas": []},
                ("propostas", 4): {"propostas": []},
                ("propostas", 6): {"propostas": []},
            }
        )
        locator = NomusProposalLocator(client, page_size=50, neighbor_limit=1)

        result = locator.locate_proposal("CP05250", "propostas")

        self.assertFalse(result.found)
        self.assertEqual(result.pages_checked, 3)
        self.assertFalse(result.used_fallback_scan)

    def test_http_error_is_propagated_instead_of_becoming_not_found(self):
        error = NomusApiClientError("server_error", "Falha temporaria do Nomus")
        client = FakeNomusClient(
            {("propostas", 1): {"propostas": [{"proposta": "CP 05480"}]}},
            errors={("propostas", 5): error},
        )
        locator = NomusProposalLocator(client, page_size=50, neighbor_limit=1)

        with self.assertRaises(NomusApiClientError):
            locator.locate_proposal("CP05250", "propostas")

    def test_cancel_stops_before_fetching_neighbor_page(self):
        client = FakeNomusClient({("propostas", 5): {"propostas": [{"proposta": "CP 05250"}]}})
        locator = NomusProposalLocator(client, neighbor_limit=1)

        result = locator.search_neighbors("CP05250", "propostas", 5, is_cancelled=lambda: True)

        self.assertFalse(result.found)
        self.assertEqual(result.pages_checked, 0)
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
