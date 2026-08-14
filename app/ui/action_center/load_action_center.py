from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ui.action_center.descriptor import ActionCategory, ActionDescriptor
from app.ui.action_center.provider import CATEGORY_TO_CARD_TYPE
from app.ui.components.action_card_button import ActionCardButton
from app.ui.components.modern_button import ModernButton
from app.ui.components.status_badge import StatusBadge
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.icons import AppIcons
from app.ui.theme_tokens import with_alpha


class GalvanizationLoadActionCenter(QDialog):
    """Central visual de acoes da carga.

    A carga continua sendo governada pelo service. Esta tela somente apresenta
    as acoes ja autorizadas e encaminha cada clique para o callback da pagina.
    Assim, a aba Cargas usa o mesmo padrao visual da Central de Acoes sem
    transformar carga em proposta ou duplicar regras de negocio.
    """

    def __init__(
        self,
        service,
        load: dict,
        handlers: dict[str, Callable[[], bool]],
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.load = dict(load)
        self.handlers = handlers
        self._buttons: list[ActionCardButton] = []
        self.setWindowTitle("Acoes da carga")
        style_dialog_from_parent(self, parent)
        self.setMinimumWidth(720)
        self.resize(760, 560)
        self._build()
        self._center_on_parent(parent)

    def _center_on_parent(self, parent):
        owner = parent.window() if parent and parent.window() else None
        if not owner:
            return
        frame = self.frameGeometry()
        frame.moveCenter(owner.geometry().center())
        self.move(frame.topLeft())

    def _build(self):
        palette = self.service.palette
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(12)
        root.addLayout(self._header(palette))

        title = QLabel("Acoes disponiveis")
        title.setStyleSheet("font-weight: 700; font-size: 13px;")
        root.addWidget(title)

        cards = QWidget()
        grid = QGridLayout(cards)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        descriptors = self._descriptors()
        for index, descriptor in enumerate(descriptors):
            grid.addWidget(self._card(descriptor, palette), index // 2, index % 2)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(cards)
        root.addWidget(scroll, 1)

        root.addWidget(QLabel("Observacao (opcional)"))
        self.observation = QTextEdit()
        self.observation.setPlaceholderText("Acrescente uma informacao importante sobre esta operacao")
        self.observation.setFixedHeight(68)
        root.addWidget(self.observation)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {palette['border']}; border: 0;")
        root.addWidget(divider)

        footer = QHBoxLayout()
        footer.addStretch()
        close = ModernButton("Fechar", AppIcons.CLOSE)
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        root.addLayout(footer)

    def _header(self, palette) -> QVBoxLayout:
        header = QVBoxLayout()
        header.setSpacing(4)
        load_id = self.load.get("id") or "-"
        driver = str(self.load.get("motorista") or "").strip()
        title = QLabel(f"Carga #{load_id}" + (f" — {driver}" if driver else ""))
        title.setStyleSheet("font-size: 16px; font-weight: 800;")
        title.setWordWrap(True)
        header.addWidget(title)

        badges = QHBoxLayout()
        badges.setContentsMargins(0, 0, 0, 0)
        area = StatusBadge("Galvanizacao", with_alpha(palette.get("area_galvanization", palette["accent"]), 34), palette.get("area_galvanization", palette["accent"]))
        badges.addWidget(area)
        status = str(self.load.get("status") or "").strip()
        status_label = self.service.load_status_label(status) if hasattr(self.service, "load_status_label") else status
        if status_label:
            badges.addWidget(StatusBadge(status_label, with_alpha(palette["muted"], 30), palette["text"]))
        badges.addStretch()
        header.addLayout(badges)
        return header

    def _descriptors(self) -> list[ActionDescriptor]:
        actions = [
            ActionDescriptor(
                id="OPEN_LOAD_DETAILS",
                label=f"Abrir carga #{self.load.get('id') or '-'}",
                description="Consulte situacao, itens, propostas e retorno desta carga.",
                icon=AppIcons.CARGO,
                category=ActionCategory.NORMAL,
                area="GALVANIZACAO",
                order=10,
            )
        ]
        allowed = set(self.service.galvanization_load_actions(self.load)) if hasattr(self.service, "galvanization_load_actions") else set()
        definitions = (
            ("EDIT", "EDIT_LOAD", "Editar carga", "Altere motorista, peso, prazo ou itens enquanto a carga estiver aberta.", AppIcons.EDIT, ActionCategory.NORMAL),
            ("RELEASE", "RELEASE_LOAD", "Liberar carga", "Envie a carga para a etapa de galvanizacao.", AppIcons.STATUS, ActionCategory.PRIMARY),
            ("RETURN", "REGISTER_RETURN", "Registrar retorno da galvanizacao", "Informe a devolucao desta carga e atualize as propostas relacionadas.", AppIcons.CARGO, ActionCategory.PRIMARY),
        )
        for permission, action_id, label, description, icon, category in definitions:
            if permission in allowed:
                actions.append(ActionDescriptor(action_id, label, description, icon, category, "GALVANIZACAO"))
        return actions

    def _card(self, descriptor: ActionDescriptor, palette) -> ActionCardButton:
        card = ActionCardButton(
            title=descriptor.label,
            description=descriptor.description,
            icon=descriptor.icon,
            action_type=CATEGORY_TO_CARD_TYPE.get(descriptor.category, "secondary"),
            palette=palette,
        )
        card.clicked.connect(lambda _checked=False, action=descriptor: self._run(action))
        self._buttons.append(card)
        return card

    def _run(self, descriptor: ActionDescriptor):
        handler = self.handlers.get(descriptor.id)
        if handler is None:
            return
        self.setEnabled(False)
        try:
            changed = bool(handler())
        finally:
            self.setEnabled(True)
        if changed:
            self.accept()
