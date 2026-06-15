from __future__ import annotations

from app.services.backend_adapter import legacy


def radius(value: int = 10) -> str:
    return f"border-radius: {value}px;"


def app_stylesheet(palette: dict) -> str:
    bg = palette["bg"]
    surface = palette["surface"]
    surface_alt = palette["surface_alt"]
    text = palette["text"]
    muted = palette["muted"]
    border = palette["border"]
    accent = palette["accent"]
    accent_hover = palette["accent_hover"]
    accent_text = palette["accent_text"]
    danger = palette["danger"]

    return f"""
    * {{
        font-family: "Segoe UI", "Arial";
        font-size: 12px;
        color: {text};
    }}
    QMainWindow, QWidget#AppRoot, QDialog {{
        background: {bg};
    }}
    QDialog QWidget {{
        background: {bg};
    }}
    QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{
        background: {bg};
        border: 0;
    }}
    QWidget#DashboardContent {{
        background: {bg};
    }}
    QFrame#Sidebar {{
        background: {surface};
        border-right: 1px solid {border};
    }}
    QLabel#AppTitle {{
        font-size: 12px;
        font-weight: 700;
        color: {text};
    }}
    QLabel#Caption {{
        color: {muted};
        font-size: 11px;
    }}
    QLabel#TopInfoChip, QLabel#TopDatabaseChip {{
        background: {surface_alt};
        color: {muted};
        border: 1px solid {border};
        border-radius: 9px;
        padding: 4px 9px;
        font-size: 10px;
    }}
    QLabel#TopDatabaseChip {{
        color: {text};
    }}
    QPushButton {{
        background: {surface_alt};
        border: 1px solid transparent;
        {radius(10)}
        padding: 7px 12px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: {border};
    }}
    QPushButton:pressed {{
        background: {accent_hover};
        color: {accent_text};
    }}
    QPushButton#AccentButton {{
        background: {accent};
        color: {accent_text};
    }}
    QPushButton#AccentButton:hover {{
        background: {accent_hover};
    }}
    QPushButton#GhostButton {{
        background: transparent;
        border: 1px solid transparent;
    }}
    QPushButton#GhostButton:hover {{
        background: {surface_alt};
    }}
    QPushButton#NavButton {{
        background: transparent;
        border: 1px solid transparent;
        text-align: left;
        padding: 9px 12px;
        {radius(12)}
    }}
    QPushButton#NavButton:hover {{
        background: {surface_alt};
        border-color: {border};
    }}
    QPushButton#NavButton[active="true"] {{
        background: {accent};
        color: {accent_text};
        border-color: {accent};
        font-weight: 700;
    }}
    QPushButton#NavButton[active="true"]:hover {{
        background: {accent_hover};
        border-color: {accent_hover};
    }}
    QFrame#TopBar, QFrame#FilterBar, QFrame#Card, QFrame#KpiCard, QFrame#Panel {{
        background: {surface};
        border: 1px solid {border};
        {radius(16)}
    }}
    QFrame#TopBar {{
        {radius(12)}
    }}
    QFrame#KpiCard:hover, QFrame#Panel:hover {{
        background: {surface_alt};
        border: 1px solid {accent};
    }}
    QFrame#FilterBar {{
        padding: 2px;
    }}
    QLabel#FilterTitle {{
        font-size: 14px;
        font-weight: 800;
        color: {text};
    }}
    QLabel#FieldLabel {{
        font-size: 10px;
        font-weight: 700;
        color: {muted};
    }}
    QLineEdit, QComboBox, QTextEdit, QSpinBox, QDoubleSpinBox {{
        background: {surface};
        border: 1px solid {border};
        {radius(10)}
        padding: 6px 10px;
        selection-background-color: {accent};
        selection-color: {accent_text};
    }}
    QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {accent};
    }}
    QComboBox::drop-down {{
        border: 0;
        width: 24px;
    }}
    QTableView, QTableWidget {{
        background: {surface};
        color: {text};
        alternate-background-color: {surface_alt};
        gridline-color: transparent;
        border: 1px solid {border};
        {radius(14)}
        selection-background-color: {accent};
        selection-color: {accent_text};
        outline: 0;
    }}
    QTableView::viewport, QTableWidget::viewport {{
        background: {surface};
        {radius(12)}
    }}
    QTableView::item, QTableWidget::item {{
        padding: 4px 8px;
        border: 0;
    }}
    QTableView::item:hover, QTableWidget::item:hover {{
        background: {surface_alt};
    }}
    QHeaderView::section {{
        background: {surface_alt};
        color: {text};
        padding: 4px 8px;
        border: 0;
        border-bottom: 1px solid {border};
        font-weight: 700;
    }}
    QTableCornerButton::section {{
        background: {surface_alt};
        border: 0;
        border-bottom: 1px solid {border};
        border-right: 1px solid {border};
        {radius(8)}
    }}
    QScrollBar:vertical, QScrollBar:horizontal {{
        background: transparent;
        border: 0;
        margin: 2px;
    }}
    QScrollBar:vertical {{
        width: 9px;
    }}
    QScrollBar:horizontal {{
        height: 9px;
    }}
    QScrollBar::handle {{
        background: {border};
        {radius(4)}
        min-height: 24px;
        min-width: 24px;
    }}
    QScrollBar::handle:hover {{
        background: {muted};
    }}
    QScrollBar::add-line, QScrollBar::sub-line {{
        background: transparent;
        border: 0;
        width: 0px;
        height: 0px;
    }}
    QScrollBar::add-page, QScrollBar::sub-page {{
        background: transparent;
        border: 0;
    }}
    QMessageBox {{
        background: {surface};
    }}
    QToolTip {{
        background: {surface};
        color: {text};
        border: 1px solid {border};
        border-radius: 7px;
        padding: 5px 8px;
    }}
    QLabel#ErrorText {{
        color: {danger};
        font-weight: 600;
    }}
    """


