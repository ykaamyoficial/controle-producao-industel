from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.logistics_service import LINK_MAX_LENGTH, LOG_STAGE_LABELS, STALE_ERROR_CODES
from app.ui.background_worker import start_worker
from app.ui.components.badge_delegate import BADGE_ROLE, BadgeColumnDelegate
from app.ui.components.detail_widgets import (
    EM_DASH,
    STEP_CURRENT,
    STEP_DONE,
    STEP_PENDING,
    CountTabWidget,
    FlowTrail,
    kv_grid,
    make_panel,
    stat_block,
)
from app.ui.components.dialog_shell import dialog_footer, dialog_header, dialog_layout, set_notice_kind, set_validation_state
from app.ui.components.modern_button import ModernButton
from app.ui.components.path_field import PathField, PathValue
from app.ui.components.status_badge import StatusBadge
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.inspection_dialogs import _read_only_table, days_text, fit_to_screen, format_date, format_moment, scrolled
from app.ui.styles import STATUS_BADGE_COLORS, _contrast_text, _is_dark

# Categoria de cor (STATUS_BADGE_COLORS) de cada etapa do LOG e de cada situacao de proposta.
LOG_STAGE_CATEGORY = {"reservada": "waiting", "docs": "attention", "aprovada": "done"}
ITEM_STATUS = {
    "ok": ("No LOG", "done"),
    "pendente": ("Inclusão pendente", "attention"),
    "reprovada": ("Inclusão reprovada", "danger"),
}
TRAIL_NODES = ("Data reservada", "Documentação enviada", "Aprovada para entrega")
TRAIL_POSITION = {"reservada": 1, "docs": 2, "aprovada": 3}
DATE_FORMAT = "%d/%m/%Y"
LOG_CODE_RE = re.compile(r"^LOG\d+$")


def category_colors(category: str, palette: dict) -> tuple[str, str]:
    """(fundo, texto) do selo de uma categoria, na paleta ativa."""
    colors = STATUS_BADGE_COLORS["escuro" if _is_dark(palette.get("bg", "#ffffff")) else "claro"]
    background = colors[category]
    return background, _contrast_text(background)


def log_stage_label(stage: str) -> str:
    return LOG_STAGE_LABELS.get(stage, stage or EM_DASH)


def log_stage_colors(stage: str, palette: dict) -> tuple[str, str]:
    return category_colors(LOG_STAGE_CATEGORY.get(stage, "neutral"), palette)


def parse_date(text: str, what: str) -> str:
    """DD/MM/AAAA digitado -> AAAA-MM-DD da API. Levanta ValueError (mensagem pronta) se vazia ou invalida."""
    text = text.strip()
    if not text:
        raise ValueError(f"Informe a {what}.")
    try:
        return datetime.strptime(text, DATE_FORMAT).date().isoformat()
    except ValueError:
        raise ValueError(f"{what.capitalize()} inválida. Use DD/MM/AAAA.") from None


def date_text(value: date) -> str:
    return value.strftime(DATE_FORMAT)


def _scroll_body(root: QVBoxLayout) -> QVBoxLayout:
    """Corpo rolável do formulário: o cabeçalho e o rodapé ficam fixos, só o miolo rola."""
    body = QWidget()
    layout = QVBoxLayout(body)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidget(body)
    root.addWidget(scroll, 1)
    return layout


def check_links(nf: str, xml: str, bim: str) -> tuple[str, str, str]:
    links = (nf.strip(), xml.strip(), bim.strip())
    if not all(links):
        raise ValueError("Informe os links de NF, XML e BIM.")
    if any(len(link) > LINK_MAX_LENGTH for link in links):
        raise ValueError(f"Cada link pode ter até {LINK_MAX_LENGTH} caracteres.")
    return links


def proposal_entry_text(p: dict) -> str:
    text = f"{p.get('proposal_number', '')}  {p.get('customer_name', '')}  ({p.get('pd_code') or EM_DASH})"
    return f"{text}  {p['state']}" if p.get("state") else text


