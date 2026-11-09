"""Registrar andamento do LOG (uma etapa por vez). Mesmo desenho de `RecordProgressDialog` da Inspeção,
mas com os resultados do LOG: documentação enviada, aprovada para entrega e entregue no CD.
Avisos de data (409) aparecem no painel da própria janela; etapa desatualizada recarrega o LOG e
mantém o que o usuário já digitou."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QDialog, QFrame, QLabel, QLineEdit, QRadioButton, QScrollArea, QVBoxLayout

from app.services.logistics_service import LINK_MAX_LENGTH, LOG_STAGE_LABELS
from app.ui.background_worker import start_worker
from app.ui.components.date_quick_field import DateQuickField, local_today
from app.ui.components.detail_widgets import make_panel
from app.ui.components.dialog_shell import dialog_footer, dialog_header, dialog_layout, set_notice_kind
from app.ui.components.modern_button import ModernButton
from app.ui.components.path_field import PathField
from app.ui.date_warnings import date_warning_messages
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.inspection_progress import DateWarningPanel

NOTE_MAX_LENGTH = 1000
STALE_STAGE_CODE = "LOGISTICS_INVALID_STAGE"
FIELD_CAPTIONS = {
    "nf_link": "NF (arquivo ou pasta)",
    "xml_link": "XML (arquivo ou pasta)",
    "bim_link": "BIM (arquivo ou pasta)",
    "delivery_proof_link": "Comprovante da entrega (arquivo, pasta ou link)",
}


@dataclass(frozen=True)
class LogOutcome:
    key: str  # docs | approve | delivered
    label: str
    fields: tuple[str, ...] = ()  # campos que o usuario preenche nesse resultado


DELIVERED = LogOutcome("delivered", "Entregue no CD", ("delivery_proof_link",))
# Resultados por etapa atual. "Entregue no CD" vale em qualquer etapa (o botão existia em todas).
LOG_OUTCOMES: dict[str, tuple[LogOutcome, ...]] = {
    "reservada": (LogOutcome("docs", "Documentação enviada", ("nf_link", "xml_link", "bim_link")), DELIVERED),
    "docs": (LogOutcome("approve", "Aprovada para entrega"), DELIVERED),
    "aprovada": (DELIVERED,),
}


def check_links(nf: str, xml: str, bim: str) -> tuple[str, str, str]:
    links = (nf.strip(), xml.strip(), bim.strip())
    if not all(links):
        raise ValueError("Informe os links de NF, XML e BIM.")
    if any(len(link) > LINK_MAX_LENGTH for link in links):
        raise ValueError(f"Cada link pode ter até {LINK_MAX_LENGTH} caracteres.")
    return links


class LogOutcomeForm(QFrame):
    """"O que aconteceu?", campos só do resultado escolhido, "Aconteceu em" e observação.
    Irmão pequeno do `OutcomeForm` da Inspeção (os resultados são outros)."""

    changed = Signal()

    def __init__(self, stage: str, parent=None):
        super().__init__(parent)
        self.outcomes = LOG_OUTCOMES.get(stage, ())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(QLabel("O que aconteceu?"))
        self.group = QButtonGroup(self)
        self.radios: dict[str, QRadioButton] = {}
        for outcome in self.outcomes:
            radio = QRadioButton(outcome.label)
            radio.setAccessibleName(outcome.label)
            self.group.addButton(radio)
            self.radios[outcome.key] = radio
            layout.addWidget(radio)
            radio.toggled.connect(lambda *_: (self._sync_fields(), self.changed.emit()))
        self.fields: dict[str, PathField] = {}
        self.field_labels: dict[str, QLabel] = {}
        for name, caption in FIELD_CAPTIONS.items():
            label = QLabel(caption)
            field = PathField("Escolha o arquivo ou a pasta", caption)
            field.line.textChanged.connect(lambda *_: self.changed.emit())
            self.field_labels[name] = label
            self.fields[name] = field
            layout.addWidget(label)
            layout.addWidget(field)
        layout.addWidget(QLabel("Aconteceu em"))
        self.occurred = DateQuickField("quando aconteceu", initial=local_today())
        self.occurred.changed.connect(self.changed)
        layout.addWidget(self.occurred)
        layout.addWidget(QLabel("Observação (opcional)"))
        self.note = QLineEdit()
        self.note.setMinimumHeight(34)
        self.note.setMaxLength(NOTE_MAX_LENGTH)
        self.note.setAccessibleName("Observação")
        self.note.textChanged.connect(lambda *_: self.changed.emit())
        layout.addWidget(self.note)
        if self.outcomes:
            self.radios[self.outcomes[0].key].setChecked(True)
        self._sync_fields()

    def outcome(self) -> LogOutcome | None:
        return next((o for o in self.outcomes if self.radios[o.key].isChecked()), None)

    def _sync_fields(self) -> None:
        chosen = self.outcome()
        wanted = set(chosen.fields) if chosen else set()
        for name, field in self.fields.items():
            field.setVisible(name in wanted)
            self.field_labels[name].setVisible(name in wanted)


class RecordLogProgressDialog(QDialog):
    """"Registrar andamento" do LOG. `result_data` guarda o LOG devolvido pela API (quem abriu recarrega).
    `log` é o LOG atual: se a etapa mudou, a janela recarrega e segue aberta (`reloaded` fica True)."""

    def __init__(self, service, log: dict, parent=None):
        super().__init__(parent)
        self.service = service
        self.api = service.logistics_service()
        self.log = dict(log)
        self.result_data: dict | None = None
        self.reloaded = False
        self._busy = False
        self.setWindowTitle("Registrar andamento")
        self.setMinimumWidth(560)
        style_dialog_from_parent(self, parent)
        root = dialog_layout(self)
        self.subtitle = QLabel()
        root.addWidget(dialog_header("Registrar andamento", self.subtitle))
        panel, layout = make_panel()
        self._form_slot = QVBoxLayout()
        layout.addLayout(self._form_slot)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.error_label = set_notice_kind(QLabel(""), "danger")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)
        self.warning_panel = DateWarningPanel(lambda: self.submit(True), lambda: self.form.occurred.line)
        layout.addWidget(self.warning_panel)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(panel)
        root.addWidget(scroll, 1)
        cancel = ModernButton("Cancelar", "close", variant="ghost")
        cancel.clicked.connect(self.reject)
        self.register_button = ModernButton("Registrar", "check", variant="primary")
        self.register_button.clicked.connect(lambda _=False: self.submit())
        root.addWidget(dialog_footer(right=[cancel, self.register_button]))
        self._build_form()

    # ---- tela ------------------------------------------------------------
    def _build_form(self, keep: LogOutcomeForm | None = None) -> None:
        """Monta o formulario da etapa atual. `keep`: o formulario anterior, cujo texto e data passam adiante."""
        self.subtitle.setText(self._subtitle_text())
        form = LogOutcomeForm(self.log.get("stage") or "")
        if keep is not None:
            form.note.setText(keep.note.text())
            form.occurred.line.setText(keep.occurred.text())
            self._form_slot.removeWidget(keep)
            keep.deleteLater()
        form.changed.connect(lambda: self.warning_panel.dismiss())
        form.changed.connect(self._sync_summary)
        self._form_slot.addWidget(form)
        self.form = form
        self.register_button.setEnabled(bool(form.outcomes))
        self._sync_summary()

    def _subtitle_text(self) -> str:
        days = int(self.log.get("days_in_stage") or 0)
        stage = LOG_STAGE_LABELS.get(self.log.get("stage") or "", self.log.get("stage") or "")
        return f"{self.log.get('code', '')} · etapa atual: {stage} · {days} {'dia' if days == 1 else 'dias'} nela"

    def _sync_summary(self) -> None:
        chosen = self.form.outcome()
        self.summary.setText(f"Vai acontecer: {chosen.label}." if chosen else "Esta etapa não tem andamento a registrar.")

    # ---- envio -----------------------------------------------------------
    def submit(self, confirm_dates: bool = False) -> None:
        if self._busy:
            return
        self.error_label.setVisible(False)
        self.warning_panel.dismiss()
        try:
            call = self._request(confirm_dates)
        except ValueError as exc:
            self._fail(str(exc))
            return
        self._busy = True
        self.register_button.setEnabled(False)
        start_worker(self, call, self._done, self._error)

    def _request(self, confirm: bool) -> Callable[[], Any]:
        """Valida o formulario e devolve a chamada da API. Levanta ValueError com a mensagem pronta."""
        chosen = self.form.outcome()
        if chosen is None:
            raise ValueError("Escolha o que aconteceu.")
        log_id = int(self.log["id"])
        occurred = self.form.occurred.date_iso("quando aconteceu")
        note = self.form.note.text().strip() or None
        if chosen.key == "docs":
            nf, xml, bim = check_links(*(self.form.fields[k].text() for k in ("nf_link", "xml_link", "bim_link")))
            return lambda: self.api.send_docs(log_id, nf, xml, bim, occurred_on=occurred, note=note, confirm_dates=confirm)
        if chosen.key == "approve":
            return lambda: self.api.approve_log(log_id, occurred_on=occurred, note=note, confirm_dates=confirm)
        proof = self.form.fields["delivery_proof_link"].text()
        if len(proof) > LINK_MAX_LENGTH:
            raise ValueError(f"O comprovante pode ter até {LINK_MAX_LENGTH} caracteres.")
        return lambda: self.api.log_delivery(log_id, occurred, proof_link=proof or None, note=note, confirm_dates=confirm)

    def _done(self, detail: dict) -> None:
        self.result_data = detail
        self.accept()

    def _error(self, exc: Exception) -> None:
        self._busy = False
        self.register_button.setEnabled(True)
        messages = date_warning_messages(exc)
        if messages is not None:
            self.warning_panel.show_messages(messages)
            return
        if getattr(exc, "error_code", None) == STALE_STAGE_CODE:
            self._reload(str(exc))
            return
        self._fail(str(exc))

    def _reload(self, message: str) -> None:
        """Etapa mudou: busca o LOG de novo e refaz o formulario sem perder a observação."""
        log_id = int(self.log["id"])
        start_worker(self, lambda: self.api.get_log(log_id), lambda detail: self._reloaded(detail, message), lambda exc: self._fail(str(exc)))

    def _reloaded(self, detail: dict, message: str) -> None:
        self.log = dict(detail)
        self.reloaded = True
        self._build_form(keep=self.form)
        self._fail(message)

    def _fail(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)
