from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Callable, Iterable

from app.services.app_logging import get_logger
from app.services.nomus_batch_import import CancellationToken
from app.services.nomus_import_metrics import NomusImportMetricsCollector, NomusImportMetricsSnapshot


log = get_logger("nomus_batch_persistence")

DuplicateChecker = Callable[[str], bool]
PersistenceEventCallback = Callable[["NomusPersistenceEvent"], None]

_FINANCIAL_KEYS = {
    "amount",
    "discount",
    "financial",
    "margin",
    "paymentcondition",
    "price",
    "subtotal",
    "totalamount",
    "totalprice",
    "unitprice",
    "unitvalue",
    "valoracrescimo",
    "valordesconto",
    "valorparcela",
    "valortotal",
    "valortotalfrete",
    "valortotalprodutos",
    "valorunitario",
}


class NomusPreparedProposalValidationError(ValueError):
    def __init__(self, message: str, *, code: str = "VALIDATION_ERROR"):
        super().__init__(message)
        self.code = code


class NomusPersistenceStatus(str, Enum):
    WAITING = "WAITING"
    VALIDATING = "VALIDATING"
    PERSISTING = "PERSISTING"
    SAVED = "SAVED"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class NomusPersistenceEventType(str, Enum):
    BATCH_STARTED = "batch_started"
    PROPOSAL_STATE_CHANGED = "proposal_state_changed"
    BATCH_PROGRESS = "batch_progress"
    PROPOSAL_FINISHED = "proposal_finished"
    BATCH_FINISHED = "batch_finished"
    BATCH_CANCELLED = "batch_cancelled"


@dataclass(frozen=True)
class PreparedProposalWrite:
    proposal_number: str
    data: dict[str, Any]
    import_metadata: dict[str, Any]
    warnings: tuple[str, ...] = ()


@dataclass
class NomusProposalPersistenceResult:
    proposal_number: str
    status: NomusPersistenceStatus
    success: bool = False
    created_id: int | None = None
    warnings: tuple[str, ...] = ()
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class NomusBatchPersistenceResult:
    results: list[NomusProposalPersistenceResult]
    selected_count: int
    batch_id: str
    elapsed_ms: int = 0
    cancelled: bool = False
    persistence_ms: float = 0.0
    proposals_persisted: int = 0
    persistence_failed: int = 0
    cancelled_count: int = 0
    telemetry: NomusImportMetricsSnapshot | None = field(default=None, repr=False)

    def counts_by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.results:
            counts[result.status.value] = counts.get(result.status.value, 0) + 1
        return counts

    @property
    def failed_results(self) -> list[NomusProposalPersistenceResult]:
        return [result for result in self.results if result.status == NomusPersistenceStatus.FAILED]


@dataclass(frozen=True)
class NomusPersistenceEvent:
    event_type: NomusPersistenceEventType
    batch_id: str
    proposal_number: str | None = None
    status: NomusPersistenceStatus | None = None
    message: str = ""
    completed: int = 0
    total: int = 0
    result: NomusProposalPersistenceResult | None = None
    summary: dict[str, int] = field(default_factory=dict)


