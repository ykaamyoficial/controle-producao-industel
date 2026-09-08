from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from app.ui.components.app_icon_button import AppIconButton
from app.ui.icons import AppIcons, IconColorRole


NAV_GROUPS = [
    (
        "PAINEIS",
        [
            ("PAINEL GERAL", "Painel geral", AppIcons.DASHBOARD),
            ("DASHBOARD EXECUTIVO", "Dashboard Executivo", AppIcons.DASHBOARD),
        ],
    ),
    (
        "OPERACAO",
        [
            ("CONTROLE GERAL", "Controle Geral", AppIcons.CONTROL),
            ("PRODUCAO", "Producao", AppIcons.PRODUCTION),
            ("GALVANIZACAO", "Galvanizacao", AppIcons.GALVANIZATION),
            ("EXPEDICAO", "Expedicao", AppIcons.EXPEDITION),
            ("FISCAL", "Fiscal", AppIcons.FISCAL),
            ("PARCIAIS", "Parciais", AppIcons.PARTIAL),
            ("ALMOXARIFADO", "Almoxarifado", AppIcons.STOCK),
        ],
    ),
    (
        "ANALISE",
        [
            ("RELATORIOS OPERACIONAIS", "Relatorios Operacionais", AppIcons.REPORTS),
            ("HISTORICO", "Historico", AppIcons.HISTORY),
        ],
    ),
]

NAV_ITEMS = [item for _group, items in NAV_GROUPS for item in items]
NAV_LABELS = {key: label for key, label, _icon in NAV_ITEMS}
EXPANDED_ICON_SIZE = 26
COLLAPSED_ICON_SIZE = 43


class Sidebar(QFrame):
    page_selected = Signal(str)
    collapse_requested = Signal()

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.buttons: dict[str, AppIconButton] = {}
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

        top = AppIconButton(
            AppIcons.COLLAPSE,
            "  " + self.service.company,
            palette=self.service.palette,
            color_role=IconColorRole.PRIMARY,
            size=EXPANDED_ICON_SIZE,
            tooltip="Recolher ou expandir o menu lateral",
        )
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
                btn = AppIconButton(
                    icon,
                    label,
                    palette=self.service.palette,
                    color_role=IconColorRole.PRIMARY,
                    size=EXPANDED_ICON_SIZE,
                    tooltip=label,
                )
                btn.setObjectName("NavButton")
                btn.setProperty("active", "false")
                btn.setProperty("collapsed", "false")
                btn.setMinimumHeight(34)
                btn.setMaximumHeight(34)
                btn.clicked.connect(lambda _=False, page=key: self.page_selected.emit(page))
                self.buttons[key] = btn
                layout.addWidget(btn)
        layout.addStretch()

    def _can_view_item(self, key: str) -> bool:
        if hasattr(self.service, "can_view_nav"):
            return bool(self.service.can_view_nav(key))
        visible = set(self.service.visible_areas()) if hasattr(self.service, "visible_areas") else set()
        always_visible = {"PAINEL GERAL", "DASHBOARD EXECUTIVO", "FISCAL", "PARCIAIS", "RELATORIOS OPERACIONAIS", "HISTORICO", "CONFIGURACOES"}
        return key in always_visible or key in visible

    def apply_palette(self, palette: dict):
        self.top_button.set_palette(palette)
        for button in self.buttons.values():
            button.set_palette(palette)

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
            button.set_size(COLLAPSED_ICON_SIZE if collapsed else EXPANDED_ICON_SIZE)
            button.setMinimumHeight(44 if collapsed else 34)
            button.setMaximumHeight(44 if collapsed else 34)
            button.setProperty("collapsed", "true" if collapsed else "false")
            button.style().unpolish(button)
            button.style().polish(button)
