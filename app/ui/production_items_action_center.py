from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QTextEdit, QVBoxLayout, QWidget

from app.ui.action_center.handlers.galvanization import choose_existing_load_for_addition
from app.ui.components.action_card_button import ActionCardButton
from app.ui.components.modern_button import ModernButton
from app.ui.components.status_badge import StatusBadge
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.theme_tokens import with_alpha


class ProductionItemsActionCenter(QDialog):
    """Central de acoes da selecao de itens.

    A pagina continua dona das operacoes de dominio; esta janela apenas exibe
    as acoes e encaminha a selecao original, preservando o escopo por item.
    """

    def __init__(self, page, rows: list[dict], parent=None):
        super().__init__(parent)
        self.page = page
        self.rows = rows
        self.changed = False
        self.setWindowTitle("Acoes dos itens selecionados")
        style_dialog_from_parent(self, parent)
        self._build()
        self.setMinimumWidth(720)
        self.resize(760, self.sizeHint().height())

    def _build(self):
        palette = self.page.service.palette
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(12)
        title = QLabel(f"{len(self.rows)} item(ns) selecionado(s)")
        title.setStyleSheet("font-size: 16px; font-weight: 800;")
        root.addWidget(title)
        badges = QHBoxLayout()
        badges.addWidget(StatusBadge("Producao", with_alpha(palette["area_production"], 34), palette["area_production"]))
        proposals = len({row.get("api_proposal_id") for row in self.rows if row.get("api_proposal_id")})
        badges.addWidget(StatusBadge(f"{proposals} proposta(s)", with_alpha(palette["muted"], 30), palette["text"]))
        badges.addStretch()
        root.addLayout(badges)
        root.addWidget(QLabel("Acoes disponiveis"))

        actions = []
        if any(str(row.get("status_producao") or "").upper() not in {"INICIADO", "PARADO"} for row in self.rows):
            actions.append(("Iniciar producao", "Inicie a producao da proposta dos itens selecionados.", "status", self._start))
        if self.page.service.can_edit("PRODUCAO"):
            actions.append(("Definir fluxo dos itens selecionados", "Altere o fluxo somente dos itens escolhidos, mesmo em propostas diferentes.", "settings", self._flow))
            actions.append(("Registrar producao dos itens selecionados", "Registre a producao sem alterar os demais itens das propostas.", "status", self._register))
        if self.page._can_mount_load():
            actions.append(("Adicionar a uma carga existente", "Escolha uma carga aberta e inclua somente estes itens.", "load", self._existing_load))
            actions.append(("Criar nova carga", "Crie uma carga com os itens selecionados; eles serao produzidos automaticamente.", "new", self._new_load))

        container = QWidget()
        grid = QGridLayout(container)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        for index, (label, description, icon, handler) in enumerate(actions):
            card = ActionCardButton(label, description, icon, "primary" if index == 0 else "secondary", palette)
            card.clicked.connect(lambda _checked=False, callback=handler: self._run(callback))
            grid.addWidget(card, index // 2, index % 2)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        root.addWidget(QLabel("Observacao (opcional)"))
        self.observation = QTextEdit()
        self.observation.setPlaceholderText("Acrescente uma informacao importante sobre esta operacao")
        self.observation.setFixedHeight(68)
        root.addWidget(self.observation)
        footer = QHBoxLayout()
        footer.addStretch()
        close = ModernButton("Fechar", "close")
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        root.addLayout(footer)

    def _run(self, callback):
        self.accept()
        callback()

    def _start(self):
        self.page.start_selected(self.rows, self.observation.toPlainText().strip())

    def _flow(self):
        self.page.open_flow_review(self.rows)

    def _register(self):
        self.page.register_selected(self.rows)

    def _new_load(self):
        self.page.open_assemble_load(self.rows)

    def _existing_load(self):
        load_id = choose_existing_load_for_addition(self.page.service, self.page)
        if load_id is not None:
            self.page.open_assemble_load(self.rows, load_id=load_id)
