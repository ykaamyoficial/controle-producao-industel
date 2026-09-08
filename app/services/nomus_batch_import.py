from __future__ import annotations

import re
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable

from app.services.app_logging import get_logger
from app.services.nomus_api_client import NomusApiClientError
from app.services.nomus_api_importer import (
    NomusApiAmbiguousOrderError,
    NomusApiImporter,
    NomusApiImportError,
    NomusApiOrderNotFoundError,
    ORDER_ENDPOINT,
    PROPOSAL_ENDPOINT,
)
from app.services.nomus_import_metrics import NomusImportMetricsCollector, NomusImportMetricsSnapshot
from app.services.nomus_proposal_locator import (
    NomusProposalEnvelopeError,
    NomusProposalLocator,
    normalize_requested_identifier,
)
from app.services.proposal_import.schemas import StandardProposalImportResult


log = get_logger("nomus_batch_import")

BatchCancelCheck = Callable[[], bool]
ExistingProposalChecker = Callable[[str], bool]
BatchEventCallback = Callable[["NomusBatchEvent"], None]

NOMUS_IMPORT_MAX_CONCURRENCY = 4
NOMUS_IMPORT_MAX_RETRIES = 3
NOMUS_IMPORT_RETRY_BACKOFF_SECONDS = (0.0, 0.05, 0.15)

FORBIDDEN_FINANCIAL_TERMS = (
    "valorunitario",
    "valortotal",
    "valortotalprodutos",
    "valortotalfrete",
    "valorparcela",
    "percentualdesconto",
    "valoracrescimo",
    "condicaopagamento",
    "parcelas",
    "nfes",
    "r$",
)


class NomusBatchTargetState(str, Enum):
    QUEUED = "QUEUED"
    PENDING = "PENDING"
    INVALID = "INVALID"
    DUPLICATE_INPUT = "DUPLICATE_INPUT"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    LOCATING = "LOCATING"
    FOUND = "FOUND"
    FETCHING_DETAILS = "FETCHING_DETAILS"
    PREPARING = "PREPARING"
    RETRYING = "RETRYING"
    READY = "READY"
    NOT_FOUND = "NOT_FOUND"
    FAILED = "FAILED"
    ERROR = "FAILED"
    CANCELLED = "CANCELLED"


class NomusBatchEventType(str, Enum):
    BATCH_STARTED = "batch_started"
    PROPOSAL_STATE_CHANGED = "proposal_state_changed"
    BATCH_PROGRESS = "batch_progress"
    PROPOSAL_READY = "proposal_ready"
    BATCH_FINISHED = "batch_finished"
    BATCH_CANCELLED = "batch_cancelled"


@dataclass(frozen=True)
class NomusBatchEvent:
    event_type: NomusBatchEventType
    batch_id: str
    proposal_number: str | None = None
    state: NomusBatchTargetState | None = None
    message: str = ""
    completed: int = 0
    total: int = 0
    result: StandardProposalImportResult | None = None
    summary: dict[str, int] | None = None


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


@dataclass
class NomusBatchTargetResult:
    raw_input: str
    index: int
    state: NomusBatchTargetState = NomusBatchTargetState.PENDING
    canonical_identifier: str | None = None
    proposal_number: int | None = None
    duplicate_of: str | None = None
    endpoint: str | None = None
    estimated_page: int | None = None
    matched_page: int | None = None
    error: str | None = None
    prepared_result: StandardProposalImportResult | None = None
    matched_payload: dict[str, Any] | None = field(default=None, repr=False)

    @property
    def ready(self) -> bool:
        return self.state == NomusBatchTargetState.READY


@dataclass(frozen=True)
class NomusBatchMetrics:
    latest_reference_calls: int = 0
    page_fetches: int = 0
    page_cache_hits: int = 0
    grouped_page_reuses: int = 0
    pages_fetched: tuple[tuple[str, int], ...] = ()
    grouped_pages: dict[str, tuple[int, ...]] = field(default_factory=dict)
    simulated_individual_page_requests: int = 0
    retries: int = 0
    max_concurrency_observed: int = 0
    batch_id: str = ""
    global_error: str | None = None
    elapsed_ms: int = 0
    location_ms: float = 0.0
    data_items_ms: float = 0.0
    http_requests_total: int = 0
    requested_pages_total: int = 0
    requested_pages_unique: int = 0
    weight_lookup_requests: int = 0
    cache_effectiveness: float = 0.0
    telemetry: NomusImportMetricsSnapshot | None = field(default=None, repr=False)


