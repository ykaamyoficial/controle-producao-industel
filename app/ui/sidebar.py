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


class Sidebar(QFrame):
    page_selected = Signal(str)
    collapse_requested = Signal()

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.buttons: dict[str, QPushButton] = {}
        self.group_labels: list[QLabel] = []
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
        top.setIconSize(QSize(18, 18))
        top.setObjectName("GhostButton")
        top.setToolTip("Recolher ou expandir o menu lateral")
        top.clicked.connect(self.collapse_requested.emit)
        self.top_button = top
        layout.addWidget(top)

        caption = QLabel("Controle de Producao")
        caption.setObjectName("Caption")
        self.caption = caption
        layout.addWidget(caption)

        visible = set(self.service.visible_areas())
        always_visible = {
            "HISTORICO",
            "DASHBOARD EXECUTIVO",
            "RELATORIOS OPERACIONAIS",
            "CONFIGURACOES",
            "PAINEL GERAL",
            "PARCIAIS",
            "FISCAL",
        }
        for group, items in NAV_GROUPS:
            group_buttons = [item for item in items if item[0] in always_visible or item[0] in visible]
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
                btn.setIcon(make_icon(icon, self.service.palette["accent"]))
                btn.setIconSize(QSize(18, 18))
                btn.setMinimumHeight(38)
                btn.setToolTip(label)
                btn.clicked.connect(lambda _=False, page=key: self.page_selected.emit(page))
                self.buttons[key] = btn
                layout.addWidget(btn)
        layout.addStretch()

    def set_active(self, key: str):
        for item_key, button in self.buttons.items():
            button.setProperty("active", "true" if item_key == key else "false")
            button.style().unpolish(button)
            button.style().polish(button)

    def set_collapsed(self, collapsed: bool):
        width = 76 if collapsed else 236
        self.setMinimumWidth(width)
        self.setMaximumWidth(width)
        self.top_button.setText("" if collapsed else "  " + self.service.company)
        self.caption.setVisible(not collapsed)
        for label in self.group_labels:
            label.setVisible(not collapsed)
        for key, button in self.buttons.items():
            button.setText("" if collapsed else NAV_LABELS[key])