class ProposalImportPersistenceService:
    """Validate and persist prepared Nomus proposals through the official service."""

    def __init__(self, storage: Any, *, duplicate_checker: DuplicateChecker | None = None):
        self.storage = storage
        self.duplicate_checker = duplicate_checker
        self._in_flight: set[str] = set()
        self._lock = threading.RLock()

    def validate_prepared_proposal(
        self,
        prepared_result: Any,
        *,
        batch_id: str | None = None,
    ) -> PreparedProposalWrite:
        raw = _as_dict(prepared_result)
        _reject_financial_content(raw)

        proposal = _value(prepared_result, "proposal")
        proposal_number = str(_value(proposal, "proposal_number") or "").strip().upper()
        customer = str(_value(proposal, "client") or "").strip()
        proposal_date = _date_value(_value(proposal, "proposal_date"))
        items = list(_value(prepared_result, "items") or [])

        missing: list[str] = []
        if not proposal_number:
            missing.append("Proposta")
        if not customer:
            missing.append("Cliente")
        if proposal_date is None:
            missing.append("Data da proposta")
        if not items:
            missing.append("Itens")
        if missing:
            raise NomusPreparedProposalValidationError(
                f"Dados obrigatorios ausentes: {', '.join(missing)}.",
                code="REQUIRED_FIELDS_MISSING",
            )

        item_payloads: list[dict[str, Any]] = []
        item_numbers: set[str] = set()
        for index, item in enumerate(items):
            item_number = str(_value(item, "item_number") or index + 1).strip()
            description = str(_value(item, "description") or "").strip()
            quantity = _positive_decimal(_value(item, "quantity"), f"Quantidade do item {item_number}")
            if not description:
                raise NomusPreparedProposalValidationError(
                    f"Descricao obrigatoria ausente no item {item_number}.",
                    code="ITEM_DESCRIPTION_MISSING",
                )
            if item_number in item_numbers:
                raise NomusPreparedProposalValidationError(
                    f"Numero de item duplicado: {item_number}.",
                    code="DUPLICATE_ITEM_NUMBER",
                )
            item_numbers.add(item_number)
            weight = _optional_positive_decimal(_value(item, "unit_weight"))
            item_payloads.append(
                {
                    "numero_item": item_number,
                    "codigo_produto": str(_value(item, "product_code") or "").strip(),
                    "descricao": description,
                    "quantidade": _decimal_text(quantity),
                    "peso": _decimal_text(weight) if weight is not None else "",
                    "produzir_internamente": "indefinido",
                    "motivo_nao_produzir": "",
                    "precisa_galvanizacao": "indefinido",
                    "observacao_fluxo_item": "",
                }
            )

        warnings = tuple(
            str(_value(warning, "message") or "").strip()
            for warning in list(_value(prepared_result, "warnings") or [])
            if str(_value(warning, "message") or "").strip()
        )
        deadline = _deadline_date(
            proposal_date,
            _value(proposal, "deadline_days"),
            _value(proposal, "deadline_raw"),
        )
        data = {
            "proposta": proposal_number,
            "cliente": customer,
            "obra_site": str(_value(proposal, "site") or "").strip(),
            "data_entrada": proposal_date.isoformat(),
            "prazo_entrega": deadline.isoformat() if deadline else "",
            "pedido_compra": str(_value(proposal, "purchase_order") or "").strip(),
            "lote": str(_value(proposal, "lot") or "").strip(),
            "observacoes_gerais": str(_value(proposal, "operational_notes") or "").strip(),
            "itens": item_payloads,
            "_import_source": "NOMUS_API",
        }
        metadata = _build_import_metadata(prepared_result, batch_id=batch_id)
        _reject_financial_content(data)
        _reject_financial_content(metadata)
        return PreparedProposalWrite(proposal_number, data, metadata, warnings)

    def check_duplicate(self, proposal_number: str) -> bool:
        if self.duplicate_checker is not None:
            return bool(self.duplicate_checker(proposal_number))
        checker = getattr(self.storage, "proposal_exists", None)
        if callable(checker):
            return bool(checker(proposal_number))
        official = getattr(self.storage, "official_proposal_storage", None)
        checker = getattr(official, "proposal_exists", None)
        return bool(checker(proposal_number)) if callable(checker) else False

    def persist_one(self, prepared_result: Any, *, batch_id: str | None = None) -> NomusProposalPersistenceResult:
        try:
            prepared = self.validate_prepared_proposal(prepared_result, batch_id=batch_id)
        except Exception as exc:
            return _failure_from_exception(_proposal_number_from_result(prepared_result), exc)

        proposal_number = prepared.proposal_number
        with self._lock:
            if proposal_number in self._in_flight:
                return NomusProposalPersistenceResult(
                    proposal_number,
                    NomusPersistenceStatus.FAILED,
                    error_code="WRITE_IN_PROGRESS",
                    error_message="Esta proposta ja esta sendo gravada.",
                )
            self._in_flight.add(proposal_number)
        try:
            if self.check_duplicate(proposal_number):
                return NomusProposalPersistenceResult(
                    proposal_number,
                    NomusPersistenceStatus.ALREADY_EXISTS,
                    warnings=prepared.warnings,
                    error_code="PROPOSAL_NUMBER_ALREADY_EXISTS",
                    error_message="Proposta ja cadastrada durante o processo.",
                )
            created_id = self.storage.save_process(prepared.data, None, prepared.import_metadata)
            return NomusProposalPersistenceResult(
                proposal_number,
                NomusPersistenceStatus.SAVED,
                success=True,
                created_id=int(created_id) if created_id is not None else None,
                warnings=prepared.warnings,
            )
        except Exception as exc:
            if _is_duplicate_error(exc):
                return NomusProposalPersistenceResult(
                    proposal_number,
                    NomusPersistenceStatus.ALREADY_EXISTS,
                    warnings=prepared.warnings,
                    error_code="PROPOSAL_NUMBER_ALREADY_EXISTS",
                    error_message="Proposta ja cadastrada durante o processo.",
                )
            failure = _failure_from_exception(proposal_number, exc, warnings=prepared.warnings)
            log.error(
                "nomus.persistence failed proposal=%s error_code=%s",
                proposal_number,
                failure.error_code,
            )
            return failure
        finally:
            with self._lock:
                self._in_flight.discard(proposal_number)

    def persist_batch(
        self,
        prepared_results: Iterable[Any],
        *,
        cancellation_token: CancellationToken | None = None,
        event_callback: PersistenceEventCallback | None = None,
        batch_id: str | None = None,
    ) -> NomusBatchPersistenceResult:
        batch_id = batch_id or uuid.uuid4().hex[:12]
        token = cancellation_token or CancellationToken()
        selected = list(prepared_results)
        total = len(selected)
        collector = NomusImportMetricsCollector(batch_id, proposal_count=total)
        results: list[NomusProposalPersistenceResult] = []
        self._emit(event_callback, NomusPersistenceEvent(NomusPersistenceEventType.BATCH_STARTED, batch_id, total=total))

        with collector.stage("persistence"):
            for index, prepared_result in enumerate(selected):
                proposal_number = _proposal_number_from_result(prepared_result)
                if token.is_cancelled():
                    for remaining in selected[index:]:
                        cancelled = NomusProposalPersistenceResult(
                            _proposal_number_from_result(remaining),
                            NomusPersistenceStatus.CANCELLED,
                            error_code="CANCELLED",
                            error_message="Nao processada por cancelamento.",
                        )
                        results.append(cancelled)
                        self._emit_result(event_callback, batch_id, cancelled, len(results), total)
                    break

                self._emit_state(event_callback, batch_id, proposal_number, NomusPersistenceStatus.VALIDATING, "Validando dados operacionais.")
                try:
                    validated = self.validate_prepared_proposal(prepared_result, batch_id=batch_id)
                    proposal_number = validated.proposal_number
                except Exception as exc:
                    failure = _failure_from_exception(proposal_number, exc)
                    results.append(failure)
                    self._emit_result(event_callback, batch_id, failure, len(results), total)
                    continue

                self._emit_state(event_callback, batch_id, proposal_number, NomusPersistenceStatus.PERSISTING, "Gravando pela API oficial.")
                result = self.persist_one(prepared_result, batch_id=batch_id)
                results.append(result)
                self._emit_result(event_callback, batch_id, result, len(results), total)

        cancelled = token.is_cancelled()
        status_counts: dict[str, int] = {}
        for result in results:
            status_counts[result.status.value] = status_counts.get(result.status.value, 0) + 1
        collector.set_persistence_counts(status_counts)
        telemetry = collector.finish()
        batch_result = NomusBatchPersistenceResult(
            results=results,
            selected_count=total,
            batch_id=batch_id,
            elapsed_ms=int(round(telemetry.total_ms)),
            cancelled=cancelled,
            persistence_ms=telemetry.persistence_ms,
            proposals_persisted=telemetry.proposals_persisted,
            persistence_failed=telemetry.persistence_failed,
            cancelled_count=telemetry.cancelled,
            telemetry=telemetry,
        )
        log.info(
            "nomus.persistence complete batch_id=%s selected=%s persisted=%s already_exists=%s failed=%s cancelled=%s persistence_ms=%s",
            batch_id,
            total,
            telemetry.proposals_persisted,
            status_counts.get(NomusPersistenceStatus.ALREADY_EXISTS.value, 0),
            telemetry.persistence_failed,
            telemetry.cancelled,
            telemetry.persistence_ms,
        )
        final_type = NomusPersistenceEventType.BATCH_CANCELLED if cancelled else NomusPersistenceEventType.BATCH_FINISHED
        self._emit(
            event_callback,
            NomusPersistenceEvent(
                final_type,
                batch_id,
                completed=len(results),
                total=total,
                summary=batch_result.counts_by_status(),
            ),
        )
        return batch_result

    @staticmethod
    def _emit(callback: PersistenceEventCallback | None, event: NomusPersistenceEvent) -> None:
        if callback is None:
            return
        try:
            callback(event)
        except Exception:
            log.exception("nomus.persistence event callback failed type=%s", event.event_type.value)

    def _emit_state(
        self,
        callback: PersistenceEventCallback | None,
        batch_id: str,
        proposal_number: str,
        status: NomusPersistenceStatus,
        message: str,
    ) -> None:
        self._emit(
            callback,
            NomusPersistenceEvent(
                NomusPersistenceEventType.PROPOSAL_STATE_CHANGED,
                batch_id,
                proposal_number=proposal_number,
                status=status,
                message=message,
            ),
        )

    def _emit_result(
        self,
        callback: PersistenceEventCallback | None,
        batch_id: str,
        result: NomusProposalPersistenceResult,
        completed: int,
        total: int,
    ) -> None:
        message = result.error_message or ("Proposta gravada." if result.success else "Processamento concluido.")
        self._emit_state(callback, batch_id, result.proposal_number, result.status, message)
        self._emit(
            callback,
            NomusPersistenceEvent(
                NomusPersistenceEventType.PROPOSAL_FINISHED,
                batch_id,
                proposal_number=result.proposal_number,
                status=result.status,
                message=message,
                completed=completed,
                total=total,
                result=result,
            ),
        )
        self._emit(
            callback,
            NomusPersistenceEvent(
                NomusPersistenceEventType.BATCH_PROGRESS,
                batch_id,
                completed=completed,
                total=total,
            ),
        )


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        converted = converter()
        return converted if isinstance(converted, dict) else {}
    return {}