@dataclass
class NomusBatchImportResult:
    targets: list[NomusBatchTargetResult]
    metrics: NomusBatchMetrics

    def by_identifier(self) -> dict[str, NomusBatchTargetResult]:
        return {
            target.canonical_identifier: target
            for target in self.targets
            if target.canonical_identifier and target.state != NomusBatchTargetState.DUPLICATE_INPUT
        }

    def counts_by_state(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for target in self.targets:
            counts[target.state.value] = counts.get(target.state.value, 0) + 1
        return counts


class NomusBatchImportService:
    def __init__(
        self,
        importer: NomusApiImporter,
        *,
        locator: NomusProposalLocator | None = None,
        exists_checker: ExistingProposalChecker | Any | None = None,
        endpoints: Iterable[str] = (PROPOSAL_ENDPOINT, ORDER_ENDPOINT),
        max_concurrency: int = NOMUS_IMPORT_MAX_CONCURRENCY,
        max_retries: int = NOMUS_IMPORT_MAX_RETRIES,
        retry_backoffs: tuple[float, ...] = NOMUS_IMPORT_RETRY_BACKOFF_SECONDS,
    ):
        self.importer = importer
        self.locator = locator or NomusProposalLocator(importer.client, page_size=50, fallback_max_pages=importer.max_search_pages)
        self.exists_checker = exists_checker
        self.endpoints = tuple(endpoints) or (PROPOSAL_ENDPOINT,)
        self.max_concurrency = max(1, int(max_concurrency or NOMUS_IMPORT_MAX_CONCURRENCY))
        self.max_retries = max(1, int(max_retries or NOMUS_IMPORT_MAX_RETRIES))
        self.retry_backoffs = tuple(retry_backoffs) or NOMUS_IMPORT_RETRY_BACKOFF_SECONDS
        self._page_cache: dict[tuple[str, int], list[dict[str, Any]]] = {}
        self._page_errors: dict[tuple[str, int], Exception] = {}
        self._latest_reference_cache: dict[str, int | None] = {}
        self._latest_reference_calls = 0
        self._page_fetches = 0
        self._page_cache_hits = 0
        self._simulated_individual_page_requests = 0
        self._retry_count = 0
        self._active_requests = 0
        self._max_concurrency_observed = 0
        self._global_error: str | None = None
        self._lock = threading.RLock()
        self._active_batch_id: str | None = None
        self._event_callback: BatchEventCallback | None = None
        self._current_targets: list[NomusBatchTargetResult] = []
        self._metrics_collector: NomusImportMetricsCollector | None = None

    def parse_targets(self, raw_input: str | Iterable[Any]) -> list[str]:
        if isinstance(raw_input, str):
            parts = re.split(r"[\n,;\t]+", raw_input)
        else:
            parts = [str(item) for item in raw_input]
        return [part.strip() for part in parts if str(part).strip()]

    def preview_targets(self, raw_input: str | Iterable[Any]) -> list[NomusBatchTargetResult]:
        """Normalize and dedupe user input without touching the Nomus API."""

        return self._normalize_and_dedupe(self.parse_targets(raw_input))

    def prepare_batch(
        self,
        raw_input: str | Iterable[Any],
        *,
        is_cancelled: BatchCancelCheck | None = None,
        cancellation_token: CancellationToken | None = None,
        event_callback: BatchEventCallback | None = None,
        batch_id: str | None = None,
    ) -> NomusBatchImportResult:
        batch_id = batch_id or uuid.uuid4().hex[:12]
        token = cancellation_token or CancellationToken()
        if is_cancelled and is_cancelled():
            token.cancel()
        self._reset_operation_cache()
        self._active_batch_id = batch_id
        self._event_callback = event_callback
        targets = self._normalize_and_dedupe(self.parse_targets(raw_input))
        self._metrics_collector = NomusImportMetricsCollector(batch_id, proposal_count=len(targets))
        self.locator.set_metrics_collector(self._metrics_collector)
        self._current_targets = targets
        effective = [
            target
            for target in targets
            if target.state not in {NomusBatchTargetState.INVALID, NomusBatchTargetState.DUPLICATE_INPUT}
        ]
        self._precheck_existing(effective)
        to_locate = [target for target in effective if target.state == NomusBatchTargetState.PENDING]
        for target in to_locate:
            self._set_state(target, NomusBatchTargetState.QUEUED, "Aguardando vaga na fila.", batch_id)
        self._emit(
            NomusBatchEvent(
                NomusBatchEventType.BATCH_STARTED,
                batch_id,
                total=len(effective),
                message="Importacao Nomus em lote iniciada.",
            )
        )
        log.info(
            "nomus.batch start batch_id=%s targets=%s valid=%s duplicates_input=%s already_exists=%s max_concurrency=%s",
            batch_id,
            len(targets),
            len(effective),
            sum(1 for target in targets if target.state == NomusBatchTargetState.DUPLICATE_INPUT),
            sum(1 for target in targets if target.state == NomusBatchTargetState.ALREADY_EXISTS),
            self.max_concurrency,
        )

        if self._cancelled(is_cancelled, token):
            self._cancel_pending(targets)
            result = self._build_result(targets, batch_id)
            self._emit_finished(result, batch_id, cancelled=True)
            return result

        with self._metrics_collector.stage("location"):
            self._locate_targets_grouped(to_locate, is_cancelled=is_cancelled, cancellation_token=token, batch_id=batch_id)
        if self._cancelled(is_cancelled, token):
            self._cancel_pending(targets)
            result = self._build_result(targets, batch_id)
            self._emit_finished(result, batch_id, cancelled=True)
            return result

        with self._metrics_collector.stage("data_items"):
            self._prepare_found_targets(to_locate, is_cancelled=is_cancelled, cancellation_token=token, batch_id=batch_id)
        result = self._build_result(targets, batch_id)
        counts = result.counts_by_state()
        log.info(
            "nomus.batch complete batch_id=%s ready=%s already_exists=%s not_found=%s failed=%s cancelled=%s pages=%s http_requests=%s cache_hits=%s retries=%s weight_lookups=%s location_ms=%s data_items_ms=%s elapsed_ms=%s",
            batch_id,
            counts.get(NomusBatchTargetState.READY.value, 0),
            counts.get(NomusBatchTargetState.ALREADY_EXISTS.value, 0),
            counts.get(NomusBatchTargetState.NOT_FOUND.value, 0),
            counts.get(NomusBatchTargetState.FAILED.value, 0),
            counts.get(NomusBatchTargetState.CANCELLED.value, 0),
            result.metrics.page_fetches,
            result.metrics.http_requests_total,
            result.metrics.page_cache_hits,
            result.metrics.retries,
            result.metrics.weight_lookup_requests,
            result.metrics.location_ms,
            result.metrics.data_items_ms,
            result.metrics.elapsed_ms,
        )
        self._log_efficiency_warnings(result.metrics)
        self._emit_finished(result, batch_id, cancelled=bool(counts.get(NomusBatchTargetState.CANCELLED.value, 0)))
        return result

    def _normalize_and_dedupe(self, raw_targets: list[str]) -> list[NomusBatchTargetResult]:
        targets: list[NomusBatchTargetResult] = []
        first_seen: dict[int, str] = {}
        for index, raw in enumerate(raw_targets):
            result = NomusBatchTargetResult(raw_input=raw, index=index)
            normalized = normalize_requested_identifier(raw)
            if normalized.number is None:
                result.state = NomusBatchTargetState.INVALID
                result.error = "Identificador de proposta invalido."
                result.canonical_identifier = normalized.compact or raw
                targets.append(result)
                continue
            number = int(normalized.number)
            result.proposal_number = number
            result.canonical_identifier = normalized.safe_log if normalized.prefix else str(number)
            if number in first_seen:
                result.state = NomusBatchTargetState.DUPLICATE_INPUT
                result.duplicate_of = first_seen[number]
            else:
                first_seen[number] = result.canonical_identifier
            targets.append(result)
        return targets

    def _precheck_existing(self, targets: list[NomusBatchTargetResult]) -> None:
        for target in targets:
            if target.canonical_identifier and self._exists_locally(target.canonical_identifier):
                target.state = NomusBatchTargetState.ALREADY_EXISTS

    def _locate_targets_grouped(
        self,
        targets: list[NomusBatchTargetResult],
        *,
        is_cancelled: BatchCancelCheck | None,
        cancellation_token: CancellationToken,
        batch_id: str,
    ) -> None:
        for endpoint in self.endpoints:
            pending = [target for target in targets if target.state in {NomusBatchTargetState.PENDING, NomusBatchTargetState.QUEUED}]
            if not pending or self._cancelled(is_cancelled, cancellation_token):
                return
            latest = self._latest_reference(endpoint)
            if latest is None:
                for target in pending:
                    target.endpoint = endpoint
                    target.error = "Nao foi possivel obter a referencia de pagina do Nomus."
                    self._set_state(target, NomusBatchTargetState.FAILED, target.error, batch_id)
                continue
            if any(int(target.proposal_number or 0) > latest for target in pending):
                log.warning(
                    "nomus.batch latest_reference_inconsistent batch_id=%s endpoint=%s targets_above_reference=%s",
                    batch_id,
                    endpoint,
                    sum(1 for target in pending if int(target.proposal_number or 0) > latest),
                )
            groups: dict[int, list[NomusBatchTargetResult]] = defaultdict(list)
            for target in pending:
                target.endpoint = endpoint
                target.estimated_page = self.locator.estimate_page(int(target.proposal_number or 0), latest)
                self._set_state(target, NomusBatchTargetState.LOCATING, f"Localizando em {endpoint}, pagina estimada {target.estimated_page}.", batch_id)
                groups[target.estimated_page].append(target)
                self._simulated_individual_page_requests += 1
            if self._metrics_collector is not None:
                self._metrics_collector.record_grouped_page_reuses(
                    sum(max(0, len(page_targets) - 1) for page_targets in groups.values())
                )
            log.info(
                "nomus.batch reference latest=%s page_size=%s endpoint=%s",
                latest,
                self.locator.page_size,
                endpoint,
            )
            log.info("nomus.batch groups endpoint=%s pages=%s", endpoint, sorted(groups))
            self._fetch_pages_and_resolve(endpoint, sorted(groups), pending, is_cancelled=is_cancelled, cancellation_token=cancellation_token, batch_id=batch_id)
            self._resolve_neighbors(endpoint, pending, is_cancelled=is_cancelled, cancellation_token=cancellation_token, batch_id=batch_id)
            if self._cancelled(is_cancelled, cancellation_token):
                return

        for target in targets:
            if target.state in {NomusBatchTargetState.PENDING, NomusBatchTargetState.QUEUED, NomusBatchTargetState.LOCATING}:
                self._set_state(target, NomusBatchTargetState.NOT_FOUND, "Busca de proximidade esgotada.", batch_id)

    def _fetch_pages_and_resolve(
        self,
        endpoint: str,
        pages: list[int],
        targets: list[NomusBatchTargetResult],
        *,
        is_cancelled: BatchCancelCheck | None,
        cancellation_token: CancellationToken,
        batch_id: str,
    ) -> None:
        page_results = self._fetch_pages(endpoint, pages, is_cancelled=is_cancelled, cancellation_token=cancellation_token, batch_id=batch_id)
        for page, outcome in page_results.items():
            page_targets = [target for target in targets if target.estimated_page == page and target.state == NomusBatchTargetState.LOCATING]
            if isinstance(outcome, Exception):
                for target in page_targets:
                    target.error = self._error_message(outcome)
                    self._set_state(target, NomusBatchTargetState.FAILED, target.error, batch_id)
                continue
            self._resolve_pending_from_records(endpoint, page, outcome, targets, batch_id=batch_id)

    def _resolve_neighbors(
        self,
        endpoint: str,
        targets: list[NomusBatchTargetResult],
        *,
        is_cancelled: BatchCancelCheck | None,
        cancellation_token: CancellationToken,
        batch_id: str,
    ) -> None:
        for offset in range(1, self.locator.neighbor_limit + 1):
            pending = [
                target
                for target in targets
                if target.state == NomusBatchTargetState.LOCATING and target.estimated_page is not None
            ]
            if not pending or self._cancelled(is_cancelled, cancellation_token):
                return
            pages: set[int] = set()
            for target in pending:
                previous = int(target.estimated_page or 1) - offset
                if previous >= 1:
                    pages.add(previous)
                pages.add(int(target.estimated_page or 1) + offset)
            page_results = self._fetch_pages(endpoint, sorted(pages), is_cancelled=is_cancelled, cancellation_token=cancellation_token, batch_id=batch_id)
            for page, outcome in page_results.items():
                if isinstance(outcome, Exception):
                    continue
                self._resolve_pending_from_records(endpoint, page, outcome, pending, batch_id=batch_id)

    def _resolve_pending_from_records(
        self,
        endpoint: str,
        page: int,
        records: list[dict[str, Any]],
        targets: list[NomusBatchTargetResult],
        *,
        batch_id: str,
    ) -> None:
        for target in targets:
            if target.state != NomusBatchTargetState.LOCATING or not target.canonical_identifier:
                continue
            matches = self.locator.find_in_page(records, target.canonical_identifier)
            if len(matches) > 1:
                target.error = f"Mais de um pedido Nomus foi encontrado para {target.canonical_identifier}."
                target.endpoint = endpoint
                target.matched_page = page
                self._set_state(target, NomusBatchTargetState.FAILED, target.error, batch_id)
            elif len(matches) == 1:
                target.endpoint = endpoint
                target.matched_page = page
                target.matched_payload = matches[0]
                self._set_state(target, NomusBatchTargetState.FOUND, f"Proposta localizada na pagina {page}.", batch_id)
                log.info("nomus.batch target=%s state=FOUND endpoint=%s page=%s", target.canonical_identifier, endpoint, page)

    def _fetch_pages(
        self,
        endpoint: str,
        pages: list[int],
        *,
        is_cancelled: BatchCancelCheck | None,
        cancellation_token: CancellationToken,
        batch_id: str,
    ) -> dict[int, list[dict[str, Any]] | Exception]:
        results: dict[int, list[dict[str, Any]] | Exception] = {}
        pages_to_fetch: list[int] = []
        for page in dict.fromkeys(int(page) for page in pages if int(page) >= 1):
            if self._cancelled(is_cancelled, cancellation_token):
                break
            cached = self._cached_page(endpoint, page)
            if cached is not None:
                results[page] = cached
            else:
                pages_to_fetch.append(page)
        if not pages_to_fetch or self._cancelled(is_cancelled, cancellation_token):
            return results

        executor = ThreadPoolExecutor(max_workers=self.max_concurrency, thread_name_prefix="nomus-batch")
        futures: dict[Future[list[dict[str, Any]]], int] = {}
        try:
            for page in pages_to_fetch:
                if self._cancelled(is_cancelled, cancellation_token):
                    break
                futures[executor.submit(self._fetch_page, endpoint, page, cancellation_token, batch_id)] = page
            for future in as_completed(futures):
                page = futures[future]
                if self._cancelled(is_cancelled, cancellation_token):
                    break
                try:
                    results[page] = future.result()
                except Exception as exc:
                    results[page] = exc
                    if self._is_global_error(exc):
                        self._global_error = self._error_message(exc)
                        cancellation_token.cancel()
                        break
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return results

    def _prepare_found_targets(
        self,
        targets: list[NomusBatchTargetResult],
        *,
        is_cancelled: BatchCancelCheck | None,
        cancellation_token: CancellationToken,
        batch_id: str,
    ) -> None:
        for target in targets:
            if target.state != NomusBatchTargetState.FOUND:
                continue
            if self._cancelled(is_cancelled, cancellation_token):
                self._set_state(target, NomusBatchTargetState.CANCELLED, "Importacao cancelada antes da preparacao.", batch_id)
                continue
            self._set_state(target, NomusBatchTargetState.FETCHING_DETAILS, "Preparando dados operacionais.", batch_id)
            try:
                if not target.matched_payload:
                    raise NomusApiOrderNotFoundError("Payload Nomus nao encontrado para preparacao.")
                result = self.importer.convert_order_payload(
                    target.matched_payload,
                    requested_identifier=target.canonical_identifier,
                    endpoint=target.endpoint or PROPOSAL_ENDPOINT,
                    search_pages=len(self._page_cache),
                    enrich_product_weights=False,
                )
                self._assert_no_financial_payload(result)
                target.prepared_result = result
                if result.errors:
                    target.error = "; ".join(issue.message for issue in result.errors)
                    self._set_state(target, NomusBatchTargetState.FAILED, target.error, batch_id)
                else:
                    self._set_state(target, NomusBatchTargetState.READY, "Dados prontos para conferencia.", batch_id)
                    self._emit(
                        NomusBatchEvent(
                            NomusBatchEventType.PROPOSAL_READY,
                            batch_id,
                            proposal_number=target.canonical_identifier,
                            state=target.state,
                            message="Proposta pronta para conferencia.",
                            result=result,
                        )
                    )
                log.info("nomus.batch target=%s state=%s", target.canonical_identifier, target.state.value)
            except Exception as exc:
                target.error = self._error_message(exc)
                self._set_state(target, NomusBatchTargetState.FAILED, target.error, batch_id)

    def _cached_page(self, endpoint: str, page: int) -> list[dict[str, Any]] | None:
        key = (endpoint, int(page))
        with self._lock:
            if key in self._page_cache:
                self._page_cache_hits += 1
                if self._metrics_collector is not None:
                    self._metrics_collector.record_page_cache_hit()
                log.info("nomus.batch fetch_page page=%s endpoint=%s cache_hit=true", page, endpoint)
                return self._page_cache[key]
        return None

    def _fetch_page(self, endpoint: str, page: int, cancellation_token: CancellationToken | None = None, batch_id: str | None = None) -> list[dict[str, Any]]:
        key = (endpoint, int(page))
        cached = self._cached_page(endpoint, int(page))
        if cached is not None:
            return cached
        log.info("nomus.batch fetch_page page=%s endpoint=%s cache_hit=false", page, endpoint)
        records = self._fetch_page_with_retry(endpoint, int(page), cancellation_token or CancellationToken(), batch_id or "")
        with self._lock:
            self._page_cache[key] = records
            self._page_fetches += 1
        return records

    def _fetch_page_with_retry(
        self,
        endpoint: str,
        page: int,
        cancellation_token: CancellationToken,
        batch_id: str,
    ) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            if cancellation_token.is_cancelled():
                raise NomusApiImportError("Importacao Nomus em lote cancelada.")
            if attempt > 1:
                backoff = self.retry_backoffs[min(attempt - 1, len(self.retry_backoffs) - 1)]
                if backoff > 0:
                    time.sleep(backoff)
            try:
                self._request_started()
                return self.locator.fetch_page(endpoint, page)
            except Exception as exc:
                last_error = exc
                if self._is_global_error(exc):
                    raise
                if not self._is_transient_error(exc) or attempt >= self.max_retries:
                    raise
                with self._lock:
                    self._retry_count += 1
                if self._metrics_collector is not None:
                    self._metrics_collector.record_retry()
                self._emit(
                    NomusBatchEvent(
                        NomusBatchEventType.PROPOSAL_STATE_CHANGED,
                        batch_id,
                        state=NomusBatchTargetState.RETRYING,
                        message=f"Falha transitoria ao consultar pagina {page}; nova tentativa {attempt + 1}.",
                    )
                )
                log.info("nomus.batch retry batch_id=%s endpoint=%s page=%s attempt=%s", batch_id, endpoint, page, attempt + 1)
            finally:
                self._request_finished()
        raise last_error or NomusApiImportError("Falha ao consultar pagina Nomus.")

    def _latest_reference(self, endpoint: str) -> int | None:
        if endpoint in self._latest_reference_cache:
            return self._latest_reference_cache[endpoint]
        self._latest_reference_calls += 1
        try:
            records = self._fetch_page(endpoint, 1)
        except Exception as exc:
            if self._is_global_error(exc):
                self._global_error = self._error_message(exc)
            self._latest_reference_cache[endpoint] = None
            return None
        latest: int | None = None
        for record in records:
            for candidate in _reference_candidates(record):
                number = self.locator.normalize_proposal_number(candidate)
                if number is not None and (latest is None or number > latest):
                    latest = number
        self._latest_reference_cache[endpoint] = latest
        return latest

    def _exists_locally(self, proposal_number: str) -> bool:
        checker = self.exists_checker
        if checker is None:
            return False
        if callable(checker):
            return bool(checker(proposal_number))
        for method_name in (
            "proposal_exists",
            "proposal_already_exists",
            "process_exists",
            "has_proposal",
            "exists_proposal",
        ):
            method = getattr(checker, method_name, None)
            if callable(method):
                return bool(method(proposal_number))
        return False

    def _build_result(self, targets: list[NomusBatchTargetResult], batch_id: str) -> NomusBatchImportResult:
        grouped_pages: dict[str, tuple[int, ...]] = {}
        for endpoint in self.endpoints:
            grouped_pages[endpoint] = tuple(
                sorted(
                    {
                        int(target.estimated_page)
                        for target in targets
                        if target.endpoint == endpoint and target.estimated_page is not None
                    }
                )
            )
        counts: dict[str, int] = {}
        for target in targets:
            counts[target.state.value] = counts.get(target.state.value, 0) + 1
        collector = self._metrics_collector or NomusImportMetricsCollector(batch_id, proposal_count=len(targets))
        collector.set_status_counts(counts)
        telemetry = collector.finish()
        metrics = NomusBatchMetrics(
            latest_reference_calls=self._latest_reference_calls,
            page_fetches=self._page_fetches,
            page_cache_hits=telemetry.page_cache_hits,
            grouped_page_reuses=telemetry.grouped_page_reuses,
            pages_fetched=tuple(sorted(self._page_cache)),
            grouped_pages=grouped_pages,
            simulated_individual_page_requests=self._simulated_individual_page_requests,
            retries=self._retry_count,
            max_concurrency_observed=self._max_concurrency_observed,
            batch_id=batch_id,
            global_error=self._global_error,
            elapsed_ms=int(round(telemetry.total_ms)),
            location_ms=telemetry.location_ms,
            data_items_ms=telemetry.data_items_ms,
            http_requests_total=telemetry.http_requests_total,
            requested_pages_total=telemetry.requested_pages_total,
            requested_pages_unique=telemetry.requested_pages_unique,
            weight_lookup_requests=telemetry.weight_lookup_requests,
            cache_effectiveness=telemetry.cache_effectiveness,
            telemetry=telemetry,
        )
        return NomusBatchImportResult(targets=targets, metrics=metrics)

    def _reset_operation_cache(self) -> None:
        self._page_cache = {}
        self._page_errors = {}
        self._latest_reference_cache = {}
        self.locator.reset_operation_cache(reset_reference=True)
        self._latest_reference_calls = 0
        self._page_fetches = 0
        self._page_cache_hits = 0
        self._simulated_individual_page_requests = 0
        self._retry_count = 0
        self._active_requests = 0
        self._max_concurrency_observed = 0
        self._global_error = None
        self._metrics_collector = None
        self.locator.set_metrics_collector(None)

    def _log_efficiency_warnings(self, metrics: NomusBatchMetrics) -> None:
        individual = metrics.simulated_individual_page_requests
        grouped_requests = max(0, metrics.page_fetches - metrics.latest_reference_calls)
        if individual >= 10 and grouped_requests >= max(1, int(individual * 0.9)):
            log.warning(
                "nomus.batch low_cache_effectiveness batch_id=%s individual_pages=%s grouped_pages=%s",
                metrics.batch_id,
                individual,
                grouped_requests,
            )
        if metrics.requested_pages_unique > max(12, individual * 2):
            log.warning(
                "nomus.batch wide_neighbor_search batch_id=%s requested_pages_unique=%s targets=%s",
                metrics.batch_id,
                metrics.requested_pages_unique,
                individual,
            )

    def _cancel_pending(self, targets: list[NomusBatchTargetResult]) -> None:
        for target in targets:
            if target.state in {
                NomusBatchTargetState.PENDING,
                NomusBatchTargetState.QUEUED,
                NomusBatchTargetState.LOCATING,
                NomusBatchTargetState.FOUND,
                NomusBatchTargetState.PREPARING,
                NomusBatchTargetState.FETCHING_DETAILS,
                NomusBatchTargetState.RETRYING,
            }:
                target.state = NomusBatchTargetState.CANCELLED

    def _cancelled(self, callback: BatchCancelCheck | None, token: CancellationToken | None = None) -> bool:
        cancelled = bool((token and token.is_cancelled()) or (callback and callback()))
        if cancelled and token:
            token.cancel()
        return cancelled

    def _set_state(
        self,
        target: NomusBatchTargetResult,
        state: NomusBatchTargetState,
        message: str,
        batch_id: str,
    ) -> None:
        target.state = state
        self._emit(
            NomusBatchEvent(
                NomusBatchEventType.PROPOSAL_STATE_CHANGED,
                batch_id,
                proposal_number=target.canonical_identifier,
                state=state,
                message=message,
            )
        )
        self._emit_progress_for_current_batch(batch_id)

    def _emit_progress_for_current_batch(self, batch_id: str) -> None:
        callback = self._event_callback
        if callback is None:
            return
        # Progress is emitted from the orchestration thread; lock only protects
        # active-batch identity against stale callbacks from cancelled work.
        if batch_id != self._active_batch_id:
            return
        total = len([target for target in self._current_targets if target.state != NomusBatchTargetState.DUPLICATE_INPUT])
        completed_states = {
            NomusBatchTargetState.READY,
            NomusBatchTargetState.ALREADY_EXISTS,
            NomusBatchTargetState.NOT_FOUND,
            NomusBatchTargetState.FAILED,
            NomusBatchTargetState.CANCELLED,
            NomusBatchTargetState.INVALID,
        }
        completed = len([target for target in self._current_targets if target.state in completed_states])
        self._emit(NomusBatchEvent(NomusBatchEventType.BATCH_PROGRESS, batch_id, completed=completed, total=total))

    def _emit_finished(self, result: NomusBatchImportResult, batch_id: str, *, cancelled: bool) -> None:
        event_type = NomusBatchEventType.BATCH_CANCELLED if cancelled else NomusBatchEventType.BATCH_FINISHED
        self._emit(
            NomusBatchEvent(
                event_type,
                batch_id,
                total=len(result.targets),
                completed=sum(1 for target in result.targets if target.state not in {NomusBatchTargetState.QUEUED, NomusBatchTargetState.PENDING, NomusBatchTargetState.LOCATING}),
                summary=result.counts_by_state(),
                message="Importacao Nomus em lote cancelada." if cancelled else "Importacao Nomus em lote finalizada.",
            )
        )

    def _emit(self, event: NomusBatchEvent) -> None:
        callback = self._event_callback
        if callback is None or event.batch_id != self._active_batch_id:
            return
        callback(event)

    def _request_started(self) -> None:
        with self._lock:
            self._active_requests += 1
            self._max_concurrency_observed = max(self._max_concurrency_observed, self._active_requests)

    def _request_finished(self) -> None:
        with self._lock:
            self._active_requests = max(0, self._active_requests - 1)

    def _is_transient_error(self, exc: Exception) -> bool:
        if not isinstance(exc, NomusApiClientError):
            return isinstance(exc, (TimeoutError, ConnectionError, OSError))
        status = exc.status_code or 0
        return exc.category in {"timeout", "connection", "network", "rate_limited", "server_error"} or status in {408, 429} or status >= 500

    def _is_global_error(self, exc: Exception) -> bool:
        return isinstance(exc, NomusApiClientError) and exc.category in {"invalid_key", "forbidden", "login_redirect", "invalid_configuration"}

    def _assert_no_financial_payload(self, result: StandardProposalImportResult) -> None:
        serialized = result.to_json().lower()
        for term in FORBIDDEN_FINANCIAL_TERMS:
            if term in serialized:
                raise NomusApiImportError(f"Campo financeiro bloqueado no resultado preparado: {term}")

    def _error_message(self, exc: Exception) -> str:
        if isinstance(exc, NomusApiClientError):
            return exc.user_message
        if isinstance(exc, (NomusApiImportError, NomusProposalEnvelopeError, NomusApiAmbiguousOrderError)):
            return str(exc)
        return str(exc) or exc.__class__.__name__


def _identifier_candidates(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        record.get("codigoPedido"),
        record.get("proposta"),
        record.get("codigoProposta"),
        record.get("numeroProposta"),
        record.get("idExterno"),
        record.get("numeroPedido"),
        record.get("pedido"),
        record.get("id"),
    )


def _reference_candidates(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        record.get("codigoPedido"),
        record.get("proposta"),
        record.get("codigoProposta"),
        record.get("numeroProposta"),
        record.get("numeroPedido"),
        record.get("pedido"),
    )