def area_color(area: str, palette: dict) -> str:
    area = (area or "").strip().upper()
    colors = {
        "CONTROLE GERAL": palette.get("area_control", palette["accent"]),
        "PRODUCAO": palette.get("area_production", palette["success"]),
        "GALVANIZACAO": palette.get("area_galvanization", palette["secondary"]),
        "EXPEDICAO": palette.get("area_expedition", palette["warning"]),
        "ALMOXARIFADO": palette.get("area_stock", palette["muted"]),
    }
    return colors.get(area, palette["accent"])


def status_color(status: str, palette: dict, area: str = "") -> tuple[str, str]:
    status = legacy.normalize_status(status or "")
    dark_theme = _is_dark(palette.get("bg", "#ffffff"))
    if "CANCEL" in status or status in {"PARADO", "PRODUCAO_CANCELADA"}:
        color = palette["danger"]
    elif "PENDENTE" in status or "PARCIAL" in status:
        color = palette["warning"]
    elif "ENTREGUE" in status or status in {
        "FINALIZADO", "RETORNOU_GALVANIZACAO", "SEPARADO", "UNIFICADA_PRINCIPAL",
    }:
        color = palette["success"]
    elif status in {"NAO_LIBERADO", "NAO_INICIADO", "AGUARDANDO_CONFIRMACAO", "NAO_DEFINIDO"}:
        color = palette["muted"]
    elif status in {"EM_CARGA", "ENVIADO_GALVANIZACAO"}:
        color = palette["secondary"]
    else:
        color = area_color(area, palette)
    color = _tone(color, dark_theme)
    return color, _contrast_text(color)


def _contrast_text(hex_color: str) -> str:
    color = hex_color.strip().lstrip("#")
    if len(color) < 6:
        return "#ffffff"
    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b)
    return "#111827" if luminance >= 150 else "#ffffff"


def chart_colors(palette: dict) -> list[str]:
    dark_theme = _is_dark(palette.get("bg", "#ffffff"))
    if dark_theme:
        return [
            "#1597ad",
            "#34d399",
            "#8b5cf6",
            "#f59e0b",
            "#38bdf8",
            "#fb923c",
            "#94a3b8",
            "#22c55e",
        ]
    return [
        "#0e7490",
        "#047857",
        "#6d28d9",
        "#b45309",
        "#006fc9",
        "#c2410c",
        "#64748b",
        "#15803d",
    ]


def _is_dark(hex_color: str) -> bool:
    color = hex_color.strip().lstrip("#")
    if len(color) < 6:
        return False
    r = int(color[0:2], 16)
    g = int(color[2:4], 16)
    b = int(color[4:6], 16)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) < 128


def _tone(color: str, dark_theme: bool) -> str:
    if not dark_theme:
        return color
    overrides = {
        "#facc15": "#eab308",
        "#34d399": "#22c55e",
        "#fb7185": "#f43f5e",
        "#38bdf8": "#22aeea",
        "#7dd3fc": "#38bdf8",
        "#cbd5e1": "#64748b",
    }
    return overrides.get(color.lower(), color)
