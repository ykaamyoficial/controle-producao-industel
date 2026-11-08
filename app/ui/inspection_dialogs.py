from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.inspection_service import LINK_MAX_LENGTH, STAGE_LABELS
from app.ui.background_worker import start_worker
from app.ui.components.detail_widgets import (
    EM_DASH,
    STEP_CURRENT,
    STEP_DONE,
    STEP_PENDING,
    CountTabWidget,
    FlowTrail,
    kv_grid,
    make_panel,
)
from app.ui.components.dialog_shell import dialog_footer, dialog_header, dialog_layout, set_notice_kind, set_validation_state
from app.ui.components.modern_button import ModernButton
from app.ui.components.path_field import PathField, path_rows_panel
from app.ui.components.status_badge import StatusBadge
from app.ui.date_edit_dialog import DateEditDialog
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.inspection_progress import STALE_ERROR_CODE, CatchUpDialog, RecordProgressDialog
from app.ui.styles import STATUS_BADGE_COLORS, _contrast_text, _is_dark

# Categoria de cor (STATUS_BADGE_COLORS) de cada etapa da inspecao.
STAGE_CATEGORY = {
    "pendente": "attention",
    "cadastro": "attention",
    "solicitada": "waiting",
    "nqt": "waiting",
    "dispensa": "waiting",
    "inloco": "progress",
    "doc": "attention",
    "fim": "final_done",
    "to_request": "neutral",
}
# Posicao de cada etapa na trilha de seis nos.
TRAIL_NODES = ("Solicitação pendente", "Cadastro do PD", "Solicitação", "NQT gerado", "Decisão", "PIT ou visita", "DOC BIM em PDF")
TRAIL_POSITION = {"pendente": 0, "cadastro": 1, "solicitada": 2, "nqt": 4, "dispensa": 5, "inloco": 5, "doc": 6, "fim": 7}
DATE_FORMAT = "%d/%m/%Y"


def fit_to_screen(dialog: QDialog, width: int, height: int) -> None:
    """Tamanho desejado, limitado à área útil da tela (cabe em 1366x768 sem cortar o rodapé)."""
    screen = (dialog.screen() if dialog.parent() is None else dialog.parent().screen()) or QGuiApplication.primaryScreen()
    if screen is None:
        dialog.resize(width, height)
        return
    area = screen.availableGeometry()
    dialog.resize(min(width, max(480, area.width() - 48)), min(height, max(420, area.height() - 72)))


