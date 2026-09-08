from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Callable, TypeVar

from .nomus_rule_parser import FORBIDDEN_FINANCIAL_TERMS


class ImportStage(str, Enum):
    FILE_VALIDATION = "file_validation"
    PDF_STRUCTURE = "pdf_structure"
    TEXT_EXTRACTION = "text_extraction"
    TEMPLATE_DETECTION = "template_detection"
    HEADER_EXTRACTION = "header_extraction"
    TEXT_RULE_PARSER = "text_rule_parser"
    TABLE_EXTRACTION = "table_extraction"
    MERGE = "merge"
    NORMALIZATION = "normalization"
    VALIDATION = "validation"
    CONFIDENCE = "confidence"
    COMPATIBILITY = "compatibility"


class ImportStageStatus(str, Enum):
    SUCCESS = "success"
    WARNING = "warning"
    FAILED = "failed"
    SKIPPED = "skipped"


_T = TypeVar("_T")
_MONEY_RE = re.compile(r"R\$\s*\d[\d.]*,\d{2}|\b\d{1,3}(?:\.\d{3})*,\d{2}\b")
_WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s;]+")


@dataclass(frozen=True)
class ImportStageResult:
    stage: str
    status: str
    method: str | None = None
    duration_ms: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    fallback_used: bool = False

    def to_safe_dict(self) -> dict[str, Any]:
        return sanitize_mapping(
            {
                "stage": self.stage,
                "status": self.status,
                "method": self.method,
                "duration_ms": self.duration_ms,
                "warnings": self.warnings,
                "errors": self.errors,
                "metadata": self.metadata,
                "fallback_used": self.fallback_used,
            }
        )


@dataclass
class ImportPipelineDiagnostics:
    stages: list[ImportStageResult] = field(default_factory=list)
    selected_template: str | None = None
    selected_header_source: str | None = None
    selected_table_source: str | None = None
    fallback_used: bool = False
    fallback_reasons: list[str] = field(default_factory=list)
    total_duration_ms: int = 0

    def add(
        self,
        stage: ImportStage,
        *,
        status: ImportStageStatus | str,
        method: str | None = None,
        duration_ms: int = 0,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        fallback_used: bool = False,
    ) -> None:
        self.stages.append(
            ImportStageResult(
                stage=stage.value,
                status=status.value if isinstance(status, ImportStageStatus) else str(status),
                method=method,
                duration_ms=duration_ms,
                warnings=sanitize_messages(warnings or []),
                errors=sanitize_messages(errors or []),
                metadata=sanitize_mapping(metadata or {}),
                fallback_used=fallback_used,
            )
        )

    def to_safe_dict(self) -> dict[str, Any]:
        return sanitize_mapping(
            {
                "stages": [stage.to_safe_dict() for stage in self.stages],
                "selected_template": self.selected_template,
                "selected_header_source": self.selected_header_source,
                "selected_table_source": self.selected_table_source,
                "fallback_used": self.fallback_used,
                "fallback_reasons": self.fallback_reasons,
                "total_duration_ms": self.total_duration_ms,
            }
        )

    def build_diagnostic_summary(self) -> dict[str, Any]:
        conflict_stages = [
            stage.stage
            for stage in self.stages
            if any("conflito" in warning.lower() or "conflict" in warning.lower() for warning in stage.warnings)
        ]
        return sanitize_mapping(
            {
                "template": self.selected_template,
                "header_source": self.selected_header_source,
                "table_source": self.selected_table_source,
                "fallback": self.fallback_used,
                "fallback_reasons": self.fallback_reasons,
                "conflict_stages": conflict_stages,
                "warnings": sum((stage.warnings for stage in self.stages), []),
                "errors": sum((stage.errors for stage in self.stages), []),
                "durations_ms": {stage.stage: stage.duration_ms for stage in self.stages},
                "total_duration_ms": self.total_duration_ms,
            }
        )


def timed_call(func: Callable[[], _T]) -> tuple[_T, int]:
    start = time.perf_counter()
    value = func()
    return value, int(round((time.perf_counter() - start) * 1000))


def now_ms_since(start: float) -> int:
    return int(round((time.perf_counter() - start) * 1000))


def sanitize_messages(messages: list[str]) -> list[str]:
    clean: list[str] = []
    seen: set[str] = set()
    for message in messages:
        sanitized = sanitize_text(str(message))
        if not sanitized or sanitized in seen:
            continue
        seen.add(sanitized)
        clean.append(sanitized)
    return clean


def sanitize_mapping(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Path):
        return value.name
    if isinstance(value, tuple):
        return [sanitize_mapping(item) for item in value]
    if isinstance(value, list):
        return [sanitize_mapping(item) for item in value]
    if isinstance(value, dict):
        return {str(key): sanitize_mapping(item) for key, item in value.items()}
    if hasattr(value, "to_safe_dict"):
        return value.to_safe_dict()
    if hasattr(value, "to_dict"):
        return sanitize_mapping(value.to_dict())
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return sanitize_text(str(value))


def sanitize_text(value: str) -> str:
    sanitized = value or ""
    sanitized = _WINDOWS_PATH_RE.sub(lambda match: Path(match.group(0)).name, sanitized)
    sanitized = _MONEY_RE.sub("[valor removido]", sanitized)
    for term in FORBIDDEN_FINANCIAL_TERMS:
        sanitized = re.sub(re.escape(term), "[termo removido]", sanitized, flags=re.IGNORECASE)
    return " ".join(sanitized.split()).strip()
