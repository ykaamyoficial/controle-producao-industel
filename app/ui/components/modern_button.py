from __future__ import annotations

from app.ui.components.app_icon_button import AppIconButton
from app.ui.icons import IconSize


class ModernButton(AppIconButton):
    def __init__(self, text: str = "", icon_name: str | None = None, accent: bool = False, parent=None):
        super().__init__(
            icon_name,
            text,
            color="#ffffff" if accent else "#2563eb",
            size=IconSize.MD,
            accent=accent,
            parent=parent,
        )
        self.setMinimumHeight(34)
        if text:
            icon_space = 28 if icon_name else 0
            self.setMinimumWidth(max(82, self.fontMetrics().horizontalAdvance(text) + icon_space + 30))
