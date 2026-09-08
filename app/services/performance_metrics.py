"""Instrumentacao leve de desempenho do Desktop.

Esta camada mede operacoes sem guardar dados de negocio. O mesmo
``operation_id`` acompanha o worker da interface e as requisicoes HTTP
executadas dentro dele, permitindo separar tempo de UI de tempo da API.
"""

from __future__ import annotations

import contextvars
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from app.services.app_logging import get_logger


SLOW_OPERATION_THRESHOLD_MS = 300
_scope_var: contextvars.ContextVar["PerformanceScope | None"] = contextvars.ContextVar(
    "controle_producao_performance_scope", default=None
)
log = get_logger("performance")
_samples_lock = threading.Lock()
_samples: deque[dict[str, object]] = deque(maxlen=5000)


@dataclass(frozen=True)
class PerformanceScope:
    operation_id: str
    operation: str
    screen: str
    action: str
    execution_thread: str


def current_scope() -> PerformanceScope | None:
    return _scope_var.get()


def _thread_kind() -> str:
    return "ui" if threading.current_thread() is threading.main_thread() else "background"


@contextmanager
def measure_operation(
    operation: str,
    *,
    screen: str = "unknown",
    action: str = "unknown",
    execution_thread: str | None = None,
) -> Iterator[PerformanceScope]:
    """Mede uma operacao e disponibiliza seu contexto para chamadas HTTP."""

    scope = PerformanceScope(
        operation_id=uuid.uuid4().hex,
        operation=str(operation or "unknown"),
        screen=str(screen or "unknown"),
        action=str(action or "unknown"),
        execution_thread=execution_thread or _thread_kind(),
    )
    token = _scope_var.set(scope)
    started = time.perf_counter()
    log.info(
        "performance_operation_started | operation_id=%s | operation=%s | screen=%s | action=%s | execution_thread=%s",
        scope.operation_id, scope.operation, scope.screen, scope.action, scope.execution_thread,
    )
    try:
        yield scope
    finally:
        duration_ms = int((time.perf_counter() - started) * 1000)
        level = log.warning if duration_ms >= SLOW_OPERATION_THRESHOLD_MS else log.info
        level(
            "performance_operation_finished | operation_id=%s | operation=%s | screen=%s | action=%s | execution_thread=%s | duration_ms=%s | slow=%s",
            scope.operation_id, scope.operation, scope.screen, scope.action,
            scope.execution_thread, duration_ms, duration_ms >= SLOW_OPERATION_THRESHOLD_MS,
        )
        with _samples_lock:
            _samples.append({
                "operation_id": scope.operation_id,
                "operation": scope.operation,
                "screen": scope.screen,
                "action": scope.action,
                "execution_thread": scope.execution_thread,
                "duration_ms": duration_ms,
                "slow": duration_ms >= SLOW_OPERATION_THRESHOLD_MS,
            })
        _scope_var.reset(token)


def request_context() -> dict[str, str]:
    scope = current_scope()
    if scope is None:
        return {}
    return {
        "operation_id": scope.operation_id,
        "operation": scope.operation,
        "screen": scope.screen,
        "action": scope.action,
        "execution_thread": scope.execution_thread,
    }


def performance_snapshot(*, operation: str | None = None, screen: str | None = None) -> dict[str, object]:
    """Agrega as operações concluídas para a auditoria de desempenho."""
    with _samples_lock:
        rows = list(_samples)
    if operation:
        rows = [row for row in rows if row["operation"] == operation]
    if screen:
        rows = [row for row in rows if row["screen"] == screen]
    values = sorted(int(row["duration_ms"]) for row in rows)
    if not values:
        return {"count": 0, "p50_ms": None, "p95_ms": None, "max_ms": None, "slow_count": 0}

    def percentile(percent: float) -> int:
        index = max(0, min(len(values) - 1, int((len(values) - 1) * percent)))
        return values[index]

    return {
        "count": len(values),
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "max_ms": values[-1],
        "slow_count": sum(1 for row in rows if row["slow"]),
    }


def clear_performance_samples() -> None:
    with _samples_lock:
        _samples.clear()
