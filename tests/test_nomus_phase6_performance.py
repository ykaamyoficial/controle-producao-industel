from __future__ import annotations

import unittest

from app.services.nomus_api_client import NomusApiClientError
from app.services.nomus_api_importer import NomusApiImporter
from app.services.nomus_batch_import import NomusBatchTargetState
from scripts.benchmark_nomus_import import (
    BenchmarkNomusClient,
    dispersed_scenario,
    make_service,
    run_benchmark,
)


class NomusPhase6PerformanceTests(unittest.TestCase):
    def test_unit_and_batch_metrics_prove_zero_weight_requests(self):
        pages, targets = dispersed_scenario(1)
        client = BenchmarkNomusClient(pages)
        importer = NomusApiImporter(client, max_search_pages=10)

        imported = importer.fetch_proposal(f"CP{targets[0]:05d}")

        self.assertEqual(imported.proposal.proposal_number.replace(" ", ""), f"CP{targets[0]:05d}")
        self.assertIsNotNone(importer.last_metrics)
        self.assertEqual(importer.last_metrics.http_requests_total, 2)
        self.assertEqual(importer.last_metrics.requested_pages_unique, 2)
        self.assertEqual(importer.last_metrics.weight_lookup_requests, 0)
        self.assertEqual(client.weight_lookup_calls, 0)

        batch_client = BenchmarkNomusClient(pages)
        result = make_service(batch_client).prepare_batch([f"CP{targets[0]:05d}"])

        self.assertEqual(result.targets[0].state, NomusBatchTargetState.READY)
        self.assertEqual(result.metrics.http_requests_total, 2)
        self.assertEqual(result.metrics.requested_pages_unique, 2)
        self.assertEqual(result.metrics.weight_lookup_requests, 0)
        self.assertEqual(batch_client.weight_lookup_calls, 0)
        self.assertGreaterEqual(result.metrics.location_ms, 0.0)
        self.assertGreaterEqual(result.metrics.data_items_ms, 0.0)

    def test_429_500_and_503_are_counted_and_retried(self):
        pages, targets = dispersed_scenario(1)
        for status_code in (429, 500, 503):
            with self.subTest(status_code=status_code):
                category = "rate_limited" if status_code == 429 else "server_error"
                error = NomusApiClientError(category, "Falha temporaria", status_code=status_code)
                client = BenchmarkNomusClient(pages, errors={("propostas", 2): [error]})

                result = make_service(client).prepare_batch([f"CP{targets[0]:05d}"])

                self.assertEqual(result.targets[0].state, NomusBatchTargetState.READY)
                self.assertEqual(result.metrics.retries, 1)
                self.assertEqual(result.metrics.http_requests_total, 3)
                self.assertEqual(result.metrics.requested_pages_total, 3)

    def test_controlled_benchmark_and_load_matrix(self):
        report = run_benchmark(repeats=1, request_latency_seconds=0.0005)
        comparison = report["comparison_25_same_page"]

        self.assertEqual(comparison["baseline_http_requests"], 500)
        self.assertEqual(comparison["optimized_http_requests"], 2)
        self.assertGreaterEqual(comparison["request_reduction_percent"], 99.0)
        self.assertGreater(comparison["time_reduction_percent"], 50.0)
        self.assertEqual(comparison["grouped_page_reuses"], 24)
        self.assertGreater(comparison["cache_effectiveness_percent"], 90.0)
        self.assertEqual(comparison["weight_lookup_requests"], 0)

        for workers in (1, 2, 4):
            metrics = report["concurrency_20_dispersed"][str(workers)]
            self.assertLessEqual(metrics["max_concurrency_observed"], workers)
            self.assertEqual(metrics["http_requests"], 21)
        self.assertLess(
            report["concurrency_20_dispersed"]["4"]["median_ms"],
            report["concurrency_20_dispersed"]["1"]["median_ms"],
        )

        for size in (1, 10, 25, 50, 100, 200):
            load = report["load"][str(size)]
            self.assertEqual(load["ready"], size)
            self.assertEqual(load["http_requests"], size + 1)
            self.assertEqual(load["weight_lookup_requests"], 0)
            self.assertLess(load["peak_memory_kib"], 32 * 1024)
            self.assertLess(load["elapsed_ms"], 5000)


if __name__ == "__main__":
    unittest.main()
