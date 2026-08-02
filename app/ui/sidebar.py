from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from app.ui.icons import make_icon


NAV_GROUPS = [
    (
        "PAINEIS",
        [
            ("PAINEL GERAL", "Painel geral", "dashboard"),
            ("DASHBOARD EXECUTIVO", "Dashboard Executivo", "dashboard"),
        ],
    ),
    (
        "OPERACAO",
        [
            ("CHATS", "Chats", "chat"),
            ("CONTROLE GERAL", "Controle Geral", "control"),
            ("PRODUCAO", "Producao", "production"),
            ("GALVANIZACAO", "Galvanizacao", "galvanization"),
            ("EXPEDICAO", "Expedicao", "expedition"),
            ("FISCAL", "Fiscal", "fiscal"),
            ("PARCIAIS", "Parciais", "partial"),
            ("ALMOXARIFADO", "Almoxarifado", "stock"),
        ],
    ),
    (
        "ANALISE",
        [
            ("RELATORIOS OPERACIONAIS", "Relatorios Operacionais", "reports"),
            ("HISTORICO", "Historico", "history"),
        ],
    ),
    (
        "SISTEMA",
        [
            ("CONFIGURACOES", "Configuracoes", "settings"),
        ],
    ),
]

NAV_ITEMS = [item for _group, items in NAV_GROUPS for item in items]
NAV_LABELS = {key: label for key, label, _icon in NAV_ITEMS}
EXPANDED_ICON_SIZE = QSize(26, 26)
COLLAPSED_ICON_SIZE = QSize(43, 43)
THEME_ICON_SIZE = QSize(28, 28)


class Sidebar(QFrame):
    page_selected = Signal(str)
    collapse_requested = Signal()
    theme_toggle_requested = Signal()

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.buttons: dict[str, QPushButton] = {}
        self.group_labels: list[QLabel] = []
        self.collapsed = False
        self._nav_badges: dict[str, int] = {}
        self.setObjectName("Sidebar")
        self.setMinimumWidth(236)
        self.setMaximumWidth(236)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(8)

        top = QPushButton("  " + self.service.company)
        top.setIcon(make_icon("collapse", self.service.palette["accent"]))
        top.setIconSize(EXPANDED_ICON_SIZE)
        top.setObjectName("GhostButton")
        top.setToolTip("Recolher ou expandir o menu lateral")
        top.clicked.connect(self.collapse_requested.emit)
        self.top_button = top
        layout.addWidget(top)

        caption = QLabel("Controle de Producao")
        caption.setObjectName("Caption")
        self.caption = caption
        layout.addWidget(caption)

        for group, items in NAV_GROUPS:
            group_buttons = [item for item in items if self._can_view_item(item[0])]
            if not group_buttons:
                continue
            group_label = QLabel(group)
            group_label.setObjectName("SidebarGroupLabel")
            self.group_labels.append(group_label)
            layout.addWidget(group_label)
            for key, label, icon in group_buttons:
                btn = QPushButton(label)
                btn.setObjectName("NavButton")
                btn.setProperty("active", "false")
                btn.setProperty("collapsed", "false")
                btn.setIcon(make_icon(icon, self.service.palette["accent"]))
                btn.setIconSize(EXPANDED_ICON_SIZE)
                btn.setMinimumHeight(34)
                btn.setMaximumHeight(34)
                btn.setToolTip(label)
                btn.clicked.connect(lambda _=False, page=key: self.page_selected.emit(page))
                self.buttons[key] = btn
                layout.addWidget(btn)
        layout.addStretch()

        self.theme_button = QPushButton()
        self.theme_button.setObjectName("ThemeToggleButton")
        self.theme_button.setProperty("collapsed", "false")
        self.theme_button.setMinimumHeight(36)
        self.theme_button.setMaximumHeight(36)
        self.theme_button.setIconSize(THEME_ICON_SIZE)
        self.theme_button.clicked.connect(self.theme_toggle_requested.emit)
        layout.addWidget(self.theme_button)
        self.update_theme_button()

    def _can_view_item(self, key: str) -> bool:
        if hasattr(self.service, "can_view_nav"):
            return bool(self.service.can_view_nav(key))
        visible = set(self.service.visible_areas()) if hasattr(self.service, "visible_areas") else set()
        always_visible = {"PAINEL GERAL", "DASHBOARD EXECUTIVO", "FISCAL", "PARCIAIS", "RELATORIOS OPERACIONAIS", "HISTORICO", "CONFIGURACOES"}
        return key in always_visible or key in visible

    def set_nav_badge(self, key: str, count: int):
        self._nav_badges[key] = count
        self._apply_badge_text(key)

    def _apply_badge_text(self, key: str):
        button = self.buttons.get(key)
        if not button:
            return
        if self.collapsed:
            button.setText("")
            return
        label = NAV_LABELS.get(key, key)
        count = self._nav_badges.get(key, 0)
        button.setText(f"{label}   {count}" if count else label)

    def set_active(self, key: str):
        for item_key, button in self.buttons.items():
            button.setProperty("active", "true" if item_key == key else "false")
            button.style().unpolish(button)
            button.style().polish(button)

    def set_collapsed(self, collapsed: bool):
        self.collapsed = collapsed
        width = 76 if collapsed else 236
        self.setMinimumWidth(width)
        self.setMaximumWidth(width)
        self.top_button.setText("" if collapsed else "  " + self.service.company)
        self.caption.setVisible(not collapsed)
        for label in self.group_labels:
            label.setVisible(not collapsed)
        for key, button in self.buttons.items():
            self._apply_badge_text(key)
            button.setIconSize(COLLAPSED_ICON_SIZE if collapsed else EXPANDED_ICON_SIZE)
            button.setMinimumHeight(44 if collapsed else 34)
            button.setMaximumHeight(44 if collapsed else 34)
            button.setProperty("collapsed", "true" if collapsed else "false")
            button.style().unpolish(button)
            button.style().polish(button)
        self.update_theme_button()

    def update_theme_button(self):
        current_palette = getattr(self.service, "palette_name", "claro")
        target_dark = current_palette == "claro"
        label = "Tema escuro" if target_dark else "Tema claro"
        icon_name = "moon" if target_dark else "sun"
        self.theme_button.setText("" if self.collapsed else label)
        self.theme_button.setIconSize(COLLAPSED_ICON_SIZE if self.collapsed else THEME_ICON_SIZE)
        self.theme_button.setMinimumHeight(44 if self.collapsed else 36)
        self.theme_button.setMaximumHeight(44 if self.collapsed else 36)
        self.theme_button.setProperty("collapsed", "true" if self.collapsed else "false")
        self.theme_button.setIcon(make_icon(icon_name, self.service.palette["accent"]))
        self.theme_button.setToolTip(f"Alternar para {label.lower()}")
        self.theme_button.style().unpolish(self.theme_button)
        self.theme_button.style().polish(self.theme_button)
