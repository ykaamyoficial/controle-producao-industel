from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from app.ui.action_center.descriptor import ActionCategory, ActionDescriptor
from app.ui.action_center.provider import CATEGORY_TO_CARD_TYPE
from app.ui.components.action_card_button import ActionCardButton
from app.ui.components.dialog_shell import dialog_header
from app.ui.components.modern_button import ModernButton
from app.ui.components.row_actions import RowAction
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.icons import AppIcons


class RowActionCenter(QDialog):
    """Central de Acoes leve para linhas de Inspecao e Logistica: mesma casca de
    cards da Central da carga, mas recebe a lista pronta de `RowAction` (a pagina
    ja decidiu o que a linha permite). O clique fecha a Central e depois executa a acao."""

    def __init__(self, palette: dict, title: str, actions: list[RowAction], parent=None):
        super().__init__(parent)
        self.palette = palette
        self.actions = actions
        self.cards: list[ActionCardButton] = []
        self.setWindowTitle("Ações")
        style_dialog_from_parent(self, parent)
        self.setMinimumWidth(720)
        self.resize(760, 420)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        root.addWidget(dialog_header(title))
        heading = QLabel("Ações disponíveis")
        heading.setObjectName("PanelTitle")
        root.addWidget(heading)
        cards = QWidget()
        grid = QGridLayout(cards)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        for index, action in enumerate(actions):
            grid.addWidget(self._card(action), index // 2, index % 2)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(cards)
        root.addWidget(scroll, 1)
        footer = QHBoxLayout()
        footer.addStretch()
        close = ModernButton("Fechar", AppIcons.CLOSE, variant="ghost")
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        root.addLayout(footer)

    def _card(self, action: RowAction) -> ActionCardButton:
        descriptor = ActionDescriptor(
            id=action.label,
            label=action.label,
            description=action.description,
            icon=action.icon,
            category=ActionCategory.PRIMARY if action.primary else ActionCategory.NORMAL,
            area="",
        )
        card = ActionCardButton(
            title=descriptor.label,
            description=descriptor.description,
            icon=descriptor.icon,
            action_type=CATEGORY_TO_CARD_TYPE[descriptor.category],
            palette=self.palette,
        )
        card.setEnabled(action.enabled)
        card.clicked.connect(lambda _checked=False, act=action: self._run(act))
        self.cards.append(card)
        return card

    def _run(self, action: RowAction) -> None:
        self.accept()
        action.callback()
