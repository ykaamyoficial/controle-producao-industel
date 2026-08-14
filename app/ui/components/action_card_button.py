from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout

from app.ui.icons import AppIcons, make_icon
from app.ui.theme_tokens import with_alpha

ACTION_CARD_TYPES = ("primary", "secondary", "warning", "destructive", "administrative")

_ICON_BOX = 46
_ICON_SIZE = 28
_CHEVRON_BOX = 20
_CHEVRON_SIZE = 15


class ActionCardButton(QPushButton):
    """Clickable action card: icon chip + title + short description + chevron, with a
    visual hierarchy (primary / secondary / warning / administrative) driven entirely by
    the active theme palette. Reused for every action of the "Acoes da proposta" grid so
    each action gets consistent states (normal, hover, pressed, focus, disabled) without
    duplicating QSS.

    Layout is a single row (icon chip | title+description | chevron); the icon chip is a
    plain QLabel sized/styled as its own "container" rather than a nested widget - one
    widget already gives a centered icon over a colored, rounded background.
    """

    def __init__(
        self,
        title: str,
        description: str,
        icon: str | None,
        action_type: str,
        palette: dict,
        parent=None,
    ):
        super().__init__(parent)
        action_type = action_type if action_type in ACTION_CARD_TYPES else "secondary"
        self.setObjectName("ActionCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(96 if description else 64)

        variant = self._variant(action_type, palette)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        if icon:
            icon_label = QLabel()
            icon_label.setObjectName("ActionCardIconBox")
            icon_label.setFixedSize(_ICON_BOX, _ICON_BOX)
            icon_label.setAlignment(Qt.AlignCenter)
            icon_label.setPixmap(make_icon(icon, variant["icon_color"], _ICON_SIZE).pixmap(_ICON_SIZE, _ICON_SIZE))
            icon_label.setAttribute(Qt.WA_TransparentForMouseEvents)
            layout.addWidget(icon_label, 0, Qt.AlignVCenter)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)

        title_label = QLabel(title)
        title_label.setObjectName("ActionCardTitle")
        title_label.setWordWrap(True)
        title_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        text_layout.addWidget(title_label)

        if description:
            description_label = QLabel(description)
            description_label.setObjectName("ActionCardDescription")
            description_label.setWordWrap(True)
            description_label.setAttribute(Qt.WA_TransparentForMouseEvents)
            text_layout.addWidget(description_label)

        layout.addLayout(text_layout, 1)
        layout.setAlignment(text_layout, Qt.AlignVCenter)

        chevron_label = QLabel()
        chevron_label.setObjectName("ActionCardChevron")
        chevron_label.setFixedSize(_CHEVRON_BOX, _CHEVRON_BOX)
        chevron_label.setAlignment(Qt.AlignCenter)
        chevron_label.setPixmap(
            make_icon(AppIcons.NEXT, variant["chevron_color"], _CHEVRON_SIZE).pixmap(_CHEVRON_SIZE, _CHEVRON_SIZE)
        )
        chevron_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(chevron_label, 0, Qt.AlignVCenter)

        self.setStyleSheet(self._card_stylesheet(variant))

    @staticmethod
    def _variant(action_type: str, palette: dict) -> dict:
        """Every action_type maps to the same fixed set of keys, sourced only from the
        active theme palette (plus `with_alpha` tints) - no ad-hoc hex codes."""
        border = palette["border"]
        surface = palette["surface"]
        surface_alt = palette["surface_alt"]
        accent = palette["accent"]
        accent_hover = palette["accent_hover"]
        accent_text = palette["accent_text"]
        warning = palette["warning"]
        muted = palette["muted"]
        disabled = palette["disabled"]
        text = palette["text"]

        if action_type == "primary":
            return {
                "bg": with_alpha(accent, 18), "bg_hover": with_alpha(accent, 30), "bg_pressed": with_alpha(accent, 42),
                "border": with_alpha(accent, 150), "border_hover": accent, "border_pressed": accent_hover,
                "focus_border": accent_hover,
                "icon_bg": accent, "icon_color": accent_text,
                "title": accent, "title_weight": 700, "description": muted,
                "chevron_color": accent,
                "disabled_title": muted, "disabled_description": disabled,
            }
        if action_type == "warning":
            return {
                "bg": with_alpha(warning, 16), "bg_hover": with_alpha(warning, 28), "bg_pressed": with_alpha(warning, 40),
                "border": with_alpha(warning, 130), "border_hover": warning, "border_pressed": warning,
                "focus_border": warning,
                "icon_bg": with_alpha(warning, 32), "icon_color": warning,
                "title": text, "title_weight": 600, "description": muted,
                "chevron_color": warning,
                "disabled_title": muted, "disabled_description": disabled,
            }
        if action_type == "destructive":
            danger = palette["danger"]
            return {
                "bg": with_alpha(danger, 16), "bg_hover": with_alpha(danger, 28), "bg_pressed": with_alpha(danger, 40),
                "border": with_alpha(danger, 140), "border_hover": danger, "border_pressed": danger,
                "focus_border": danger,
                "icon_bg": with_alpha(danger, 32), "icon_color": danger,
                "title": danger, "title_weight": 700, "description": muted,
                "chevron_color": danger,
                "disabled_title": muted, "disabled_description": disabled,
            }
        if action_type == "administrative":
            return {
                "bg": "transparent", "bg_hover": surface_alt, "bg_pressed": surface_alt,
                "border": "transparent", "border_hover": border, "border_pressed": border,
                "focus_border": accent,
                "icon_bg": surface_alt, "icon_color": muted,
                "title": muted, "title_weight": 600, "description": muted,
                "chevron_color": muted,
                "disabled_title": muted, "disabled_description": disabled,
            }
        return {
            "bg": surface, "bg_hover": surface_alt, "bg_pressed": with_alpha(border, 90),
            "border": border, "border_hover": with_alpha(muted, 140), "border_pressed": accent,
            "focus_border": accent,
            "icon_bg": surface_alt, "icon_color": text,
            "title": text, "title_weight": 600, "description": muted,
            "chevron_color": muted,
            "disabled_title": muted, "disabled_description": disabled,
        }

    @staticmethod
    def _card_stylesheet(variant: dict) -> str:
        return f"""
        QPushButton#ActionCard {{
            background: {variant['bg']};
            border: 1px solid {variant['border']};
            border-radius: 11px;
            text-align: left;
        }}
        QPushButton#ActionCard:hover {{
            background: {variant['bg_hover']};
            border: 1px solid {variant['border_hover']};
        }}
        QPushButton#ActionCard:pressed {{
            background: {variant['bg_pressed']};
            border: 1px solid {variant['border_pressed']};
        }}
        QPushButton#ActionCard:focus {{
            border: 2px solid {variant['focus_border']};
        }}
        QPushButton#ActionCard QLabel#ActionCardIconBox {{
            background: {variant['icon_bg']};
            border-radius: 10px;
        }}
        QPushButton#ActionCard QLabel#ActionCardTitle {{
            color: {variant['title']};
            font-weight: {variant['title_weight']};
            font-size: 14px;
            background: transparent;
        }}
        QPushButton#ActionCard QLabel#ActionCardDescription {{
            color: {variant['description']};
            font-size: 12px;
            font-weight: 400;
            background: transparent;
        }}
        QPushButton#ActionCard QLabel#ActionCardChevron {{
            background: transparent;
        }}
        QPushButton#ActionCard:disabled QLabel#ActionCardTitle {{
            color: {variant['disabled_title']};
        }}
        QPushButton#ActionCard:disabled QLabel#ActionCardDescription {{
            color: {variant['disabled_description']};
        }}
        """
