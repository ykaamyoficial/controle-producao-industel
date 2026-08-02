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
    QAbstractScrollArea {{
        background: {surface};
        border: 1px solid {border};
        {radius(14)}
    }}
    QAbstractScrollArea::viewport {{
        background: {surface};
    }}
    QWidget#DashboardContent {{
        background: {bg};
    }}
    QWidget#FiscalPage, QWidget#FiscalTabPage, QWidget#FiscalTabContent {{
        background: {bg};
    }}
    QFrame#HintBar {{
        background: {surface};
        border: 1px solid {border};
        {radius(14)}
    }}
    QLabel#HintLabel {{
        background: {surface};
        color: {muted};
        border: 1px solid {border};
        {radius(12)}
        padding: 8px 10px;
        font-size: 11px;
    }}
    QTabWidget {{
        background: {bg};
        border: 0;
    }}
    QTabWidget::pane {{
        background: {surface};
        border: 1px solid {border};
        {radius(14)}
        top: -1px;
    }}
    QTabWidget#ModernTabs::pane {{
        background: {surface};
        border: 1px solid {border};
        {radius(14)}
    }}
    QTabBar {{
        background: {bg};
        border: 0;
    }}
    QTabBar::tab {{
        background: {surface_alt};
        color: {muted};
        border: 1px solid {border};
        border-bottom: 0;
        border-top-left-radius: 10px;
        border-top-right-radius: 10px;
        padding: 8px 14px;
        margin-right: 4px;
    }}
    QTabBar::tab:selected {{
        background: {surface};
        color: {text};
        border-color: {border};
        font-weight: 700;
    }}
    QTabBar::tab:hover {{
        background: {surface};
        color: {text};
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
    QLabel#SidebarGroupLabel {{
        color: {muted};
        font-size: 10px;
        font-weight: 800;
        letter-spacing: 0px;
        padding: 10px 4px 2px 4px;
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
        padding: 2px 8px;
        {radius(12)}
    }}
    QPushButton#NavButton[collapsed="true"] {{
        text-align: center;
        padding: 1px 0px;
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
    QPushButton#ThemeToggleButton {{
        background: {surface_alt};
        color: {text};
        border: 1px solid {border};
        text-align: left;
        padding: 3px 8px;
        {radius(12)}
        font-weight: 700;
    }}
    QPushButton#ThemeToggleButton[collapsed="true"] {{
        text-align: center;
        padding: 1px 0px;
    }}
    QPushButton#ThemeToggleButton:hover {{
        background: {accent};
        color: {accent_text};
        border-color: {accent};
    }}
    QPushButton#ThemeToggleButton:pressed {{
        background: {accent_hover};
        color: {accent_text};
    }}
    QFrame#TopBar, QFrame#FilterBar, QFrame#Card, QFrame#KpiCard, QFrame#Panel {{
        background: {surface};
        border: 1px solid {border};
        {radius(16)}
    }}
    QFrame#TopBar QLabel,
    QFrame#FilterBar QLabel,
    QFrame#Card QLabel,
    QFrame#KpiCard QLabel,
    QFrame#Panel QLabel {{
        background: transparent;
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
    QSplitter::handle {{
        background: {border};
        margin: 2px;
    }}
    QSplitter::handle:horizontal {{
        width: 2px;
    }}
    QSplitter::handle:vertical {{
        height: 2px;
    }}
    QSplitter::handle:hover {{
        background: {accent};
    }}
    QSplitter::handle:pressed {{
        background: {accent_hover};
    }}
    QLabel#FilterTitle {{
        font-size: 14px;
        font-weight: 800;
        color: {text};
    }}
    QLabel#FilterSubtitle {{
        font-size: 10px;
        color: {muted};
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
    QLineEdit[validationState="error"], QTableWidget[validationState="error"] {{
        border: 2px solid {danger};
    }}
    QLineEdit[validationState="warning"] {{
        border: 2px solid {palette["warning"]};
    }}
    QLabel#ValidationWarning {{
        color: {palette["warning"]};
        font-size: 10px;
        font-weight: 700;
    }}
    QLabel#ValidationError {{
        color: {danger};
        font-size: 10px;
        font-weight: 700;
    }}
    QLabel#ValidationSuccess {{
        color: {palette["success"]};
        font-size: 11px;
        font-weight: 700;
    }}
    QComboBox::drop-down {{
        border: 0;
        width: 24px;
    }}
    QComboBox QAbstractItemView {{
        background: {surface};
        color: {text};
        border: 1px solid {border};
        selection-background-color: {accent};
        selection-color: {accent_text};
        outline: 0;
    }}
    QMenu {{
        background: {surface};
        color: {text};
        border: 1px solid {border};
        border-radius: 9px;
        padding: 5px;
    }}
    QMenu::item {{
        padding: 7px 18px;
        border-radius: 7px;
    }}
    QMenu::item:selected {{
        background: {accent};
        color: {accent_text};
    }}
    QCheckBox {{
        color: {text};
        spacing: 7px;
    }}
    QCheckBox::indicator {{
        width: 15px;
        height: 15px;
        border: 1px solid {border};
        border-radius: 4px;
        background: {surface};
    }}
    QCheckBox::indicator:checked {{
        background: {accent};
        border-color: {accent};
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
        padding: 3px 8px;
        border: 0;
    }}
    QTableView::item:hover, QTableWidget::item:hover {{
        background: {surface_alt};
    }}
    QHeaderView::section {{
        background: {surface_alt};
        color: {text};
        padding: 3px 8px;
        border: 0;
        border-bottom: 1px solid {border};
        font-weight: 700;
    }}
    QFrame#TableStack {{
        background: transparent;
        border: 0;
    }}
    QWidget#OperationalEmptyState {{
        background: {surface};
        border: 1px solid {border};
        {radius(14)}
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