class _Checklist(QScrollArea):
    """Lista de caixas de marcacao com id; `checked_ids()` devolve os marcados."""

    selection_changed = Signal()

    def __init__(self, empty_text: str, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setMinimumHeight(120)
        self.setMaximumHeight(220)
        self._empty_text = empty_text
        self.boxes: list[tuple[QCheckBox, int]] = []
        self.set_entries([])

    def set_entries(self, entries: list[tuple[int, str]]) -> None:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        self.boxes = []
        for entry_id, text in entries:
            box = QCheckBox(text)
            box.toggled.connect(lambda _=False: self.selection_changed.emit())
            layout.addWidget(box)
            self.boxes.append((box, int(entry_id)))
        if not entries:
            empty = QLabel(self._empty_text)
            empty.setWordWrap(True)
            layout.addWidget(empty)
        layout.addStretch(1)
        self.setWidget(body)

    def set_visible_ids(self, visible: set[int]) -> None:
        for box, entry_id in self.boxes:
            box.setHidden(entry_id not in visible)

    def checked_ids(self) -> list[int]:
        return [entry_id for box, entry_id in self.boxes if box.isChecked()]


class _DetailDialog(QDialog):
    """Base das janelas de detalhe: carrega pela API, redesenha com a resposta,
    bloqueia os botoes durante uma acao e mostra o erro da API no painel.
    `changed` fica True se algo foi gravado, para a lista recarregar."""

    changed_signal = Signal()

    def __init__(self, service, data: dict, parent=None, *, can_edit: bool | None = None):
        super().__init__(parent)
        self.service = service
        self.api = service.logistics_service()
        self.data: dict = dict(data)
        self.can_edit = bool(service.can_edit("logistics")) if can_edit is None else bool(can_edit)
        self.changed = False
        self._busy = False
        self._tab_index = 0
        self._notice = ""
        self._content: QWidget | None = None
        self._tabs: CountTabWidget | None = None
        self.error_label: QLabel | None = None  # o primeiro aviso da tela; os demais abas espelham o texto
        self._notice_labels: list[QLabel] = []
        self.action_buttons: list[ModernButton] = []
        self.setMinimumSize(760, 480)
        fit_to_screen(self, 1040, 640)
        style_dialog_from_parent(self, parent)
        self._root = dialog_layout(self)

    # ---- dados -----------------------------------------------------------
    def _fetch(self) -> dict:
        raise NotImplementedError

    def _build(self) -> QWidget:
        raise NotImplementedError

    def _reload(self) -> None:
        start_worker(self, self._fetch, self._apply, self._show_error)

    def _apply(self, detail: dict) -> None:
        self._busy = False
        self.data = dict(detail)
        self._render()

    def _show_error(self, exc: Exception) -> None:
        self._busy = False
        for button in self.action_buttons:
            button.setEnabled(True)
        self._set_notice(str(exc))
        if getattr(exc, "error_code", None) in STALE_ERROR_CODES:
            self._reload()

    def _set_notice(self, message: str) -> None:
        self._notice = message
        for label in self._notice_labels:
            label.setText(message)
            label.setVisible(bool(message))

    def _run(self, operation: Callable[[], Any], on_done: Callable[[Any], None] | None = None) -> None:
        if self._busy:
            return
        self._busy = True
        self._set_notice("")
        for button in self.action_buttons:
            button.setEnabled(False)
        start_worker(self, operation, on_done or self._after_action, self._show_error)

    def _after_action(self, detail: dict) -> None:
        self.changed = True
        self.changed_signal.emit()
        self._notice = ""
        self._apply(detail)

    def _invalid(self, message: str, field: QLineEdit | None = None) -> None:
        self._set_notice(message)
        if field is not None:
            set_validation_state(field, "error")
            field.setFocus()

    # ---- tela ------------------------------------------------------------
    def _render(self) -> None:
        if self._content is not None:
            if self._tabs is not None:
                self._tab_index = self._tabs.currentIndex()
            self._root.removeWidget(self._content)
            self._content.setParent(None)
            self._content.deleteLater()
        self.action_buttons = []
        self.error_label = None
        self._notice_labels = []
        self._tabs = None
        self._content = self._build()
        self._root.addWidget(self._content, 1)
        self._set_notice(self._notice)

    def _notice_label(self) -> QLabel:
        label = set_notice_kind(QLabel(""), "danger")
        label.setWordWrap(True)
        label.setVisible(False)
        self._notice_labels.append(label)
        if self.error_label is None:
            self.error_label = label
        return label

    def _make_button(self, text: str, icon: str, variant: str, handler: Callable[[], None]) -> ModernButton:
        button = ModernButton(text, icon, variant=variant)
        button.clicked.connect(lambda _=False: self._submit(handler))
        self.action_buttons.append(button)
        return button

    def _submit(self, handler: Callable[[], None]) -> None:
        self._set_notice("")
        try:
            handler()
        except ValueError as exc:
            self._invalid(str(exc))

    def _history_page(self, events: list[dict]) -> QWidget:
        panel, layout = make_panel("Histórico")
        self.history_table = _read_only_table(["Quando", "Quem", "Registro"])
        self.history_table.setRowCount(len(events))
        for row, event in enumerate(events):
            text = event.get("text") or ""
            if event.get("reason"):
                text = f"{text} Motivo: {event['reason']}" if text else f"Motivo: {event['reason']}"
            values = [format_moment(event.get("created_at")), event.get("actor_name") or EM_DASH, text]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                self.history_table.setItem(row, column, cell)
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.history_table.resizeRowsToContents()
        layout.addWidget(self.history_table, 1)
        return panel


class LogDetailDialog(_DetailDialog):
    """Detalhes do LOG: fluxo (data reservada, documentacao, aprovacao),
    propostas (inclusao pendente, remocao com motivo) e historico."""

    def __init__(self, service, log: dict, parent=None, *, can_edit: bool | None = None):
        super().__init__(service, log, parent, can_edit=can_edit)
        self._eligible: list[dict] = []
        self.doc_fields: dict[str, QLineEdit] = {}
        self.reason_field: QLineEdit | None = None
        self.items_table = None
        self.checklist: _Checklist | None = None
        self.setWindowTitle(f"LOG {self.data.get('code', '')}")
        self._render()
        self._reload()
        if self.can_edit:
            self._load_eligible()

    def _fetch(self) -> dict:
        return self.api.get_log(int(self.data["id"]))

    def _load_eligible(self) -> None:
        def loaded(result: dict) -> None:
            self._eligible = list(result.get("items") or [])
            self._fill_checklist()

        start_worker(self, lambda: self.api.eligible_proposals(), loaded, lambda _exc: None)

    def _fill_checklist(self) -> None:
        if self.checklist is not None:
            # O servidor recusa proposta de outro estado; sem estado derivavel entra em qualquer LOG.
            log_state = self.data.get("state")
            self.checklist.set_entries(
                [(p["id"], proposal_entry_text(p)) for p in self._eligible if not p.get("state") or p["state"] == log_state]
            )

    @property
    def in_load(self) -> bool:
        return self.data.get("load_id") is not None

    # ---- tela ------------------------------------------------------------
    def _build(self) -> QWidget:
        data = self.data
        stage = data.get("stage") or ""
        palette = self.service.palette
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        background, foreground = log_stage_colors(stage, palette)
        self.stage_badge = StatusBadge(log_stage_label(stage), background, foreground)
        self.days_label = QLabel(days_text(data.get("days_in_stage"), long=True))
        close = ModernButton("Fechar", "close", variant="ghost")
        close.clicked.connect(self.accept)
        buttons = []
        if self.can_edit and stage == "reservada":
            buttons.append(self._make_button("Documentação enviada", "check", "primary", self._send_docs))
        elif self.can_edit and stage == "docs":
            buttons.append(self._make_button("Tudo ok: data aprovada", "check_double", "primary", self._approve))
        layout.addWidget(
            dialog_header(
                f"{data.get('code', '')} | {data.get('state', '')}",
                f"Entrega no CD em {format_date(data.get('delivery_date'))} · carregamento em {format_date(data.get('loading_date'))}",
                status=[self.stage_badge, self.days_label],
                actions=[*buttons, close],
            )
        )

        items = list(data.get("items") or [])
        events = list(data.get("events") or [])
        tabs = CountTabWidget()
        tabs.addTab(scrolled(self._summary_page()), "Resumo")
        tabs.addTab(scrolled(self._proposals_page(items)), "Propostas", len(items))
        tabs.addTab(self._history_page(events), "Histórico", len(events))
        tabs.setCurrentIndex(min(self._tab_index, tabs.count() - 1))
        self._tabs = tabs
        layout.addWidget(tabs, 1)
        return content

    def _summary_page(self) -> QWidget:
        data = self.data
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        flow_panel, flow_layout = make_panel("Fluxo do LOG", highlight=True)
        current = TRAIL_POSITION.get(data.get("stage") or "", 1)
        details = [
            format_date(data.get("reserved_date")),
            "NF, XML e BIM" if data.get("nf_link") else "Falta enviar",
            "Tudo ok no portal",
        ]
        color = log_stage_colors(data.get("stage") or "", self.service.palette)[0]
        steps = [
            {
                "name": name,
                "state": STEP_DONE if index < current else STEP_CURRENT if index == current else STEP_PENDING,
                "label": details[index],
                "color": color,
            }
            for index, name in enumerate(TRAIL_NODES)
        ]
        self.trail = FlowTrail()
        self.trail.set_steps(steps)
        flow_layout.addWidget(self.trail)
        layout.addWidget(flow_panel)

        info, info_layout = make_panel("Dados do LOG")
        info_layout.addLayout(
            kv_grid(
                [
                    ("Código", data.get("code") or EM_DASH),
                    ("Estado", data.get("state") or EM_DASH),
                    ("Data pedida", format_date(data.get("requested_date"))),
                    ("Data reservada", format_date(data.get("reserved_date"))),
                    ("Carregamento no pátio", format_date(data.get("loading_date"))),
                    ("Entrega no CD", format_date(data.get("delivery_date"))),
                ]
            )
        )
        status, status_layout = make_panel("Situação atual")
        status_layout.addLayout(
            kv_grid(
                [
                    ("Etapa atual", StatusBadge(log_stage_label(data.get("stage") or ""), *log_stage_colors(data.get("stage") or "", self.service.palette))),
                    ("Dias na etapa", days_text(data.get("days_in_stage"))),
                    ("Propostas", str(data.get("proposal_count", len(data.get("items") or [])))),
                    ("Carga de entrega", data.get("load_code") or EM_DASH),
                    ("NF", PathValue(data["nf_link"]) if data.get("nf_link") else EM_DASH),
                    ("XML", PathValue(data["xml_link"]) if data.get("xml_link") else EM_DASH),
                    ("BIM", PathValue(data["bim_link"]) if data.get("bim_link") else EM_DASH),
                ]
            )
        )
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)
        row_layout.addWidget(info, 1)
        row_layout.addWidget(status, 1)
        layout.addWidget(row)

        self.doc_fields = {}
        if self.can_edit and data.get("stage") == "reservada":
            docs, docs_layout = make_panel("Enviar documentação ao portal")
            for key, caption in (("nf", "NF (arquivo ou pasta)"), ("xml", "XML (arquivo ou pasta)"), ("bim", "BIM (arquivo ou pasta)")):
                docs_layout.addWidget(QLabel(caption))
                path_field = PathField("Escolha o arquivo ou a pasta", caption)
                docs_layout.addWidget(path_field)
                self.doc_fields[key] = path_field.line
            layout.addWidget(docs)
        layout.addWidget(self._notice_label())
        layout.addStretch(1)
        return page

    def _proposals_page(self, items: list[dict]) -> QWidget:
        palette = self.service.palette
        self._items = items
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        panel, panel_layout = make_panel("Propostas do LOG")
        table = _read_only_table(["Proposta", "Cliente", "PD", "Situação"])
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setItemDelegateForColumn(3, BadgeColumnDelegate(table))
        table.setRowCount(len(items))
        for row, item in enumerate(items):
            label, category = ITEM_STATUS.get(item.get("status"), (item.get("status") or EM_DASH, "neutral"))
            values = [item.get("proposal_number") or EM_DASH, item.get("customer_name") or EM_DASH, item.get("pd_code") or EM_DASH, label]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setTextAlignment(Qt.AlignVCenter | (Qt.AlignCenter if column == 3 else Qt.AlignLeft))
                if column == 3:
                    cell.setData(BADGE_ROLE, category_colors(category, palette))
                table.setItem(row, column, cell)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        table.setColumnWidth(3, 190)
        table.itemSelectionChanged.connect(self._sync_item_buttons)
        self.items_table = table
        panel_layout.addWidget(table, 1)
        layout.addWidget(panel, 1)

        self.reason_field = None
        self.checklist = None
        if self.can_edit:
            self.approve_item_button = self._make_button("Aprovar inclusão", "check", "secondary", lambda: self._resolve("ok"))
            self.reject_item_button = self._make_button("Reprovar inclusão", "close", "secondary", lambda: self._resolve("reprovada"))
            self.remove_item_button = self._make_button("Remover proposta", "remove", "secondary", self._remove)
            if self.in_load:
                note = QLabel(f"Este LOG está na carga de entrega {self.data.get('load_code') or ''}. Desfaça a carga para remover propostas.")
                note.setWordWrap(True)
                panel_layout.addWidget(note)
                actions = [self.approve_item_button, self.reject_item_button]
            else:
                panel_layout.addWidget(QLabel("A remoção exige motivo. A proposta volta a ficar disponível e o vínculo antigo fica no histórico."))
                self.reason_field = QLineEdit()
                self.reason_field.setMinimumHeight(34)
                self.reason_field.setPlaceholderText("Motivo da remoção")
                self.reason_field.setAccessibleName("Motivo da remoção")
                panel_layout.addWidget(self.reason_field)
                actions = [self.approve_item_button, self.reject_item_button, self.remove_item_button]
            for button in actions:
                panel_layout.addWidget(button)
            include, include_layout = make_panel("Incluir novos pedidos")
            self.checklist = _Checklist(
                "Nenhuma proposta elegível. Só entram propostas com inspeção finalizada (DOC BIM em PDF) que ainda não estejam em um LOG."
            )
            include_layout.addWidget(self.checklist)
            include_layout.addWidget(self._make_button("Incluir no LOG", "new", "secondary", self._include))
            layout.addWidget(include)
            self._fill_checklist()
            layout.addWidget(self._notice_label())
        self._sync_item_buttons()
        return page

    # ---- selecao ---------------------------------------------------------
    def selected_item(self) -> dict | None:
        table = self.items_table
        rows = table.selectionModel().selectedRows() if table is not None and table.selectionModel() else []
        if not rows or not 0 <= rows[0].row() < len(self._items):
            return None
        return self._items[rows[0].row()]

    def _sync_item_buttons(self) -> None:
        if not self.can_edit or self._busy:
            return
        item = self.selected_item()
        pending = item is not None and item.get("status") == "pendente"
        self.approve_item_button.setEnabled(pending)
        self.reject_item_button.setEnabled(pending)
        self.remove_item_button.setEnabled(item is not None)

    # ---- acoes -----------------------------------------------------------
    def _log_id(self) -> int:
        return int(self.data["id"])

    def _send_docs(self) -> None:
        links = check_links(*(self.doc_fields[key].text() for key in ("nf", "xml", "bim")))
        self._run(lambda: self.api.send_docs(self._log_id(), *links))

    def _approve(self) -> None:
        self._run(lambda: self.api.approve_log(self._log_id()))

    def _resolve(self, result: str) -> None:
        item = self.selected_item()
        if item is None or item.get("status") != "pendente":
            raise ValueError("Selecione uma proposta com inclusão pendente.")
        self._run(lambda: self.api.resolve_item(self._log_id(), int(item["id"]), result))

    def _include(self) -> None:
        ids = self.checklist.checked_ids() if self.checklist is not None else []
        if not ids:
            raise ValueError("Escolha ao menos uma proposta.")

        def done(detail: dict) -> None:
            self._load_eligible()
            self._after_action(detail)

        self._run(lambda: self.api.add_proposals(self._log_id(), ids), done)

    def _remove(self) -> None:
        item = self.selected_item()
        if item is None:
            raise ValueError("Selecione a proposta que será removida.")
        reason = self.reason_field.text().strip() if self.reason_field is not None else ""
        if not reason:
            raise ValueError("Informe o motivo da remoção.")
        if len(self._items) == 1:
            answer = QMessageBox.question(
                self,
                "Remover última proposta",
                "Esta é a última proposta do LOG. Remover apaga o LOG. Continuar?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        def done(result: dict) -> None:
            self.changed = True
            self.changed_signal.emit()
            self._load_eligible()
            if result.get("log_deleted"):
                self.accept()
                return
            self._notice = ""
            self._apply(result.get("log") or self.data)

        self._run(lambda: self.api.remove_item(self._log_id(), int(item["id"]), reason), done)


class NewLogDialog(QDialog):
    """Registra o LOG que o portal da Equatorial gerou. Nasce em "Data reservada"."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.api = service.logistics_service()
        self.created: dict | None = None
        self._busy = False
        self._eligible: list[dict] = []
        self.setWindowTitle("Novo LOG")
        self.setMinimumSize(640, 420)
        fit_to_screen(self, 900, 640)
        style_dialog_from_parent(self, parent)
        root = dialog_layout(self)
        root.addWidget(dialog_header("Novo LOG", "Registre o LOG que o portal gerou"))
        body = _scroll_body(root)

        panel, layout = make_panel("Escolha da data no portal")
        note = QLabel(
            "No portal, escolha a data de entrega. Se estiver disponível, ela fica reservada e o portal gera o código LOG. "
            "Se não, escolha a data disponível mais próxima."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        today = date.today()
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        _, self.state_field = self._field(grid, 0, 0, "Estado da Equatorial", "Definido pela proposta escolhida")
        self.state_field.setReadOnly(True)  # automatico; so editavel se a proposta escolhida nao tem estado
        _, self.code_field = self._field(grid, 0, 1, "Código LOG (gerado no portal)", "LOG103")
        _, self.requested_field = self._field(grid, 1, 0, "Data pedida", "DD/MM/AAAA", date_text(today + timedelta(days=25)))
        self.available = QCheckBox("A data pedida estava disponível (ficou reservada)")
        self.available.setChecked(True)
        self.available.toggled.connect(self._toggle_reserved)
        grid.addWidget(self.available, 1, 1, Qt.AlignBottom)
        self.reserved_caption, self.reserved_field = self._field(
            grid, 2, 0, "Data mais próxima (reservada)", "DD/MM/AAAA", date_text(today + timedelta(days=28))
        )
        _, self.loading_field = self._field(grid, 3, 0, "Carregamento no pátio Industel", "DD/MM/AAAA", date_text(today + timedelta(days=24)))
        _, self.delivery_field = self._field(grid, 3, 1, "Entrega no CD da Equatorial", "DD/MM/AAAA", date_text(today + timedelta(days=25)))
        layout.addLayout(grid)
        self._toggle_reserved(True)
        body.addWidget(panel)

        proposals, proposals_layout = make_panel("Propostas neste LOG")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrar propostas...")
        self.search.setAccessibleName("Filtrar propostas")
        self.search.setMinimumHeight(34)
        self.search.textChanged.connect(self._apply_filter)
        proposals_layout.addWidget(self.search)
        self.checklist = _Checklist(
            "Nenhuma proposta elegível. Só entram propostas com inspeção finalizada (DOC BIM em PDF) que ainda não estejam em um LOG."
        )
        self.checklist.selection_changed.connect(self._sync_state)
        proposals_layout.addWidget(self.checklist)
        body.addWidget(proposals, 1)

        self.error_label = set_notice_kind(QLabel(""), "danger")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        body.addWidget(self.error_label)
        cancel = ModernButton("Cancelar", "close", variant="ghost")
        cancel.clicked.connect(self.reject)
        self.create_button = ModernButton("Registrar LOG", "check", variant="primary")
        self.create_button.clicked.connect(self.submit)
        root.addWidget(dialog_footer(right=[cancel, self.create_button]))
        self.code_field.setFocus()
        start_worker(self, lambda: self.api.eligible_proposals(), self._eligible_loaded, self._eligible_failed)

    def _field(self, grid: QGridLayout, row: int, column: int, caption: str, placeholder: str, value: str = "") -> tuple[QLabel, QLineEdit]:
        cell = QWidget()
        box = QVBoxLayout(cell)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        label = QLabel(caption)
        box.addWidget(label)
        field = QLineEdit(value)
        field.setPlaceholderText(placeholder)
        field.setMinimumHeight(34)
        field.setAccessibleName(caption)
        box.addWidget(field)
        grid.addWidget(cell, row, column)
        return label, field

    def _toggle_reserved(self, available: bool) -> None:
        self.reserved_caption.setVisible(not available)
        self.reserved_field.setVisible(not available)

    def _eligible_loaded(self, result: dict) -> None:
        self._eligible = list(result.get("items") or [])
        self._fill_checklist()

    def _eligible_failed(self, exc: Exception) -> None:
        self._fail(str(exc))

    def _fill_checklist(self, *_args) -> None:
        self.checklist.set_entries([(p["id"], proposal_entry_text(p)) for p in self._eligible])
        self._apply_filter()

    def _sync_state(self) -> None:
        """Estado vem da proposta marcada; sem marcacao limpa. Proposta sem estado libera o campo (fallback)."""
        checked = set(self.checklist.checked_ids())
        states = {p["state"] for p in self._eligible if p["id"] in checked and p.get("state")}
        if not checked:
            self.state_field.clear()
        elif states:
            self.state_field.setText(sorted(states)[0])
        self.state_field.setReadOnly(not checked or bool(states))
        self._apply_filter()

    def _apply_filter(self, *_args) -> None:
        """Texto de busca + mesmo estado da selecao (o servidor recusa estados diferentes ou derivavel misturado com sem-estado)."""
        checked = set(self.checklist.checked_ids())
        locked = checked and next((p.get("state") for p in self._eligible if p["id"] in checked), None)
        needle = self.search.text().strip().lower()
        self.checklist.set_visible_ids(
            {
                p["id"]
                for p in self._eligible
                if (not checked or (p.get("state") or None) == (locked or None))
                and (not needle or needle in " ".join(str(p.get(k) or "") for k in ("proposal_number", "customer_name", "pd_code", "project_name", "state")).lower())
            }
        )

    def payload(self) -> dict[str, Any]:
        """Valida o formulario e monta o corpo de POST /logs. Levanta ValueError com a mensagem."""
        code = self.code_field.text().strip().upper()
        if not LOG_CODE_RE.match(code):
            raise ValueError("O código deve ser LOG seguido de números, ex.: LOG103.")
        state = self.state_field.text().strip().upper()
        if not state:
            raise ValueError("Informe o estado da Equatorial.")
        payload: dict[str, Any] = {
            "code": code,
            "state": state,
            "requested_date": parse_date(self.requested_field.text(), "data pedida"),
            "loading_date": parse_date(self.loading_field.text(), "data de carregamento"),
            "delivery_date": parse_date(self.delivery_field.text(), "data de entrega"),
        }
        if not self.available.isChecked():
            payload["reserved_date"] = parse_date(self.reserved_field.text(), "data reservada")
        ids = self.checklist.checked_ids()
        if not ids:
            raise ValueError("Escolha ao menos uma proposta.")
        payload["proposal_ids"] = ids
        return payload

    def submit(self) -> None:
        if self._busy:
            return
        self.error_label.setVisible(False)
        try:
            payload = self.payload()
        except ValueError as exc:
            self._fail(str(exc))
            return
        self._busy = True
        self.create_button.setEnabled(False)
        start_worker(self, lambda: self.api.create_log(payload), self._done, self._error)

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


class LoadDetailDialog(_DetailDialog):
    """Detalhes da carga de entrega: resumo, LOGs do caminhao, saida e historico.
    "Desfazer carga" apaga a carga e libera os LOGs."""

    def __init__(self, service, load: dict, parent=None, *, can_edit: bool | None = None):
        super().__init__(service, load, parent, can_edit=can_edit)
        self.deleted = False
        self.date_field: QLineEdit | None = None
        self.setWindowTitle(f"Carga de entrega {self.data.get('code', '')}")
        self._render()
        self._reload()

    def _fetch(self) -> dict:
        return self.api.get_load(int(self.data["id"]))

    def _build(self) -> QWidget:
        data = self.data
        palette = self.service.palette
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        close = ModernButton("Fechar", "close", variant="ghost")
        close.clicked.connect(self.accept)
        undo = []
        if self.can_edit:
            undo.append(self._make_button("Desfazer carga", "close", "secondary", self._undo))
        layout.addWidget(
            dialog_header(
                f"Carga de entrega {data.get('code', '')}",
                f"Saída do pátio em {format_date(data.get('departure_date'))}",
                actions=[*undo, close],
            )
        )

        logs = list(data.get("logs") or [])
        events = list(data.get("events") or [])
        summary = QWidget()
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(12)
        stats, stats_layout = make_panel()
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        states = sorted({log.get("state") for log in logs if log.get("state")})
        for number, caption in (
            (str(len(logs)), "LOGs na carga"),
            (str(data.get("proposal_count", 0)), "propostas"),
            (str(len(states)), "estados"),
            (format_date(data.get("departure_date")), "saída do pátio"),
        ):
            row_layout.addLayout(stat_block(number, caption))
        stats_layout.addWidget(row)
        summary_layout.addWidget(stats)

        if self.can_edit:
            edit, edit_layout = make_panel("Saída do pátio")
            self.date_field = QLineEdit(format_date(data.get("departure_date")))
            self.date_field.setMinimumHeight(34)
            self.date_field.setAccessibleName("Data de saída do pátio")
            edit_layout.addWidget(self.date_field)
            edit_layout.addWidget(self._make_button("Salvar data", "save", "secondary", self._save_date))
            summary_layout.addWidget(edit)

        self.retire_buttons: list[ModernButton] = []
        for log in logs:
            panel, panel_layout = make_panel(f"{log.get('code', '')} · {log.get('state', '')}", right=StatusBadge(log_stage_label(log.get("stage") or ""), *log_stage_colors(log.get("stage") or "", palette)))
            props = ", ".join(f"{i.get('proposal_number')} ({i.get('customer_name')})" for i in log.get("items") or []) or EM_DASH
            panel_layout.addLayout(
                kv_grid(
                    [
                        ("Carregamento no pátio", format_date(log.get("loading_date"))),
                        ("Entrega no CD", format_date(log.get("delivery_date"))),
                        ("Propostas", props),
                    ]
                )
            )
            if self.can_edit:
                button = self._make_button("Retirar da carga", "remove", "ghost", lambda log=log: self._retire(log))
                self.retire_buttons.append(button)
                panel_layout.addWidget(button)
            summary_layout.addWidget(panel)
        summary_layout.addWidget(self._notice_label())
        summary_layout.addStretch(1)

        tabs = CountTabWidget()
        tabs.addTab(scrolled(summary), "Resumo")
        tabs.addTab(self._history_page(events), "Histórico", len(events))
        tabs.setCurrentIndex(min(self._tab_index, tabs.count() - 1))
        self._tabs = tabs
        layout.addWidget(tabs, 1)
        return content

    def _load_id(self) -> int:
        return int(self.data["id"])

    def _save_date(self) -> None:
        text = self.date_field.text() if self.date_field is not None else ""
        departure = parse_date(text, "data de saída")
        self._run(lambda: self.api.update_load(self._load_id(), departure))

    def _retire(self, log: dict) -> None:
        if len(self.data.get("logs") or []) <= 1:
            raise ValueError('Este é o último LOG da carga. Use "Desfazer carga".')
        self._run(lambda: self.api.remove_log_from_load(self._load_id(), int(log["id"])))

    def _undo(self) -> None:
        answer = QMessageBox.question(
            self,
            "Desfazer carga",
            f"Desfazer a carga {self.data.get('code', '')}? Os LOGs ficam livres para outra carga.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        def done(_result: Any) -> None:
            self.changed = True
            self.deleted = True
            self.changed_signal.emit()
            self.accept()

        self._run(lambda: self.api.delete_load(self._load_id()), done)


class NewLoadDialog(QDialog):
    """Monta uma carga de entrega com LOGs aprovados e livres (podem ser de estados diferentes)."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.api = service.logistics_service()
        self.created: dict | None = None
        self._busy = False
        self._free_logs: list[dict] = []
        self.setWindowTitle("Nova carga de entrega")
        self.setMinimumSize(560, 420)
        fit_to_screen(self, 900, 560)
        style_dialog_from_parent(self, parent)
        root = dialog_layout(self)
        root.addWidget(dialog_header("Nova carga de entrega", "Reúna LOGs aprovados no mesmo caminhão"))
        body = _scroll_body(root)

        panel, layout = make_panel("Dados da carga")
        layout.addWidget(QLabel("Data de saída do pátio"))
        self.date_field = QLineEdit(date_text(date.today() + timedelta(days=23)))
        self.date_field.setPlaceholderText("DD/MM/AAAA")
        self.date_field.setMinimumHeight(34)
        self.date_field.setAccessibleName("Data de saída do pátio")
        layout.addWidget(self.date_field)
        body.addWidget(panel)

        logs_panel, logs_layout = make_panel("LOGs aprovados para entrega")
        hint = QLabel("Escolha os LOGs que vão no mesmo caminhão. Podem ser de estados diferentes.")
        hint.setWordWrap(True)
        logs_layout.addWidget(hint)
        self.checklist = _Checklist("Nenhum LOG aprovado e livre. Aprove um LOG na aba LOGs primeiro.")
        logs_layout.addWidget(self.checklist)
        body.addWidget(logs_panel, 1)

        self.error_label = set_notice_kind(QLabel(""), "danger")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        body.addWidget(self.error_label)
        cancel = ModernButton("Cancelar", "close", variant="ghost")
        cancel.clicked.connect(self.reject)
        self.create_button = ModernButton("Montar carga", "check", variant="primary")
        self.create_button.clicked.connect(self.submit)
        root.addWidget(dialog_footer(right=[cancel, self.create_button]))
        start_worker(
            self,
            lambda: self.api.list_logs(stage="aprovada", in_load=False, limit=200),
            self._logs_loaded,
            lambda exc: self._fail(str(exc)),
        )

    def _logs_loaded(self, result: dict) -> None:
        self._free_logs = list(result.get("items") or [])
        self.checklist.set_entries(
            [
                (
                    log["id"],
                    f"{log.get('code', '')}  {log.get('state', '')}  entrega {format_date(log.get('delivery_date'))}, {log.get('proposal_count', 0)} propostas",
                )
                for log in self._free_logs
            ]
        )

    def submit(self) -> None:
        if self._busy:
            return
        self.error_label.setVisible(False)
        ids = self.checklist.checked_ids()
        if not ids:
            self._fail("Escolha ao menos um LOG.")
            return
        try:
            departure = parse_date(self.date_field.text(), "data de saída")
        except ValueError as exc:
            self._fail(str(exc))
            set_validation_state(self.date_field, "error")
            return
        self._busy = True
        self.create_button.setEnabled(False)
        start_worker(self, lambda: self.api.create_load(departure, ids), self._done, self._error)

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