def scrolled(page: QWidget) -> QScrollArea:
    """Página de aba que rola em vez de espremer os painéis quando a janela é baixa."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidget(page)
    return scroll


def stage_colors(stage: str, palette: dict) -> tuple[str, str]:
    """(fundo, texto) do selo da etapa, na paleta ativa."""
    colors = STATUS_BADGE_COLORS["escuro" if _is_dark(palette.get("bg", "#ffffff")) else "claro"]
    background = colors[STAGE_CATEGORY.get(stage, "neutral")]
    return background, _contrast_text(background)


def stage_label(stage: str) -> str:
    return STAGE_LABELS.get(stage, stage or EM_DASH)


def format_date(value: Any) -> str:
    """Data ISO (AAAA-MM-DD) da API em DD/MM/AAAA."""
    if not value:
        return EM_DASH
    try:
        return date.fromisoformat(str(value)[:10]).strftime(DATE_FORMAT)
    except ValueError:
        return str(value)


def format_moment(value: Any) -> str:
    if not value:
        return EM_DASH
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.strftime(f"{DATE_FORMAT} %H:%M")


def days_text(days: Any, *, long: bool = False, business: Any = None) -> str:
    """"6 dias (4 úteis)": dias corridos na etapa e, entre parênteses, os dias úteis da fábrica."""
    count = int(days or 0)
    text = f"{count} {'dia' if count == 1 else 'dias'}" + (" nesta etapa" if long else "")
    if business is not None:
        useful = int(business)
        text += f" ({useful} {'útil' if useful == 1 else 'úteis'})"
    return text


def parse_visit_date(text: str) -> str:
    """DD/MM/AAAA digitado -> AAAA-MM-DD da API. Levanta ValueError se invalida."""
    return datetime.strptime(text.strip(), DATE_FORMAT).date().isoformat()


def check_link(text: str, what: str) -> str:
    link = text.strip()
    if not link:
        raise ValueError(f"Informe o link ou caminho do {what}.")
    if len(link) > LINK_MAX_LENGTH:
        raise ValueError(f"O link do {what} passa de {LINK_MAX_LENGTH} caracteres.")
    return link


def _read_only_table(columns: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(True)
    return table


# Orientacao curta de cada etapa (o que costuma acontecer ate o proximo andamento).
STAGE_HINTS = {
    "pendente": "A inspeção ainda não foi solicitada. Solicite no portal e registre o andamento.",
    "cadastro": "O PD ainda não está cadastrado. Peça o cadastro no portal de cadastro e registre quando estiver pronto.",
    "solicitada": "Solicite a inspeção no portal. Quando o portal gerar o código NQT, registre o andamento.",
    "nqt": "Aguardando a Equatorial: dispensar a inspeção ou mandar um engenheiro à fábrica (in loco).",
    "dispensa": "Anexe a documentação PIT no portal e registre onde o arquivo (ou a pasta) está guardado.",
    "inloco": "Registre o resultado da visita do engenheiro: aprovada ou reprovada.",
    "doc": "A Equatorial gera o DOC depois da dispensa ou da aprovação. A inspeção só finaliza com o DOC BIM em PDF.",
    "fim": "Inspeção finalizada. Pedido liberado para a Logística.",
}


def history_registro(event: dict, previous_stage: str | None) -> str:
    """Texto do histórico: "De X para Y" nas mudanças de etapa, mais motivo e observação."""
    text = event.get("text") or ""
    if event.get("kind", "transition") == "transition" and previous_stage and previous_stage != event.get("stage"):
        text = f"De {stage_label(previous_stage)} para {stage_label(event.get('stage') or '')}. {text}".strip()
    if event.get("reason"):
        text = f"{text} Motivo: {event['reason']}" if text else f"Motivo: {event['reason']}"
    if event.get("note"):
        text = f"{text} Observação: {event['note']}" if text else f"Observação: {event['note']}"
    return text


class InspectionDetailDialog(QDialog):
    """Detalhes da inspecao de um PD: trilha do fluxo, situacao, andamento e historico.
    "Registrar andamento", "Atualizar atrasado", "Remarcar visita" e a correcao de data de um
    andamento abrem janelas proprias; a resposta (InspectionDetail) redesenha a tela.
    `changed` fica True se algo foi registrado, para a lista recarregar."""

    changed_signal = Signal()

    def __init__(self, service, inspection: dict, parent=None, *, can_edit: bool | None = None):
        super().__init__(parent)
        self.service = service
        self.api = service.inspection_service()
        self.data: dict = dict(inspection)
        self.can_edit = bool(service.can_edit("inspection")) if can_edit is None else bool(can_edit)
        self.changed = False
        self._tab_index = 0
        self._content: QWidget | None = None
        self.error_label: QLabel | None = None
        self.action_buttons: list[ModernButton] = []
        self._events: list[dict] = []
        self.setWindowTitle(f"Inspeção {self.data.get('pd_code', '')}")
        self.setMinimumSize(760, 480)
        fit_to_screen(self, 1040, 640)
        style_dialog_from_parent(self, parent)
        self._root = dialog_layout(self)
        self._render()
        self._reload()

    # ---- dados -----------------------------------------------------------
    def _reload(self) -> None:
        inspection_id = int(self.data["id"])
        start_worker(self, lambda: self.api.get(inspection_id), self._apply, self._show_error)

    def _apply(self, detail: dict) -> None:
        self.data = dict(detail)
        self._render()

    def _show_error(self, exc: Exception) -> None:
        if self.error_label is not None:
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)
        if getattr(exc, "error_code", None) == STALE_ERROR_CODE:
            self._reload()

    def _after_action(self, detail: dict) -> None:
        self.changed = True
        self.changed_signal.emit()
        self._apply(detail)

    # ---- acoes (cada uma abre a sua janela) --------------------------------
    def open_record(self) -> None:
        dialog = RecordProgressDialog(self.service, self.data, self)
        if dialog.exec() and dialog.result_data is not None:
            self._after_action(dialog.result_data)
        elif dialog.stale:
            self._reload()

    def open_catch_up(self) -> None:
        dialog = CatchUpDialog(self.service, self.data, self)
        if dialog.exec() and dialog.result_data is not None:
            self._after_action(dialog.result_data)
        elif dialog.stale:
            self._reload()

    def open_reschedule(self) -> None:
        inspection_id = int(self.data["id"])
        visit = self.data.get("visit_date")
        dialog = DateEditDialog(
            self,
            title="Remarcar visita",
            subtitle=f"PD {self.data.get('pd_code', '')} · visita in loco hoje em {format_date(visit)}",
            dates=[("visit_date", "Nova data da visita", date.fromisoformat(str(visit)[:10]) if visit else None)],
            send=lambda values, reason, _link, confirm: self.api.reschedule_visit(inspection_id, values["visit_date"], reason, confirm),
            ok_text="Remarcar",
        )
        if dialog.exec() and dialog.result_data is not None:
            self._after_action(dialog.result_data)

    def selected_event(self) -> dict | None:
        table = getattr(self, "history_table", None)
        rows = table.selectionModel().selectedRows() if table is not None and table.selectionModel() else []
        if not rows or not 0 <= rows[0].row() < len(self._events):
            return None
        return self._events[rows[0].row()]

    def open_correct_event(self) -> None:
        event = self.selected_event()
        if event is None or event.get("kind", "transition") != "transition":
            if self.error_label is not None:
                self.error_label.setText("Selecione um andamento do histórico para corrigir a data.")
                self.error_label.setVisible(True)
            return
        inspection_id, event_id = int(self.data["id"]), int(event["id"])
        occurred = event.get("occurred_on")
        dialog = DateEditDialog(
            self,
            title="Corrigir data do andamento",
            subtitle=f"{event.get('text') or ''} · hoje consta {format_date(occurred)}",
            dates=[("occurred_on", "Aconteceu em", date.fromisoformat(str(occurred)[:10]) if occurred else None)],
            send=lambda values, reason, _link, _confirm: self.api.correct_occurred_on(inspection_id, event_id, values["occurred_on"], reason),
            ok_text="Corrigir",
            shortcuts=True,
        )
        if dialog.exec() and dialog.result_data is not None:
            self._after_action(dialog.result_data)

    # ---- tela ------------------------------------------------------------
    def _render(self) -> None:
        if self._content is not None:
            self._tab_index = self._tabs.currentIndex()
            self._root.removeWidget(self._content)
            self._content.setParent(None)
            self._content.deleteLater()
        data = self.data
        stage = data.get("stage") or ""
        palette = self.service.palette
        self.action_buttons = []
        self.error_label = None

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        background, foreground = stage_colors(stage, palette)
        self.stage_badge = StatusBadge(stage_label(stage), background, foreground)
        proposals = ", ".join(data.get("proposal_numbers") or []) or "sem proposta vinculada"
        nqt = data.get("nqt_code") or "ainda sem código"
        self.days_label = QLabel(days_text(data.get("days_in_stage"), long=True, business=data.get("business_days_in_stage")))
        self.attempt_label = QLabel(f"Tentativa {data.get('attempt', 1)}")
        close = ModernButton("Fechar", "close", variant="ghost")
        close.clicked.connect(self.accept)
        layout.addWidget(
            dialog_header(
                f"Inspeção {data.get('pd_code', '')}",
                f"{proposals} · NQT {nqt}",
                status=[self.stage_badge, self.days_label, self.attempt_label],
                actions=[close],
            )
        )

        self._tabs = CountTabWidget()
        self._tabs.addTab(scrolled(self._progress_page()), "Andamento")
        events = list(data.get("events") or [])
        self._tabs.addTab(self._history_page(events), "Histórico", len(events))
        self._tabs.setCurrentIndex(min(self._tab_index, self._tabs.count() - 1))
        layout.addWidget(self._tabs, 1)

        self._content = content
        self._root.addWidget(content, 1)

    def _make_button(self, text: str, icon: str, variant: str, handler: Callable[[], None]) -> ModernButton:
        button = ModernButton(text, icon, variant=variant)
        button.clicked.connect(lambda _=False: handler())
        self.action_buttons.append(button)
        return button

    def _trail_steps(self) -> list[dict]:
        data = self.data
        stage = data.get("stage") or ""
        current = TRAIL_POSITION.get(stage, 0)
        decision = data.get("decision_type")
        details = [
            "Aguardando solicitar",
            "No portal de cadastro",
            "No portal de inspeção",
            data.get("nqt_code") or "Código do portal",
            "Dispensa" if decision == "dispensa" else "In loco" if decision == "inloco" else "Dispensa ou in loco",
            "PIT anexado" if decision == "dispensa" else (
                f"Visita {format_date(data.get('visit_date'))}" if data.get("visit_date") else "Visita do engenheiro"
            ) if decision == "inloco" else "A definir",
            "Equatorial gera o DOC",
        ]
        color = stage_colors(stage, self.service.palette)[0]
        steps = []
        for index, name in enumerate(TRAIL_NODES):
            state = STEP_DONE if index < current else STEP_CURRENT if index == current else STEP_PENDING
            steps.append({"name": name, "state": state, "label": details[index], "color": color})
        return steps

    def _progress_page(self) -> QWidget:
        data = self.data
        stage = data.get("stage") or ""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        flow_panel, flow_layout = make_panel("Fluxo da inspeção", highlight=True)
        self.trail = FlowTrail()
        self.trail.set_steps(self._trail_steps())
        flow_layout.addWidget(self.trail)
        layout.addWidget(flow_panel)

        panel, panel_layout = make_panel("Situação e andamento")
        self.step_label = QLabel(STAGE_HINTS.get(stage, ""))
        self.step_label.setWordWrap(True)
        panel_layout.addWidget(self.step_label)
        rows = [
            ("Etapa atual", stage_label(stage)),
            ("Desde", format_date(data.get("stage_since_date"))),
            ("Dias na etapa", days_text(data.get("days_in_stage"), business=data.get("business_days_in_stage"))),
        ]
        if data.get("visit_date"):
            rows.append(("Visita in loco", format_date(data.get("visit_date"))))
        panel_layout.addLayout(kv_grid(rows))
        if self.can_edit and stage != "fim":
            self.record_button = self._make_button("Registrar andamento", "edit", "primary", self.open_record)
            panel_layout.addWidget(self.record_button)
            self.catch_up_button = self._make_button("Atualizar atrasado", "refresh", "secondary", self.open_catch_up)
            panel_layout.addWidget(self.catch_up_button)
            if stage == "inloco":
                self.reschedule_button = self._make_button("Remarcar visita", "edit", "secondary", self.open_reschedule)
                panel_layout.addWidget(self.reschedule_button)
        elif not self.can_edit and stage != "fim":
            panel_layout.addWidget(QLabel("Você pode consultar, mas não registrar andamento nesta área."))
        self.error_label = set_notice_kind(QLabel(""), "danger")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        panel_layout.addWidget(self.error_label)
        layout.addWidget(panel)
        saved = [("PIT", data.get("pit_link") or ""), ("DOC BIM em PDF", data.get("doc_link") or "")]
        if any(path for _caption, path in saved):
            docs, docs_layout = make_panel("Documentos salvos")
            docs_layout.addWidget(path_rows_panel(saved))
            layout.addWidget(docs)
        layout.addStretch(1)
        return page

    def _history_page(self, events: list[dict]) -> QWidget:
        panel, layout = make_panel("Histórico")
        # Do mais antigo ao mais novo para achar o "de X para Y"; a tela mostra na ordem recebida.
        previous: dict[int, str | None] = {}
        last_stage: str | None = None
        for event in sorted(events, key=lambda e: (str(e.get("created_at") or ""), int(e.get("id") or 0))):
            previous[id(event)] = last_stage
            if event.get("kind", "transition") == "transition":
                last_stage = event.get("stage")
        self._events = events
        self.history_table = _read_only_table(["Aconteceu em", "Registrado em", "Quem", "Etapa", "Tentativa", "Registro"])
        self.history_table.setRowCount(len(events))
        for row, event in enumerate(events):
            values = [
                format_date(event.get("occurred_on")),
                format_moment(event.get("created_at")),
                event.get("actor_name") or EM_DASH,
                stage_label(event.get("stage") or ""),
                str(event.get("attempt", "")),
                history_registro(event, previous.get(id(event))),
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                self.history_table.setItem(row, column, cell)
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        self.history_table.resizeRowsToContents()
        layout.addWidget(self.history_table, 1)
        if self.can_edit:
            self.correct_button = self._make_button("Corrigir data do andamento", "edit", "secondary", self.open_correct_event)
            layout.addWidget(self.correct_button)
        return panel


class NewInspectionDialog(QDialog):
    """Abre a inspecao de um PD. A API exige PD existente em proposta ativa;
    a inspecao nasce em "Solicitação pendente"."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.api = service.inspection_service()
        self.created: dict | None = None
        self._busy = False
        self.setWindowTitle("Nova inspeção")
        self.setMinimumWidth(480)
        style_dialog_from_parent(self, parent)
        root = dialog_layout(self)
        root.addWidget(dialog_header("Nova inspeção", "Informe o PD principal do pedido."))
        panel, layout = make_panel()
        layout.addWidget(QLabel("PD principal"))
        self.pd_field = QLineEdit()
        self.pd_field.setPlaceholderText("Número do PD")
        self.pd_field.setMinimumHeight(34)
        self.pd_field.setAccessibleName("PD principal")
        self.pd_field.returnPressed.connect(self.submit)
        layout.addWidget(self.pd_field)
        self.error_label = set_notice_kind(QLabel(""), "danger")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)
        root.addWidget(panel)
        cancel = ModernButton("Cancelar", "close", variant="ghost")
        cancel.clicked.connect(self.reject)
        self.create_button = ModernButton("Criar inspeção", "check", variant="primary")
        self.create_button.clicked.connect(self.submit)
        root.addWidget(dialog_footer(right=[cancel, self.create_button]))
        self.pd_field.setFocus()

    def submit(self) -> None:
        if self._busy:
            return
        pd_code = self.pd_field.text().strip()
        if not pd_code:
            self._fail("Informe o PD principal.")
            return
        self._busy = True
        self.create_button.setEnabled(False)
        start_worker(self, lambda: self.api.create(pd_code), self._done, self._error)

    def _done(self, detail: dict) -> None:
        self.created = detail
        self.accept()

    def _error(self, exc: Exception) -> None:
        self._busy = False
        self.create_button.setEnabled(True)
        self._fail(str(exc))

    def _fail(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)
        set_validation_state(self.pd_field, "error")
        self.pd_field.setFocus()


