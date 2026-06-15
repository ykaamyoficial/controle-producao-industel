from __future__ import annotations

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from app.ui.icons import make_icon


NAV_ITEMS = [
    ("PAINEL GERAL", "Painel geral", "dashboard"),
    ("CONTROLE GERAL", "Controle Geral", "control"),
    ("PRODUCAO", "Producao", "production"),
    ("GALVANIZACAO", "Galvanizacao", "galvanization"),
    ("EXPEDICAO", "Expedicao", "expedition"),
    ("ALMOXARIFADO", "Almoxarifado", "stock"),
    ("PARCIAIS", "Parciais", "partial"),
    ("HISTORICO", "Historico", "history"),
    ("AUDITORIA", "Auditoria", "audit"),
    ("RELATORIOS", "Relatorios", "reports"),
    ("CONFIGURACOES", "Configuracoes", "settings"),
]


class Sidebar(QFrame):
    page_selected = Signal(str)
    collapse_requested = Signal()

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.buttons: dict[str, QPushButton] = {}
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
        for key, label, icon in NAV_ITEMS:
            if key in {"HISTORICO", "RELATORIOS", "CONFIGURACOES", "PAINEL GERAL", "PARCIAIS"} or key in visible:
                if key == "AUDITORIA" and self.service.user_profile() != "Administrador":
                    continue
                btn = QPushButton(label)
                btn.setObjectName("NavButton")
                btn.setProperty("active", "false")
                btn.setIcon(make_icon(icon, self.service.palette["accent"]))
                btn.setIconSize(QSize(18, 18))
                btn.setMinimumHeight(40)
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
        for key, button in self.buttons.items():
            button.setText("" if collapsed else next(label for item, label, _icon in NAV_ITEMS if item == key))
