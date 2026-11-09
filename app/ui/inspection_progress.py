"""Registrar andamento da inspecao (uma etapa) e "Atualizar atrasado" (varias etapas de uma vez).

Cada etapa tem os resultados possiveis (`OUTCOMES`); o usuario escolhe o que aconteceu, preenche
so os campos desse resultado, diz QUANDO aconteceu (qualquer data) e registra. Avisos de data da
API (409) aparecem num painel dentro da propria janela: "Marcar mesmo assim / Escolher outra data".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services.inspection_service import LINK_MAX_LENGTH, STAGE_LABELS
from app.ui.background_worker import start_worker
from app.ui.components.date_quick_field import DateQuickField
from app.ui.components.detail_widgets import make_panel
from app.ui.components.dialog_shell import dialog_footer, dialog_header, dialog_layout, set_notice_kind
from app.ui.components.modern_button import ModernButton
from app.ui.components.path_field import PathField
from app.ui.date_warnings import CHOOSE_AGAIN_TEXT, CONFIRM_TEXT, date_warning_messages
from app.ui.dialog_utils import style_dialog_from_parent

MAX_CATCH_UP_STEPS = 20
NOTE_MAX_LENGTH = 1000
STALE_ERROR_CODE = "INSPECTION_INVALID_STAGE"
STALE_NOTICE = "A inspeção mudou de etapa; os dados foram atualizados."


@dataclass(frozen=True)
class Outcome:
    key: str
    label: str
    action: str  # rota da API: request, register-pd, nqt, decision, pit, approve, reject, doc
    to: str  # etapa seguinte
    fixed: dict[str, Any] = field(default_factory=dict)  # campos constantes do corpo
    fields: tuple[str, ...] = ()  # campos que o usuario preenche: nqt_code, visit_date, pit_link, doc_link, reason


# Resultados possiveis por etapa (a ordem das etapas e o contrato da API; D1..D18 da spec).
OUTCOMES: dict[str, tuple[Outcome, ...]] = {
    "pendente": (
        Outcome("requested", "Solicitei no portal (PD já cadastrado)", "request", "solicitada", {"pd_registered": True}),
        Outcome("needs_pd", "Solicitei, mas o PD ainda não está cadastrado", "request", "cadastro", {"pd_registered": False}),
    ),
    "cadastro": (Outcome("pd_registered", "PD cadastrado no portal", "register-pd", "solicitada"),),
    "solicitada": (Outcome("nqt", "O portal gerou o NQT", "nqt", "nqt", fields=("nqt_code",)),),
    "nqt": (
        Outcome("dispensed", "Equatorial dispensou", "decision", "dispensa", {"decision": "dispensa"}),
        Outcome("on_site", "Inspeção in loco", "decision", "inloco", {"decision": "inloco"}, ("visit_date",)),
    ),
    "dispensa": (Outcome("pit", "PIT anexado", "pit", "doc", fields=("pit_link",)),),
    "inloco": (
        Outcome("approved", "Aprovada", "approve", "doc"),
        Outcome("rejected", "Reprovada", "reject", "pendente", fields=("reason",)),
    ),
    "doc": (Outcome("doc", "DOC BIM em PDF recebido", "doc", "fim", fields=("doc_link",)),),
}

FIELD_CAPTIONS = {
    "nqt_code": "Código NQT",
    "visit_date": "Data da visita",
    "pit_link": "Arquivo ou pasta do PIT",
    "doc_link": "Arquivo ou pasta do DOC BIM em PDF",
    "reason": "Motivo da reprovação",
}
LINK_WHAT = {"pit_link": "PIT", "doc_link": "DOC BIM em PDF"}


def stage_name(stage: str) -> str:
    return STAGE_LABELS.get(stage, stage)


class OutcomeForm(QFrame):
    """Um andamento: "O que aconteceu?", campos so do resultado escolhido, "Aconteceu em" e observacao."""

    changed = Signal()  # qualquer campo mudou (esconde o painel de avisos de data)

    def __init__(self, stage: str, parent=None, *, title: str = ""):
        super().__init__(parent)
        self.stage = stage
        self.outcomes = OUTCOMES.get(stage, ())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        if title:
            heading = QLabel(title)
            heading.setObjectName("SectionTitle")
            layout.addWidget(heading)
        layout.addWidget(QLabel("O que aconteceu?"))
        self.group = QButtonGroup(self)
        self.radios: dict[str, QRadioButton] = {}
        for outcome in self.outcomes:
            radio = QRadioButton(outcome.label)
            radio.setAccessibleName(outcome.label)
            self.group.addButton(radio)
            self.radios[outcome.key] = radio
            layout.addWidget(radio)
            radio.toggled.connect(lambda _checked=False: self._sync_fields())
        self.field_widgets: dict[str, QWidget] = {}
        self.field_labels: dict[str, QLabel] = {}
        for name, caption in FIELD_CAPTIONS.items():
            label = QLabel(caption)
            if name in LINK_WHAT:
                widget: QWidget = PathField(f"Escolha o arquivo ou a pasta do {LINK_WHAT[name]}", caption)
            elif name == "visit_date":
                widget = DateQuickField(caption.lower(), shortcuts=False)
            else:
                widget = QLineEdit()
                widget.setMinimumHeight(34)
                widget.setAccessibleName(caption)
                widget.setPlaceholderText("NQT-0000" if name == "nqt_code" else caption)
            self.field_labels[name] = label
            self.field_widgets[name] = widget
            layout.addWidget(label)
            layout.addWidget(widget)
        layout.addWidget(QLabel("Aconteceu em"))
        self.occurred = DateQuickField("quando aconteceu", initial=date.today())
        layout.addWidget(self.occurred)
        layout.addWidget(QLabel("Observação (opcional)"))
        self.note = QLineEdit()
        self.note.setMinimumHeight(34)
        self.note.setMaxLength(NOTE_MAX_LENGTH)
        self.note.setAccessibleName("Observação")
        layout.addWidget(self.note)
        if self.outcomes:
            self.radios[self.outcomes[0].key].setChecked(True)
        self._sync_fields()
        for radio in self.radios.values():
            radio.toggled.connect(lambda *_: self.changed.emit())
        self.occurred.changed.connect(self.changed)
        self.note.textChanged.connect(lambda *_: self.changed.emit())
        for widget in self.field_widgets.values():
            line = widget.line if isinstance(widget, (DateQuickField, PathField)) else widget
            line.textChanged.connect(lambda *_: self.changed.emit())

    def focus_line(self) -> QLineEdit:
        """Campo de data a focar: a da visita, se aparece; senao "Aconteceu em"."""
        visit = self.field_widgets["visit_date"]
        return (visit if not visit.isHidden() else self.occurred).line

    def outcome(self) -> Outcome | None:
        return next((o for o in self.outcomes if self.radios[o.key].isChecked()), None)

    def next_stage(self) -> str | None:
        chosen = self.outcome()
        return chosen.to if chosen else None

    def _sync_fields(self) -> None:
        chosen = self.outcome()
        wanted = set(chosen.fields) if chosen else set()
        for name, widget in self.field_widgets.items():
            widget.setVisible(name in wanted)
            self.field_labels[name].setVisible(name in wanted)

    def _value(self, name: str) -> str:
        widget = self.field_widgets[name]
        if isinstance(widget, DateQuickField):
            return widget.date_iso("a data da visita")
        text = widget.text().strip()
        if name in LINK_WHAT:
            if not text:
                raise ValueError(f"Informe o link ou caminho do {LINK_WHAT[name]}.")
            if len(text) > LINK_MAX_LENGTH:
                raise ValueError(f"O link do {LINK_WHAT[name]} passa de {LINK_MAX_LENGTH} caracteres.")
        elif not text:
            raise ValueError("Informe o código NQT." if name == "nqt_code" else "Informe o motivo da reprovação.")
        return text.upper() if name == "nqt_code" else text

    def body(self) -> dict[str, Any]:
        """Corpo do POST da etapa (sem `action`). Levanta ValueError com a mensagem pronta."""
        chosen = self.outcome()
        if chosen is None:
            raise ValueError("Escolha o que aconteceu.")
        payload: dict[str, Any] = dict(chosen.fixed)
        for name in chosen.fields:
            payload[name] = self._value(name)
        payload["occurred_on"] = self.occurred.date_iso("quando aconteceu")
        note = self.note.text().strip()
        if note:
            payload["note"] = note
        return payload

    def step(self) -> dict[str, Any]:
        """Passo do catch-up: o corpo mais `action`."""
        chosen = self.outcome()
        body = self.body()
        return {"action": chosen.action, **body}  # type: ignore[union-attr]


def _parents(widget: QWidget):
    while (widget := widget.parentWidget()) is not None:
        yield widget


class DateWarningPanel(QFrame):
    """Avisos de data da API dentro da propria janela (sem QMessageBox). "Marcar mesmo assim" chama
    `on_confirm`; "Escolher outra data" fecha o painel e devolve o foco a `focus_target()`."""

    def __init__(self, on_confirm, focus_target, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.label = set_notice_kind(QLabel(""), "warning")
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        row = QHBoxLayout()
        row.addStretch(1)
        self.choose_button = ModernButton(CHOOSE_AGAIN_TEXT, "edit", variant="secondary")
        self.confirm_button = ModernButton(CONFIRM_TEXT, "check", variant="secondary")
        self.choose_button.clicked.connect(lambda _=False: self.dismiss(focus=True))
        self.confirm_button.clicked.connect(lambda _=False: (self.dismiss(), on_confirm()))
        row.addWidget(self.choose_button)
        row.addWidget(self.confirm_button)
        layout.addLayout(row)
        self._focus_target = focus_target
        self.setVisible(False)

    def show_messages(self, messages: list[str]) -> None:
        self.label.setText("\n\n".join(messages))
        self.setVisible(True)
        area = next((p for p in _parents(self) if isinstance(p, QScrollArea)), None)
        if area is not None:  # o layout so se ajusta no proximo ciclo
            QTimer.singleShot(0, self, lambda: area.ensureWidgetVisible(self))

    def dismiss(self, focus: bool = False) -> None:
        self.setVisible(False)
        target = self._focus_target() if focus else None
        if target is not None:
            target.setFocus()


def _show_date_warning(dialog, exc: Exception) -> bool:
    """True se `exc` era o 409 de datas (mostrado no painel da janela)."""
    messages = date_warning_messages(exc)
    if messages is None:
        return False
    dialog.warning_panel.show_messages(messages)
    return True


class RecordProgressDialog(QDialog):
    """"Registrar andamento": uma etapa por vez. `result_data` guarda o InspectionDetail devolvido."""

    def __init__(self, service, inspection: dict, parent=None):
        super().__init__(parent)
        self.service = service
        self.api = service.inspection_service()
        self.inspection = dict(inspection)
        self.stage = self.inspection.get("stage") or ""
        self.result_data: dict | None = None
        self.stale = False  # a inspecao mudou de etapa: quem abriu recarrega
        self._busy = False
        self.setWindowTitle("Registrar andamento")
        self.setMinimumWidth(560)
        style_dialog_from_parent(self, parent)
        root = dialog_layout(self)
        days = int(self.inspection.get("days_in_stage") or 0)
        root.addWidget(
            dialog_header(
                "Registrar andamento",
                f"PD {self.inspection.get('pd_code', '')} · etapa atual: {stage_name(self.stage)} · {days} {'dia' if days == 1 else 'dias'} nela",
            )
        )
        panel, layout = make_panel()
        self.form = OutcomeForm(self.stage)
        self.form.group.buttonToggled.connect(lambda *_: self._sync_summary())
        layout.addWidget(self.form)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.error_label = set_notice_kind(QLabel(""), "danger")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)
        self.warning_panel = DateWarningPanel(lambda: self.submit(True), lambda: self.form.focus_line())
        self.form.changed.connect(lambda: self.warning_panel.dismiss())
        layout.addWidget(self.warning_panel)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(panel)
        root.addWidget(scroll, 1)
        cancel = ModernButton("Cancelar", "close", variant="ghost")
        cancel.clicked.connect(self.reject)
        self.catch_up_button = ModernButton("Atualizar atrasado", "refresh", variant="secondary")
        self.catch_up_button.clicked.connect(self._open_catch_up)
        self.register_button = ModernButton("Registrar", "check", variant="primary")
        self.register_button.clicked.connect(lambda _=False: self.submit())
        self.register_button.setEnabled(bool(self.form.outcomes))
        root.addWidget(dialog_footer(left=[self.catch_up_button], right=[cancel, self.register_button]))
        self._sync_summary()

    def _sync_summary(self) -> None:
        nxt = self.form.next_stage()
        self.summary.setText(f"Vai acontecer: {stage_name(self.stage)} → {stage_name(nxt)}" if nxt else "Esta inspeção já foi finalizada.")

    def _open_catch_up(self) -> None:
        dialog = CatchUpDialog(self.service, self.inspection, self)
        if dialog.exec() and dialog.result_data is not None:
            self.result_data = dialog.result_data
            self.accept()
        elif dialog.stale:
            self.stale = True
            self.reject()

    def submit(self, confirm_dates: bool = False) -> None:
        if self._busy:
            return
        self.error_label.setVisible(False)
        self.warning_panel.dismiss()
        chosen = self.form.outcome()
        try:
            body = self.form.body()
        except ValueError as exc:
            self._fail(str(exc))
            return
        if confirm_dates:
            body["confirm_dates"] = True
        self._busy = True
        self.register_button.setEnabled(False)
        inspection_id = int(self.inspection["id"])
        start_worker(
            self,
            lambda: self.api.transition(inspection_id, chosen.action, body),
            self._done,
            lambda exc: self._error(exc),
        )

    def _done(self, detail: dict) -> None:
        self.result_data = detail
        self.accept()

    def _error(self, exc: Exception) -> None:
        self._busy = False
        self.register_button.setEnabled(True)
        if _show_date_warning(self, exc):
            return
        if getattr(exc, "error_code", None) == STALE_ERROR_CODE:
            self.stale = True
            self.reject()
            return
        self._fail(str(exc))

    def _fail(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)


class CatchUpDialog(QDialog):
    """"Atualizar atrasado": varias etapas seguidas, cada uma com a sua data real, enviadas de uma vez
    (POST catch-up, atomico). Trocar o resultado de uma etapa descarta as seguintes."""

    def __init__(self, service, inspection: dict, parent=None):
        super().__init__(parent)
        self.service = service
        self.api = service.inspection_service()
        self.inspection = dict(inspection)
        self.result_data: dict | None = None
        self.rows: list[OutcomeForm] = []
        self.stale = False  # a inspecao mudou de etapa: quem abriu recarrega
        self._busy = False
        self.setWindowTitle("Atualizar atrasado")
        self.setMinimumSize(600, 460)
        style_dialog_from_parent(self, parent)
        root = dialog_layout(self)
        root.addWidget(
            dialog_header(
                "Atualizar atrasado",
                f"PD {self.inspection.get('pd_code', '')} · hoje está em: {stage_name(self.inspection.get('stage') or '')}. "
                "Registre as etapas que já aconteceram, cada uma com a data em que aconteceu.",
            )
        )
        body = QWidget()
        self._rows_layout = QVBoxLayout(body)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(12)
        self._rows_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        self.add_button = ModernButton("Adicionar etapa", "new", variant="secondary")
        self.add_button.clicked.connect(lambda _=False: self.add_row())
        self.remove_button = ModernButton("Remover última", "remove", variant="ghost")
        self.remove_button.clicked.connect(lambda _=False: self._remove_last())
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.error_label = set_notice_kind(QLabel(""), "danger")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)
        self.warning_panel = DateWarningPanel(lambda: self.submit(True), lambda: next((r for r in self.rows if not r.field_widgets["visit_date"].isHidden()), self.rows[0]).focus_line())
        root.addWidget(self.warning_panel)
        cancel = ModernButton("Cancelar", "close", variant="ghost")
        cancel.clicked.connect(self.reject)
        self.register_button = ModernButton("Registrar tudo", "check", variant="primary")
        self.register_button.clicked.connect(lambda _=False: self.submit())
        root.addWidget(dialog_footer(left=[self.summary], right=[self.add_button, self.remove_button, cancel, self.register_button]))
        self.add_row()

    def _stage_after(self, index: int) -> str:
        """Etapa em que a linha `index` acontece (a atual da inspecao ou a que a linha anterior deixa)."""
        if index == 0:
            return self.inspection.get("stage") or ""
        return self.rows[index - 1].next_stage() or "fim"

    def add_row(self) -> None:
        stage = self._stage_after(len(self.rows))
        if not OUTCOMES.get(stage) or len(self.rows) >= MAX_CATCH_UP_STEPS:
            return
        form = OutcomeForm(stage, title=f"Etapa {len(self.rows) + 1}: {stage_name(stage)}")
        form.changed.connect(lambda: self.warning_panel.dismiss())
        form.group.buttonToggled.connect(lambda *_a, f=form: self._outcome_changed(f))
        self.rows.append(form)
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, form)
        self._sync()

    def _outcome_changed(self, form: OutcomeForm) -> None:
        index = self.rows.index(form)
        while len(self.rows) > index + 1:
            self._remove_last()
        self._sync()

    def _remove_last(self) -> None:
        if len(self.rows) <= 1:
            return
        form = self.rows.pop()
        self._rows_layout.removeWidget(form)
        form.setParent(None)
        form.deleteLater()
        self._sync()

    def _sync(self) -> None:
        last = self.rows[-1]
        can_add = bool(OUTCOMES.get(last.next_stage() or "fim")) and len(self.rows) < MAX_CATCH_UP_STEPS
        self.add_button.setEnabled(can_add)
        self.remove_button.setEnabled(len(self.rows) > 1)
        self.summary.setText(
            f"Vai acontecer: {stage_name(self.inspection.get('stage') or '')} → {stage_name(last.next_stage() or 'fim')} "
            f"({len(self.rows)} {'etapa' if len(self.rows) == 1 else 'etapas'})"
        )

    def submit(self, confirm_dates: bool = False) -> None:
        if self._busy:
            return
        self.error_label.setVisible(False)
        self.warning_panel.dismiss()
        steps = []
        for number, form in enumerate(self.rows, start=1):
            try:
                steps.append(form.step())
            except ValueError as exc:
                self._fail(f"Etapa {number}: {exc}")
                return
        self._busy = True
        self.register_button.setEnabled(False)
        inspection_id = int(self.inspection["id"])
        start_worker(
            self,
            lambda: self.api.catch_up(inspection_id, steps, confirm_dates),
            self._done,
            self._error,
        )

    def _done(self, detail: dict) -> None:
        self.result_data = detail
        self.accept()

    def _error(self, exc: Exception) -> None:
        self._busy = False
        self.register_button.setEnabled(True)
        if _show_date_warning(self, exc):
            return
        details = getattr(exc, "details", None)
        index = details.get("step_index") if isinstance(details, dict) else None
        # Etapa trocada so se o 1o passo falhou; nos seguintes a janela fica aberta com o erro no passo.
        if getattr(exc, "error_code", None) == STALE_ERROR_CODE and not index:
            self.stale = True
            self.reject()
            return
        # A API ja manda "Passo N" na mensagem; so prefixa quando nao veio.
        prefix = f"Etapa {int(index) + 1}: " if isinstance(index, int) and "Passo" not in str(exc) else ""
        self._fail(f"{prefix}{exc}")

    def _fail(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)