PD_SOURCE_LABELS = {"order_reference": "do Pedido da proposta", "project_name": "extraído de Obra/Site"}


class InspectionStartDialog(QDialog):
    """"Iniciar inspeção" a partir de uma proposta (linha "A solicitar" ou ação do Controle Geral).
    Mostra o PD sugerido pela API, deixa confirmar/digitar o PD e pede confirmação
    explícita quando o PD já é Pedido de outro cliente. `result` guarda a resposta da API
    (InspectionDetail + `created`); `created` é False quando o PD já tinha inspeção."""

    def __init__(self, service, proposal_id: int, parent=None, *, proposal_label: str = ""):
        super().__init__(parent)
        self.service = service
        self.api = service.inspection_service()
        self.proposal_id = int(proposal_id)
        self.result: dict | None = None
        self.suggestion: dict = {}
        self._busy = False
        self._locked_pd = False
        self.setWindowTitle("Iniciar inspeção")
        self.setMinimumWidth(520)
        style_dialog_from_parent(self, parent)
        root = dialog_layout(self)
        root.addWidget(dialog_header("Iniciar inspeção", "Confirme o PD que vai para a inspeção."))
        panel, layout = make_panel()
        self.proposal_label = QLabel(proposal_label or "Carregando a proposta...")
        self.proposal_label.setWordWrap(True)
        layout.addWidget(self.proposal_label)
        layout.addWidget(QLabel("PD principal"))
        self.pd_field = QLineEdit()
        self.pd_field.setPlaceholderText("Número do PD")
        self.pd_field.setMinimumHeight(34)
        self.pd_field.setAccessibleName("PD principal")
        self.pd_field.setEnabled(False)
        self.pd_field.returnPressed.connect(self.submit)
        layout.addWidget(self.pd_field)
        self.source_label = QLabel("")
        self.source_label.setObjectName("Caption")
        layout.addWidget(self.source_label)
        self.notice_label = set_notice_kind(QLabel(""), "warning")
        self.notice_label.setWordWrap(True)
        self.notice_label.setVisible(False)
        layout.addWidget(self.notice_label)
        self.error_label = set_notice_kind(QLabel(""), "danger")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)
        root.addWidget(panel)
        cancel = ModernButton("Cancelar", "close", variant="ghost")
        cancel.clicked.connect(self.reject)
        self.start_button = ModernButton("Iniciar inspeção", "check", variant="primary")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(lambda _=False: self.submit())
        root.addWidget(dialog_footer(right=[cancel, self.start_button]))
        start_worker(self, lambda: self.api.pd_suggestion(self.proposal_id), self._suggested, self._suggest_failed)

    @property
    def created(self) -> bool:
        return bool(self.result is not None and self.result.get("created", True))

    # ---- sugestao ----------------------------------------------------------
    def _suggested(self, data: dict) -> None:
        self.suggestion = dict(data)
        self.proposal_label.setText(f"Proposta {data.get('proposal_number') or ''} · {data.get('customer_name') or ''}")
        if data.get("pd_code"):
            self.pd_field.setText(str(data["pd_code"]))
            self.source_label.setText(f"PD sugerido ({PD_SOURCE_LABELS.get(data.get('pd_source'), 'sugestão')}).")
        else:
            self.source_label.setText("Nenhum PD identificado com segurança. Digite o PD.")
        if data.get("order_reference"):
            self._lock_pd(str(data["order_reference"]))
        notices = []
        if data.get("existing_inspection_id"):
            notices.append("Já existe inspeção para este PD. Ao confirmar, ela será aberta.")
        if data.get("conflicting_proposals"):
            notices.append("Esse PD já é Pedido de outro cliente: " + self._proposals_text(data["conflicting_proposals"]) + ".")
        if notices:
            self.notice_label.setText(" ".join(notices))
            self.notice_label.setVisible(True)
        if data.get("is_cancelled"):
            self._fail("A proposta está cancelada e não pode entrar na inspeção.")
            self.pd_field.setEnabled(False)
            return
        self.pd_field.setEnabled(not self._locked_pd)
        self.start_button.setEnabled(True)
        self.pd_field.setFocus()

    def _suggest_failed(self, exc: Exception) -> None:
        self.proposal_label.setText("Não foi possível carregar a proposta.")
        self._fail(str(exc))

    @staticmethod
    def _proposals_text(proposals: list[dict]) -> str:
        return "; ".join(f"{p.get('proposal_number', '')} ({p.get('customer_name', '')})" for p in proposals)

    def _lock_pd(self, order_reference: str) -> None:
        self._locked_pd = True
        self.pd_field.setText(order_reference)
        self.pd_field.setEnabled(False)
        self.source_label.setText("O PD é o Pedido da proposta e não pode ser trocado aqui.")

    # ---- envio -------------------------------------------------------------
    def submit(self, confirm_conflict: bool = False) -> None:
        if self._busy or not self.start_button.isEnabled():
            return
        confirm = confirm_conflict is True
        pd_code = self.pd_field.text().strip()
        if not pd_code:
            self._fail("Informe o PD principal.")
            return
        self.error_label.setVisible(False)
        set_validation_state(self.pd_field, "")
        self._busy = True
        self.start_button.setEnabled(False)
        start_worker(
            self,
            lambda: self.api.start_from_proposal(self.proposal_id, pd_code, confirm),
            self._done,
            self._error,
        )

    def _done(self, detail: dict) -> None:
        self.result = detail
        if not self.created:
            QMessageBox.information(self, "Iniciar inspeção", "Já existia uma inspeção para esse PD. Vamos abrir a existente.")
        self.accept()

    def _error(self, exc: Exception) -> None:
        self._busy = False
        self.start_button.setEnabled(True)
        code = getattr(exc, "error_code", None)
        details = getattr(exc, "details", None) or {}
        if code == "INSPECTION_PD_CUSTOMER_CONFLICT":
            names = self._proposals_text(details.get("proposals") or [])
            answer = QMessageBox.question(
                self,
                "Iniciar inspeção",
                f"Esse PD já é Pedido de proposta de outro cliente: {names}.\n\nConfirma usar o mesmo PD?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer == QMessageBox.Yes:
                self.submit(confirm_conflict=True)
            return
        if code == "INSPECTION_PD_DIFFERS_FROM_ORDER" and details.get("order_reference"):
            self._lock_pd(str(details["order_reference"]))
        if code == "PROPOSAL_CANCELLED_TERMINAL":
            self.start_button.setEnabled(False)
            self.pd_field.setEnabled(False)
        self._fail(str(exc))

    def _fail(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)
        set_validation_state(self.pd_field, "error")


def start_inspection_for_proposal(service, proposal_id: int, parent=None, *, proposal_label: str = "") -> bool:
    """Abre o diálogo "Iniciar inspeção". Se o PD já tinha inspeção, abre a existente.
    Devolve True quando a API gravou algo (a lista deve recarregar)."""
    dialog = InspectionStartDialog(service, proposal_id, parent, proposal_label=proposal_label)
    if not dialog.exec() or dialog.result is None:
        return False
    if not dialog.created:
        InspectionDetailDialog(service, dialog.result, parent).exec()
    return True