STATUS_BADGE_COLORS = {
    "claro": {
        "neutral": "#64748B",
        "waiting": "#2563EB",
        "progress": "#EA580C",
        "attention": "#CA8A04",
        "done": "#16A34A",
        "final_done": "#0F766E",
        "danger": "#DC2626",
        "location_production": "#047857",
        "location_galvanization": "#7C3AED",
        "location_expedition": "#C2410C",
        "location_grouped": "#0369A1",
    },
    "escuro": {
        "neutral": "#CBD5E1",
        "waiting": "#60A5FA",
        "progress": "#FB923C",
        "attention": "#FACC15",
        "done": "#4ADE80",
        "final_done": "#2DD4BF",
        "danger": "#FB7185",
        "location_production": "#34D399",
        "location_galvanization": "#A78BFA",
        "location_expedition": "#FB923C",
        "location_grouped": "#38BDF8",
    },
}

STATUS_CATEGORY_BY_STATUS = {
    "NAO_LIBERADO": "neutral",
    "LIBERADO_PRODUCAO": "waiting",
    "CANCELADA": "danger",
    "NAO_INICIADO": "waiting",
    "ITEM_PENDENTE_FABRICACAO": "attention",
    "INICIADO": "progress",
    "PARADO": "danger",
    "FINALIZADO_PARCIAL": "attention",
    "FINALIZADO": "done",
    "AGUARDANDO_ENVIO": "waiting",
    "DISPONIVEL_PARCIAL": "attention",
    "EM_CARGA": "progress",
    "ENVIADO_GALVANIZACAO": "progress",
    "AGUARDANDO_LIBERACAO": "waiting",
    "LIBERADA_PARA_ENVIO": "progress",
    "RETORNO_PARCIAL": "warning",
    "RETORNADA_GALVANIZACAO": "done",
    "RETORNOU_GALVANIZACAO": "done",
    "RETORNOU_PARCIAL": "attention",
    "EM_SEPARACAO": "waiting",
    "AGUARDANDO_SEPARACAO_PARCIAL": "attention",
    "SEPARACAO_INICIADA": "progress",
    "SEPARADO": "done",
    "ENTREGUE_PARCIAL": "attention",
    "ENTREGUE": "final_done",
    "AGUARDANDO_CONFIRMACAO": "waiting",
    "SEM_PARAFUSOS": "danger",
    "ALMOXARIFADO_ENTREGUE": "final_done",
    "ALMOXARIFADO_ENTREGUE_PARCIAL": "attention",
    "FALTA_EMITIR_NOTA_FISCAL": "danger",
    "AGUARDANDO_NF": "waiting",
    "CP_EM_PROCESSAMENTO": "progress",
    "NF_EM_PROCESSAMENTO": "progress",
    "DISPONIVEL_PARA_EMISSAO": "waiting",
    "PENDENCIA_FISCAL_CRITICA": "blocked",
    "NOTA_FISCAL_PARCIAL": "attention",
    "NF_PARCIAL": "attention",
    "NOTA_FISCAL_EMITIDA": "done",
    "NF_EMITIDA": "done",
    "NF_RETIRADA_CLIENTE": "final_done",
    "FISCAL_CANCELADO": "danger",
    "PENDENTE": "attention",
    "PARCIAL": "attention",
    "FATURADO": "done",
    "CANCELADO": "danger",
}

LOCATION_STATUS_CATEGORY_BY_STATUS = {
    "EM_PRODUCAO": "location_production",
    "EM_GALVANIZACAO": "location_galvanization",
    "EM_EXPEDICAO": "location_expedition",
    "UNIFICADA_PRINCIPAL": "location_grouped",
}


def status_color(status: str, palette: dict, area: str = "") -> tuple[str, str]:
    status = legacy.normalize_status(status or "")
    dark_theme = _is_dark(palette.get("bg", "#ffffff"))
    theme_key = "escuro" if dark_theme else "claro"
    colors = STATUS_BADGE_COLORS[theme_key]
    category = (
        LOCATION_STATUS_CATEGORY_BY_STATUS.get(status)
        or STATUS_CATEGORY_BY_STATUS.get(status)
        or "neutral"
    )
    color = colors[category]
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