def _value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _reject_financial_content(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = _normalized_key(key)
            if normalized in _FINANCIAL_KEYS:
                raise NomusPreparedProposalValidationError(
                    f"Campo financeiro bloqueado: {path}.{key}.",
                    code="FINANCIAL_FIELD_BLOCKED",
                )
            _reject_financial_content(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_financial_content(item, path=f"{path}[{index}]")


def _date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()[:10]
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _deadline_date(proposal_date: date, days: Any, raw: Any) -> date | None:
    try:
        if days not in (None, "") and int(days) >= 0:
            return proposal_date + timedelta(days=int(days))
    except (TypeError, ValueError):
        pass
    direct = _date_value(raw)
    if direct is not None:
        return direct
    match = re.fullmatch(r"\s*(\d+)\s*DIAS?\s*", str(raw or ""), flags=re.IGNORECASE)
    return proposal_date + timedelta(days=int(match.group(1))) if match else None


def _positive_decimal(value: Any, label: str) -> Decimal:
    try:
        parsed = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise NomusPreparedProposalValidationError(
            f"{label} deve ser numerica.",
            code="INVALID_ITEM_QUANTITY",
        ) from exc
    if parsed <= 0:
        raise NomusPreparedProposalValidationError(
            f"{label} deve ser maior que zero.",
            code="INVALID_ITEM_QUANTITY",
        )
    return parsed


def _optional_positive_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _build_import_metadata(prepared_result: Any, *, batch_id: str | None) -> dict[str, Any]:
    metadata = _value(prepared_result, "metadata")
    warnings = list(_value(prepared_result, "warnings") or [])
    safe = {
        "origem": "NOMUS_API",
        "batch_id": str(batch_id or "")[:64] or None,
        "extraction_method": str(_value(metadata, "extraction_method") or "nomus_api")[:80],
        "template_id": str(_value(metadata, "template_id") or "")[:80] or None,
        "parser_version": str(_value(metadata, "parser_version") or "")[:80] or None,
        "requires_human_review": bool(_value(metadata, "requires_human_review")),
        "warning_codes": [
            str(_value(warning, "code") or "")[:80]
            for warning in warnings
            if str(_value(warning, "code") or "").strip()
        ][:50],
    }
    return {key: value for key, value in safe.items() if value not in (None, "", [])}


def _proposal_number_from_result(prepared_result: Any) -> str:
    proposal = _value(prepared_result, "proposal")
    return str(_value(proposal, "proposal_number") or "").strip().upper() or "-"


def _exception_chain(exc: Exception):
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _is_duplicate_error(exc: Exception) -> bool:
    for current in _exception_chain(exc):
        code = str(getattr(current, "error_code", None) or getattr(current, "code", None) or "").upper()
        message = str(current).lower()
        if code == "PROPOSAL_NUMBER_ALREADY_EXISTS":
            return True
        if "ja existe" in message and "proposta" in message:
            return True
        if "already exists" in message and "proposal" in message:
            return True
    return False


def _failure_from_exception(
    proposal_number: str,
    exc: Exception,
    *,
    warnings: tuple[str, ...] = (),
) -> NomusProposalPersistenceResult:
    code = str(
        getattr(exc, "code", None)
        or getattr(exc, "error_code", None)
        or exc.__class__.__name__.upper()
    )
    return NomusProposalPersistenceResult(
        proposal_number,
        NomusPersistenceStatus.FAILED,
        warnings=warnings,
        error_code=code,
        error_message=str(exc).strip() or "Nao foi possivel gravar a proposta.",
    )
