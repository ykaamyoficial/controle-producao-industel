"""Lightweight, privacy-safe metrics for the Nomus import pipeline."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, Mapping


_STAGES = {"location", "data_items", "conference", "persistence"}


@dataclass(frozen=True)
class NomusImportMetricsSnapshot:
    batch_id: str
    proposal_count: int
    total_ms: float
    location_ms: float = 0.0
    data_items_ms: float = 0.0
    conference_ms: float = 0.0
    persistence_ms: float = 0.0
    http_requests_total: int = 0
    requested_pages_total: int = 0
    requested_pages_unique: int = 0
    requested_pages: tuple[tuple[str, int], ...] = ()
    page_cache_hits: int = 0
    grouped_page_reuses: int = 0
    retries: int = 0
    proposals_ready: int = 0
    proposals_already_exists: int = 0
    proposals_not_found: int = 0
    proposals_failed: int = 0
    proposals_persisted: int = 0
    persistence_failed: int = 0
    cancelled: int = 0
    weight_lookup_requests: int = 0

    @property
    def cache_effectiveness(self) -> float:
        reused = self.page_cache_hits + self.grouped_page_reuses
        denominator = reused + self.requested_pages_unique
        return reused / denominator if denominator else 0.0


@dataclass
class NomusImportMetricsCollector:
    """Collect counters and stage timings without retaining business data."""

    batch_id: str
    proposal_count: int = 0
    _started: float = field(default_factory=time.perf_counter, init=False, repr=False)
    _finished: float | None = field(default=None, init=False, repr=False)
    _stage_seconds: dict[str, float] = field(default_factory=dict, init=False, repr=False)
    _requested_pages: list[tuple[str, int]] = field(default_factory=list, init=False, repr=False)
    _http_requests: int = field(default=0, init=False, repr=False)
    _page_cache_hits: int = field(default=0, init=False, repr=False)
    _grouped_page_reuses: int = field(default=0, init=False, repr=False)
    _retries: int = field(default=0, init=False, repr=False)
    _weight_lookup_requests: int = field(default=0, init=False, repr=False)
    _status_counts: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _persistence_counts: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        if name not in _STAGES:
            raise ValueError(f"Unknown Nomus metrics stage: {name}")
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            with self._lock:
                self._stage_seconds[name] = self._stage_seconds.get(name, 0.0) + elapsed

    def record_http_request(self, endpoint: str, page: int | None = None, *, weight_lookup: bool = False) -> None:
        with self._lock:
            self._http_requests += 1
            if page is not None:
                self._requested_pages.append((str(endpoint), int(page)))
            if weight_lookup:
                self._weight_lookup_requests += 1

    def record_page_cache_hit(self) -> None:
        with self._lock:
            self._page_cache_hits += 1

    def record_grouped_page_reuses(self, count: int) -> None:
        with self._lock:
            self._grouped_page_reuses += max(0, int(count))

    def record_retry(self) -> None:
        with self._lock:
            self._retries += 1

    def set_status_counts(self, counts: Mapping[str, int]) -> None:
        with self._lock:
            self._status_counts = {str(key).upper(): int(value) for key, value in counts.items()}

    def set_persistence_counts(self, counts: Mapping[str, int]) -> None:
        with self._lock:
            self._persistence_counts = {str(key).upper(): int(value) for key, value in counts.items()}

    def finish(self) -> NomusImportMetricsSnapshot:
        with self._lock:
            if self._finished is None:
                self._finished = time.perf_counter()
            return self._snapshot_locked(self._finished)

    def snapshot(self) -> NomusImportMetricsSnapshot:
        with self._lock:
            return self._snapshot_locked(self._finished or time.perf_counter())

    def _snapshot_locked(self, ended: float) -> NomusImportMetricsSnapshot:
        pages = tuple(self._requested_pages)
        statuses = self._status_counts
        persistence = self._persistence_counts
        return NomusImportMetricsSnapshot(
            batch_id=self.batch_id,
            proposal_count=self.proposal_count,
            total_ms=_milliseconds(ended - self._started),
            location_ms=_milliseconds(self._stage_seconds.get("location", 0.0)),
            data_items_ms=_milliseconds(self._stage_seconds.get("data_items", 0.0)),
            conference_ms=_milliseconds(self._stage_seconds.get("conference", 0.0)),
            persistence_ms=_milliseconds(self._stage_seconds.get("persistence", 0.0)),
            http_requests_total=self._http_requests,
            requested_pages_total=len(pages),
            requested_pages_unique=len(set(pages)),
            requested_pages=pages,
            page_cache_hits=self._page_cache_hits,
            grouped_page_reuses=self._grouped_page_reuses,
            retries=self._retries,
            proposals_ready=statuses.get("READY", 0),
            proposals_already_exists=statuses.get("ALREADY_EXISTS", 0),
            proposals_not_found=statuses.get("NOT_FOUND", 0),
            proposals_failed=statuses.get("FAILED", 0),
            proposals_persisted=persistence.get("SAVED", 0),
            persistence_failed=persistence.get("FAILED", 0),
            cancelled=statuses.get("CANCELLED", 0) + persistence.get("CANCELLED", 0),
            weight_lookup_requests=self._weight_lookup_requests,
        )


def _milliseconds(seconds: float) -> float:
    return round(max(0.0, seconds) * 1000.0, 3)
