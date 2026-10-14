from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QTextEdit, QVBoxLayout, QWidget

from app.ui.action_center.descriptor import ActionCategory, ActionDescriptor
from app.ui.action_center.provider import CATEGORY_TO_CARD_TYPE
from app.ui.components.action_card_button import ActionCardButton
from app.ui.components.dialog_shell import dialog_header
from app.ui.components.modern_button import ModernButton
from app.ui.components.status_badge import area_badge, neutral_badge
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.icons import AppIcons


class FiscalActionCenter(QDialog):
    """Central visual das acoes fiscais, sem duplicar regras do service."""

    def __init__(self, service, fiscal_row: dict, handlers: dict[str, Callable[[], bool]], parent=None):
        super().__init__(parent)
        self.service = service
        self.fiscal_row = dict(fiscal_row)
        self.handlers = handlers
        self.setWindowTitle("Ações fiscais")
        style_dialog_from_parent(self, parent)
        self.setMinimumWidth(720)
        self.resize(760, 550)
        self._build()
        self._center_on_parent(parent)

    def _center_on_parent(self, parent):
        owner = parent.window() if parent and parent.window() else None
        if owner:
            frame = self.frameGeometry()
            frame.moveCenter(owner.geometry().center())
            self.move(frame.topLeft())

    def _build(self):
        palette = self.service.palette
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        root.addWidget(self._header(palette))
        label = QLabel("Ações disponíveis")
        label.setObjectName("PanelTitle")
        root.addWidget(label)

        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        for index, descriptor in enumerate(self._descriptors()):
            card = ActionCardButton(
                title=descriptor.label,
                description=descriptor.description,
                icon=descriptor.icon,
                action_type=CATEGORY_TO_CARD_TYPE.get(descriptor.category, "secondary"),
                palette=palette,
            )
            card.clicked.connect(lambda _checked=False, action=descriptor: self._run(action))
            grid.addWidget(card, index // 2, index % 2)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        root.addWidget(QLabel("Observação (opcional)"))
        observation = QTextEdit()
        observation.setPlaceholderText("Acrescente uma informação importante sobre esta operação")
        observation.setFixedHeight(68)
        root.addWidget(observation)
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setObjectName("Divider")
        root.addWidget(divider)
        footer = QHBoxLayout()
        footer.addStretch()
        close = ModernButton("Fechar", AppIcons.CLOSE, variant="ghost")
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        root.addLayout(footer)

    def _header(self, palette) -> QFrame:
        proposal = self.fiscal_row.get("proposta") or "Proposta fiscal"
        client = self.fiscal_row.get("cliente") or ""
        title = QLabel(f"{proposal}" + (f" — {client}" if client else ""))
        badges = QHBoxLayout()
        badges.setContentsMargins(0, 0, 0, 0)
        area_color = palette.get("area_fiscal", palette["danger"])
        badges.addWidget(area_badge("Fiscal", area_color))
        status = self.fiscal_row.get("status_fiscal") or self.fiscal_row.get("situacao_fiscal") or ""
        status_label = self.service.fiscal_status_label(status) if hasattr(self.service, "fiscal_status_label") else status
        if status_label:
            badges.addWidget(neutral_badge(status_label, palette))
        return dialog_header(title, status=[badges])

    def _descriptors(self) -> list[ActionDescriptor]:
        row = self.fiscal_row
        actions = [ActionDescriptor(
            "OPEN_FISCAL_DETAILS", "Abrir detalhes da proposta",
            "Consulte itens, resumo, historico fiscal e emissoes desta proposta.",
            AppIcons.AUDIT, ActionCategory.NORMAL, "FISCAL",
        )]
        status = str(row.get("status_fiscal") or "").strip().upper()
        if self.service.can_register_fiscal_emission() and status not in {"NOTA_FISCAL_EMITIDA", "FISCAL_CANCELADO"}:
            actions.append(ActionDescriptor(
                "REGISTER_FISCAL_EMISSION", "Registrar emissao fiscal",
                "Informe os itens e quantidades que serao registrados nesta emissao.",
                AppIcons.STATUS, ActionCategory.PRIMARY, "FISCAL",
            ))
        has_emissions = bool(self.service.fiscal_emissions(int(row["fiscal_processo_id"])))
        if getattr(self.service, "can_cancel_fiscal_emission", lambda: False)() and has_emissions:
            actions.append(ActionDescriptor(
                "CANCEL_FISCAL_EMISSION", "Cancelar ultima emissao interna",
                "Desfaça o ultimo vinculo fiscal interno desta proposta.",
                AppIcons.REMOVE, ActionCategory.ATTENTION, "FISCAL",
            ))
        return actions

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
