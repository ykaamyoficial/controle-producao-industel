from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from app.ui.components.app_icon_button import AppIconButton
from app.ui.components.count_badge import format_count_badge
from app.ui.icons import AppIcons, IconColorRole
from app.ui.fonts import scaled_px


# Chaves (1o campo) sao identificadores internos e ficam sem acento; so o
# rotulo exibido (2o campo) e o nome do grupo levam acentuacao.
NAV_GROUPS = [
    (
        "PAINÉIS",
        [
            ("PAINEL GERAL", "Painel geral", AppIcons.DASHBOARD),
            ("DASHBOARD EXECUTIVO", "Dashboard Executivo", AppIcons.DASHBOARD),
        ],
    ),
    (
        "OPERAÇÃO",
        [
            ("CONTROLE GERAL", "Controle Geral", AppIcons.CONTROL),
            ("PRODUCAO", "Produção", AppIcons.PRODUCTION),
            ("GALVANIZACAO", "Galvanização", AppIcons.GALVANIZATION),
            ("EXPEDICAO", "Expedição", AppIcons.EXPEDITION),
            ("FISCAL", "Fiscal", AppIcons.FISCAL),
            ("PARCIAIS", "Parciais", AppIcons.PARTIAL),
            ("ALMOXARIFADO", "Almoxarifado", AppIcons.STOCK),
        ],
    ),
    (
        "ANÁLISE",
        [
            ("RELATORIOS OPERACIONAIS", "Relatórios Operacionais", AppIcons.REPORTS),
            ("HISTORICO", "Histórico", AppIcons.HISTORY),
        ],
    ),
]

NAV_ITEMS = [item for _group, items in NAV_GROUPS for item in items]
NAV_LABELS = {key: label for key, label, _icon in NAV_ITEMS}
EXPANDED_ICON_SIZE = 26
COLLAPSED_ICON_SIZE = 43
EXPANDED_ITEM_HEIGHT = 40
COLLAPSED_ITEM_HEIGHT = 44


class NavButton(AppIconButton):
    """Item da barra lateral. Com o menu expandido o contador vira uma pilula
    a direita do rotulo (pintada, nunca via setText - o botao nao muda de
    largura); recolhido, cai no contador padrao do canto do icone."""

    def _paint_badge(self) -> None:
        if self.property("collapsed") == "true":
            super()._paint_badge()
            return
        text = format_count_badge(self._badge_count)
        if not text:
            return
        active = self.property("active") == "true"
        accent = self._palette.get("accent", "#006fc9")
        accent_text = self._palette.get("accent_text", "#ffffff")
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont(self.font())
        font.setPixelSize(scaled_px(11))
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        width = max(20.0, QFontMetricsF(font).horizontalAdvance(text) + 12)
        pill = QRectF(self.width() - width - 10, self.height() / 2 - 9, width, 18)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(accent_text if active else accent))
        painter.drawRoundedRect(pill, 9, 9)
        painter.setPen(QColor(accent if active else accent_text))
        painter.drawText(pill, Qt.AlignCenter, text)
        painter.end()


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
        self._active_key: str | None = None
        self.setObjectName("Sidebar")
        self.setMinimumWidth(236)
        self.setMaximumWidth(236)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(6)

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

        caption = QLabel("Controle de Produção")
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
                btn = NavButton(
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
                btn.setMinimumHeight(EXPANDED_ITEM_HEIGHT)
                btn.setMaximumHeight(EXPANDED_ITEM_HEIGHT)
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
        button.setText("" if self.collapsed else NAV_LABELS.get(key, key))
        button.set_badge_count(self._nav_badges.get(key, 0))

    def set_active(self, key: str):
        self._active_key = key
        for item_key, button in self.buttons.items():
            active = item_key == key
            button.setProperty("active", "true" if active else "false")
            # Icone do item ativo na cor do texto sobre o destaque: na cor de
            # destaque ele sumia dentro da pilula azul.
            button.set_color_role(IconColorRole.ON_ACCENT if active else IconColorRole.PRIMARY)
            button.style().unpolish(button)
            button.style().polish(button)

    def set_collapsed(self, collapsed: bool):
        self.collapsed = collapsed
        width = 76 if collapsed else 236
        height = COLLAPSED_ITEM_HEIGHT if collapsed else EXPANDED_ITEM_HEIGHT
        self.setMinimumWidth(width)
        self.setMaximumWidth(width)
        self.top_button.setText("" if collapsed else "  " + self.service.company)
        self.caption.setVisible(not collapsed)
        for label in self.group_labels:
            label.setVisible(not collapsed)
        for key, button in self.buttons.items():
            button.setProperty("collapsed", "true" if collapsed else "false")
            self._apply_badge_text(key)
            button.set_size(COLLAPSED_ICON_SIZE if collapsed else EXPANDED_ICON_SIZE)
            button.setMinimumHeight(height)
            button.setMaximumHeight(height)
            button.style().unpolish(button)
            button.style().polish(button)
