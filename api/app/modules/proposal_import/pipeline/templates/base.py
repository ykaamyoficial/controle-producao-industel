from __future__ import annotations

from abc import ABC, abstractmethod

from ..pymupdf_extractor import PdfExtractionContext
from .models import TemplateExtractionResult, TemplateMarker, TemplateMatchResult, TemplateTableDefinition


class PdfTemplate(ABC):
    template_id: str
    name: str
    version: str
    priority: int
    required_markers: tuple[TemplateMarker, ...]
    optional_markers: tuple[TemplateMarker, ...]
    table_definition: TemplateTableDefinition | None = None

    @abstractmethod
    def evaluate(self, context: PdfExtractionContext) -> TemplateMatchResult:
        raise NotImplementedError

    @abstractmethod
    def extract_header(self, context: PdfExtractionContext) -> TemplateExtractionResult:
        raise NotImplementedError
