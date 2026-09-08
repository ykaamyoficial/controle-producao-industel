from __future__ import annotations

import logging
import time
from decimal import Decimal

from ..pymupdf_extractor import PdfExtractionContext
from .models import SCORE_AMBIGUITY_DELTA, SCORE_CANDIDATE, TemplateDetectionResult

logger = logging.getLogger(__name__)


class TemplateDetector:
    def __init__(self, registry):
        self.registry = registry

    def detect(self, context: PdfExtractionContext) -> TemplateDetectionResult:
        start = time.perf_counter()
        templates = self.registry.get_all()
        if not templates:
            return TemplateDetectionResult(
                selected_template_id=None,
                selected_template_version=None,
                confidence=Decimal("0.00"),
                ambiguous=False,
                candidates=[],
                reasons=["nenhum template registrado"],
                elapsed_seconds=round(time.perf_counter() - start, 6),
            )
        candidates = [template.evaluate(context) for template in templates]
        candidates = sorted(candidates, key=lambda candidate: (candidate.score, candidate.matched), reverse=True)
        best = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None
        ambiguous = (
            second is not None
            and best.score >= SCORE_CANDIDATE
            and second.score >= SCORE_CANDIDATE
            and abs(best.score - second.score) < SCORE_AMBIGUITY_DELTA
        )
        selected_id = best.template_id if best.score >= SCORE_CANDIDATE and not ambiguous else None
        selected_version = best.template_version if selected_id else None
        reasons = [f"{candidate.template_id}: score {candidate.score}" for candidate in candidates]
        if ambiguous:
            reasons.append("deteccao ambigua; fallback deve ser preservado")
        elif not selected_id:
            reasons.append("nenhum template atingiu score minimo")
        else:
            reasons.append(f"template selecionado: {selected_id}")
        logger.info("Deteccao de template concluida: %s", "; ".join(reasons))
        return TemplateDetectionResult(
            selected_template_id=selected_id,
            selected_template_version=selected_version,
            confidence=best.score,
            ambiguous=ambiguous,
            candidates=candidates,
            reasons=reasons,
            elapsed_seconds=round(time.perf_counter() - start, 6),
        )


def detect_template(context: PdfExtractionContext) -> TemplateDetectionResult:
    from .registry import default_template_registry

    return default_template_registry().detect(context)
