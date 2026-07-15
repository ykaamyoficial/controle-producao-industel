from __future__ import annotations

from PySide6.QtGui import QColor


def with_alpha(color: str, alpha: int) -> str:
    value = QColor(color)
    return f"rgba({value.red()}, {value.green()}, {value.blue()}, {max(0, min(alpha, 255))})"


def dashboard_tokens(palette: dict) -> dict[str, str]:
    """Semantic dashboard colors derived exclusively from the active application theme."""
    return {
        **palette,
        "header_start": palette["accent"],
        "header_end": palette["accent_hover"],
        "header_text": palette["accent_text"],
        "header_muted": with_alpha(palette["accent_text"], 205),
        "shadow": with_alpha(palette["text"], 10),
        "track": palette["surface_alt"],
        "hover": with_alpha(palette["accent"], 20),
        "success_soft": with_alpha(palette["success"], 34),
        "warning_soft": with_alpha(palette["warning"], 38),
        "danger_soft": with_alpha(palette["danger"], 34),
        "accent_soft": with_alpha(palette["accent"], 32),
    }


def dashboard_chart_colors(palette: dict) -> list[str]:
    """Chart series sourced from the semantic colors of the active theme."""
    return [
        palette.get("area_control", palette["accent"]),
        palette.get("area_production", palette["success"]),
        palette.get("area_galvanization", palette["secondary"]),
        palette.get("area_expedition", palette["warning"]),
        palette["danger"],
        palette["accent_hover"],
        palette.get("area_stock", palette["muted"]),
    ]
