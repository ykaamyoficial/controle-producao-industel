from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from app.services.app_logging import get_logger

if TYPE_CHECKING:
    from app.services.nomus_import_metrics import NomusImportMetricsCollector


log = get_logger("nomus_locator")

DEFAULT_PAGE_SIZE = 50
DEFAULT_NEIGHBOR_LIMIT = 6
DEFAULT_FALLBACK_MAX_PAGES = 50

DetailCallback = Callable[[str], None]
CancelCheck = Callable[[], bool]


class NomusProposalEnvelopeError(RuntimeError):
    """Raised when a page payload cannot be interpreted as a list of proposals/pedidos."""


@dataclass(frozen=True)
class _NormalizedIdentifier:
    prefix: str | None
    number: str | None
    compact: str
    safe_log: str


def normalize_requested_identifier(value: str) -> _NormalizedIdentifier:
    text = re.sub(r"\s+", " ", str(value or "")).strip().upper()
    compact = re.sub(r"[\s._/-]+", "", text)
    match = re.match(r"^([A-Z]+)0*([0-9]+)$", compact)
    if match:
        prefix, number = match.groups()
        safe = f"{prefix}{number.zfill(5)}"
        return _NormalizedIdentifier(prefix, str(int(number)), compact, safe)
    if compact.isdigit():
        return _NormalizedIdentifier(None, str(int(compact)), compact, f"ID:{int(compact)}")
    return _NormalizedIdentifier(None, None, compact, compact[:24])


def _identifiers_match(left: Any, right: Any) -> bool:
    a = normalize_requested_identifier(str(left))
    b = normalize_requested_identifier(str(right))
    if a.prefix and b.prefix:
        return a.prefix == b.prefix and a.number == b.number
    if a.prefix and not b.prefix:
        return False
    if a.number is not None and b.number is not None:
        return a.number == b.number
    return a.compact == b.compact


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


def _record_matches_identifier(requested: str, record: dict[str, Any]) -> bool:
    return any(_identifiers_match(requested, candidate) for candidate in _identifier_candidates(record) if candidate is not None)


