"""Controlled, network-free benchmark for the Nomus batch importer."""

from __future__ import annotations

import json
import statistics
import sys
import threading
import time
import tracemalloc
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.nomus_api_importer import NomusApiImporter
from app.services.nomus_batch_import import NomusBatchImportService
from app.services.nomus_proposal_locator import NomusProposalLocator


class BenchmarkNomusClient:
    def __init__(
        self,
        pages: dict[tuple[str, int], Any],
        *,
        latency_seconds: float = 0.0,
        errors: dict[tuple[str, int], list[Exception]] | None = None,
    ):
        self.pages = pages
        self.latency_seconds = latency_seconds
        self.errors = {key: list(values) for key, values in (errors or {}).items()}
        self.calls: list[tuple[str, int | None]] = []
        self.weight_lookup_calls = 0
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def get(self, endpoint: str, params: dict[str, Any] | None = None):
        page = int(params["pagina"]) if params and params.get("pagina") is not None else None
        with self._lock:
            if endpoint.startswith("produtos"):
                self.weight_lookup_calls += 1
                raise AssertionError("The optimized import must not request product weights")
            self.calls.append((endpoint, page))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.latency_seconds:
                time.sleep(self.latency_seconds)
            key = (endpoint, page or 1)
            with self._lock:
                if self.errors.get(key):
                    raise self.errors[key].pop(0)
            return self.pages.get(key, {"propostas": []})
        finally:
            with self._lock:
                self.active -= 1


def proposal(number: int) -> dict[str, Any]:
    return {
        "id": number,
        "proposta": f"CP {number:05d}",
        "dataHoraAbertura": "2026-08-18T10:00:00",
        "nomeCliente": "CLIENTE BENCHMARK",
        "obraSite": "OBRA BENCHMARK",
        "itensProposta": [
            {
                "item": "1",
                "codigoProduto": "ITEM-1",
                "idProduto": 17517,
                "descricaoProduto": "ITEM OPERACIONAL",
                "nomeUnidadeMedida": "UNIDADE",
                "qtde": "2",
            }
        ],
    }


def same_page_scenario(count: int = 25, *, latest: int = 10_000, page: int = 20):
    targets = [latest - ((page - 1) * 50 + offset) for offset in range(count)]
    pages = {
        ("propostas", 1): {"propostas": [proposal(latest)]},
        ("propostas", page): {"propostas": [proposal(number) for number in targets]},
    }
    return pages, targets


def dispersed_scenario(count: int, *, latest: int = 20_000):
    targets = [latest - (index + 1) * 50 for index in range(count)]
    pages: dict[tuple[str, int], Any] = {("propostas", 1): {"propostas": [proposal(latest)]}}
    for index, number in enumerate(targets, start=2):
        pages[("propostas", index)] = {"propostas": [proposal(number)]}
    return pages, targets


def make_service(client: BenchmarkNomusClient, *, concurrency: int = 4) -> NomusBatchImportService:
    importer = NomusApiImporter(client, max_search_pages=250)
    locator = NomusProposalLocator(client, page_size=50, neighbor_limit=0, fallback_max_pages=250)
    return NomusBatchImportService(
        importer,
        locator=locator,
        endpoints=("propostas",),
        max_concurrency=concurrency,
        retry_backoffs=(0.0, 0.0, 0.0),
    )


def run_new_strategy(pages, targets, *, latency_seconds: float, concurrency: int = 4):
    client = BenchmarkNomusClient(pages, latency_seconds=latency_seconds)
    started = time.perf_counter()
    result = make_service(client, concurrency=concurrency).prepare_batch([f"CP{number:05d}" for number in targets])
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert result.counts_by_state().get("READY", 0) == len(targets)
    return elapsed_ms, client, result


def run_sequential_baseline(pages, targets, *, latency_seconds: float, latest: int):
    """Test-only model of the old per-target scan from page 1."""

    client = BenchmarkNomusClient(pages, latency_seconds=latency_seconds)
    started = time.perf_counter()
    for target in targets:
        target_page = max(1, (latest - target) // 50 + 1)
        for page in range(1, target_page + 1):
            client.get("propostas", params={"pagina": page})
    return (time.perf_counter() - started) * 1000.0, client


def run_benchmark(*, repeats: int = 3, request_latency_seconds: float = 0.001) -> dict[str, Any]:
    pages, targets = same_page_scenario()
    baseline_runs = [
        run_sequential_baseline(pages, targets, latency_seconds=request_latency_seconds, latest=10_000)
        for _ in range(repeats)
    ]
    optimized_runs = [
        run_new_strategy(pages, targets, latency_seconds=request_latency_seconds, concurrency=4)
        for _ in range(repeats)
    ]
    baseline_ms = statistics.median(run[0] for run in baseline_runs)
    optimized_ms = statistics.median(run[0] for run in optimized_runs)
    baseline_requests = len(baseline_runs[-1][1].calls)
    optimized_result = optimized_runs[-1][2]
    optimized_requests = optimized_result.metrics.http_requests_total

    concurrency: dict[str, Any] = {}
    spread_pages, spread_targets = dispersed_scenario(20)
    for workers in (1, 2, 4):
        runs = [
            run_new_strategy(spread_pages, spread_targets, latency_seconds=0.005, concurrency=workers)
            for _ in range(repeats)
        ]
        concurrency[str(workers)] = {
            "median_ms": round(statistics.median(run[0] for run in runs), 3),
            "http_requests": runs[-1][2].metrics.http_requests_total,
            "max_concurrency_observed": runs[-1][2].metrics.max_concurrency_observed,
        }

    loads: dict[str, Any] = {}
    for size in (1, 10, 25, 50, 100, 200):
        load_pages, load_targets = dispersed_scenario(size)
        tracemalloc.start()
        elapsed_ms, client, result = run_new_strategy(load_pages, load_targets, latency_seconds=0.0, concurrency=4)
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        loads[str(size)] = {
            "elapsed_ms": round(elapsed_ms, 3),
            "peak_memory_kib": round(peak / 1024.0, 1),
            "http_requests": result.metrics.http_requests_total,
            "ready": result.counts_by_state().get("READY", 0),
            "weight_lookup_requests": client.weight_lookup_calls,
        }

    return {
        "comparison_25_same_page": {
            "baseline_median_ms": round(baseline_ms, 3),
            "optimized_median_ms": round(optimized_ms, 3),
            "baseline_http_requests": baseline_requests,
            "optimized_http_requests": optimized_requests,
            "request_reduction_percent": round((1 - optimized_requests / baseline_requests) * 100.0, 2),
            "time_reduction_percent": round((1 - optimized_ms / baseline_ms) * 100.0, 2),
            "page_cache_hits": optimized_result.metrics.page_cache_hits,
            "grouped_page_reuses": optimized_result.metrics.grouped_page_reuses,
            "cache_effectiveness_percent": round(optimized_result.metrics.cache_effectiveness * 100.0, 2),
            "weight_lookup_requests": optimized_result.metrics.weight_lookup_requests,
        },
        "concurrency_20_dispersed": concurrency,
        "load": loads,
        "configuration": {
            "page_size": 50,
            "benchmark_neighbor_limit": 0,
            "production_neighbor_limit": 6,
            "production_max_concurrency": 4,
            "production_max_retries": 3,
            "production_backoff_seconds": [0.0, 0.05, 0.15],
        },
    }


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), ensure_ascii=True, indent=2, sort_keys=True))
