from __future__ import annotations

from .base import PdfTemplate
from .models import InvalidTemplateConfigurationError, TemplateDetectionResult


class TemplateRegistry:
    def __init__(self) -> None:
        self._templates: dict[tuple[str, str], PdfTemplate] = {}

    def register(self, template: PdfTemplate) -> None:
        if not template.template_id or not template.version:
            raise InvalidTemplateConfigurationError("Template precisa de id e versao.")
        key = (template.template_id, template.version)
        if key in self._templates:
            raise InvalidTemplateConfigurationError(f"Template duplicado: {template.template_id} {template.version}")
        self._templates[key] = template

    def get_all(self) -> tuple[PdfTemplate, ...]:
        return tuple(sorted(self._templates.values(), key=lambda template: (-template.priority, template.template_id)))

    def get(self, template_id: str, version: str | None = None) -> PdfTemplate | None:
        candidates = [template for template in self._templates.values() if template.template_id == template_id]
        if version is not None:
            return self._templates.get((template_id, version))
        return sorted(candidates, key=lambda template: -template.priority)[0] if candidates else None

    def detect(self, context) -> TemplateDetectionResult:
        from .detector import TemplateDetector

        return TemplateDetector(self).detect(context)


def default_template_registry() -> TemplateRegistry:
    from .nomus_current import NomusCurrentTemplate

    registry = TemplateRegistry()
    registry.register(NomusCurrentTemplate())
    return registry
