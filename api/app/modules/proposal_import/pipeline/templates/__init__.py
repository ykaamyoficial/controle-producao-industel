from __future__ import annotations

from .detector import detect_template
from .models import TemplateDetectionResult, TemplateExtractionResult, TemplateFieldResult
from .registry import default_template_registry

__all__ = [
    "TemplateDetectionResult",
    "TemplateExtractionResult",
    "TemplateFieldResult",
    "default_template_registry",
    "detect_template",
]