def _extract_order_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        raise NomusProposalEnvelopeError("Resposta Nomus incompativel: lista de pedidos invalida.")
    for key in ("pedidos", "propostas", "dados", "data", "resultados", "items", "content"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if "codigoPedido" in payload or "proposta" in payload:
        return [{key: value for key, value in payload.items() if not str(key).startswith("_nomus_")}]
    log.warning(
        "Envelope Nomus incompativel | raiz=%s | chaves=%s",
        type(payload).__name__,
        _safe_payload_keys(payload),
    )
    raise NomusProposalEnvelopeError("Resposta Nomus incompativel: lista de pedidos nao encontrada.")


def _safe_payload_keys(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        return [str(key) for key in payload.keys() if not str(key).startswith("_nomus_")][:40]
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return [str(key) for key in payload[0].keys() if not str(key).startswith("_nomus_")][:40]
    return []


@dataclass(frozen=True)
class NomusProposalLocateResult:
    """Outcome of a proposal/pedido lookup for a single Nomus endpoint."""

    matches: list[dict[str, Any]]
    endpoint: str
    matched_page: int | None
    pages_checked: int
    estimated_page: int | None
    used_fallback_scan: bool

    @property
    def found(self) -> bool:
        return bool(self.matches)


class NomusProposalLocator:
    """Locate a Nomus proposal/pedido by estimated page instead of scanning from page 1.

    The estimate uses the current highest known proposal number as a reference:
    since proposal numbers grow over time and the Nomus listing is read newest-first,
    the distance between the latest proposal and the target approximates how many
    pages separate them. The estimate is only an approximation (numbering can have
    gaps, cancellations or deletions), so a bounded neighbor expansion absorbs the
    difference instead of falling back to a full page-1 scan.

    Reusable by both the single-proposal lookup (Fase 1) and the future batch
    import engine (Fase 2), since neither depends on any UI framework.
    """

    def __init__(
        self,
        client: Any,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        neighbor_limit: int = DEFAULT_NEIGHBOR_LIMIT,
        fallback_max_pages: int = DEFAULT_FALLBACK_MAX_PAGES,
        metrics_collector: NomusImportMetricsCollector | None = None,
    ):
        self.client = client
        self.page_size = max(1, int(page_size or DEFAULT_PAGE_SIZE))
        self.neighbor_limit = max(0, int(neighbor_limit))
        self.fallback_max_pages = max(1, int(fallback_max_pages or DEFAULT_FALLBACK_MAX_PAGES))
        self._latest_reference_cache: dict[str, int | None] = {}
        self._page_cache: dict[tuple[str, int], list[dict[str, Any]]] = {}
        self.metrics_collector = metrics_collector

    def set_metrics_collector(self, collector: NomusImportMetricsCollector | None) -> None:
        self.metrics_collector = collector

    def reset_operation_cache(self, *, reset_reference: bool = True) -> None:
        self._page_cache = {}
        if reset_reference:
            self._latest_reference_cache = {}

    def normalize_proposal_number(self, value: Any) -> int | None:
        if value is None:
            return None
        normalized = normalize_requested_identifier(str(value))
        return int(normalized.number) if normalized.number is not None else None

    def get_latest_reference(self, endpoint: str) -> int | None:
        """Return the highest proposal number seen on page 1, reusing it for the rest of the operation."""

        if endpoint in self._latest_reference_cache:
            return self._latest_reference_cache[endpoint]
        records = self.fetch_page(endpoint, 1)
        latest: int | None = None
        for record in records:
            for candidate in _reference_candidates(record):
                number = self.normalize_proposal_number(candidate)
                if number is not None and (latest is None or number > latest):
                    latest = number
        self._latest_reference_cache[endpoint] = latest
        return latest

    def estimate_page(self, target: int, latest: int) -> int:
        delta = latest - target
        index_estimated = max(0, delta)
        return index_estimated // self.page_size + 1

    def fetch_page(self, endpoint: str, page: int) -> list[dict[str, Any]]:
        cache_key = (endpoint, page)
        if cache_key in self._page_cache:
            if self.metrics_collector is not None:
                self.metrics_collector.record_page_cache_hit()
            return self._page_cache[cache_key]
        if self.metrics_collector is not None:
            self.metrics_collector.record_http_request(endpoint, page)
        payload = self.client.get(endpoint, params={"pagina": page})
        records = _extract_order_list(payload)
        self._page_cache[cache_key] = records
        return records

    def find_in_page(self, records: list[dict[str, Any]], requested_identifier: str) -> list[dict[str, Any]]:
        return [record for record in records if _record_matches_identifier(requested_identifier, record)]

    def locate_proposal(
        self,
        requested_identifier: str,
        endpoint: str,
        *,
        progress_callback: DetailCallback | None = None,
        is_cancelled: CancelCheck | None = None,
    ) -> NomusProposalLocateResult:
        self.reset_operation_cache(reset_reference=True)
        target = self.normalize_proposal_number(requested_identifier)
        if target is None:
            return self._fallback_scan(
                requested_identifier,
                endpoint,
                reason="identificador_nao_numerico",
                progress_callback=progress_callback,
                is_cancelled=is_cancelled,
            )

        latest = self.get_latest_reference(endpoint)
        if latest is None:
            return self._fallback_scan(
                requested_identifier,
                endpoint,
                reason="referencia_indisponivel",
                progress_callback=progress_callback,
                is_cancelled=is_cancelled,
            )

        estimated_page = self.estimate_page(target, latest)
        log.info(
            "nomus.locator target=%s latest=%s page_size=%s estimated_page=%s endpoint=%s",
            target,
            latest,
            self.page_size,
            estimated_page,
            endpoint,
        )
        return self.search_neighbors(
            requested_identifier,
            endpoint,
            estimated_page,
            progress_callback=progress_callback,
            is_cancelled=is_cancelled,
        )

    def search_neighbors(
        self,
        requested_identifier: str,
        endpoint: str,
        estimated_page: int,
        *,
        progress_callback: DetailCallback | None = None,
        is_cancelled: CancelCheck | None = None,
    ) -> NomusProposalLocateResult:
        pages_checked = 0
        for page in self._candidate_pages(estimated_page):
            if is_cancelled and is_cancelled():
                log.info("nomus.locator cancelled | endpoint=%s | pages_checked=%s", endpoint, pages_checked)
                return NomusProposalLocateResult([], endpoint, None, pages_checked, estimated_page, False)
            label = "Consultando pagina estimada" if page == estimated_page else "Ajustando busca na pagina vizinha"
            _emit(progress_callback, f"{label} {page}.")
            started = time.perf_counter()
            records = self.fetch_page(endpoint, page)
            pages_checked += 1
            matches = self.find_in_page(records, requested_identifier)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            if matches:
                log.info("nomus.locator page=%s result=found elapsed_ms=%s", page, elapsed_ms)
                return NomusProposalLocateResult(matches, endpoint, page, pages_checked, estimated_page, False)
            log.info(
                "nomus.locator fallback page=%s reason=%s elapsed_ms=%s",
                page,
                "not_found_on_estimated_page" if page == estimated_page else "not_found_on_neighbor_page",
                elapsed_ms,
            )
        return NomusProposalLocateResult([], endpoint, None, pages_checked, estimated_page, False)

    def _candidate_pages(self, estimated_page: int):
        yield estimated_page
        for offset in range(1, self.neighbor_limit + 1):
            previous = estimated_page - offset
            if previous >= 1:
                yield previous
            yield estimated_page + offset

    def candidate_pages(self, estimated_page: int) -> tuple[int, ...]:
        return tuple(self._candidate_pages(estimated_page))

    def _fallback_scan(
        self,
        requested_identifier: str,
        endpoint: str,
        *,
        reason: str,
        progress_callback: DetailCallback | None = None,
        is_cancelled: CancelCheck | None = None,
    ) -> NomusProposalLocateResult:
        """Bounded compatibility scan from page 1, used only when no numeric estimate is possible.

        This is an explicit exception path (unparsable identifier or an unreadable
        reference page), not the default search strategy.
        """

        log.info("nomus.locator fallback_scan reason=%s endpoint=%s max_pages=%s", reason, endpoint, self.fallback_max_pages)
        pages_checked = 0
        for page in range(1, self.fallback_max_pages + 1):
            if is_cancelled and is_cancelled():
                return NomusProposalLocateResult([], endpoint, None, pages_checked, None, True)
            _emit(progress_callback, f"Consultando pagina {page} (busca de compatibilidade).")
            records = self.fetch_page(endpoint, page)
            pages_checked += 1
            matches = self.find_in_page(records, requested_identifier)
            if matches:
                return NomusProposalLocateResult(matches, endpoint, page, pages_checked, None, True)
            if len(records) < self.page_size:
                break
        return NomusProposalLocateResult([], endpoint, None, pages_checked, None, True)


def _emit(callback: DetailCallback | None, detail: str) -> None:
    if callback is not None:
        callback(detail)
