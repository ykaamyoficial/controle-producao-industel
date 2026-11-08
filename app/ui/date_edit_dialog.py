"""Janela pequena para gravar/corrigir datas com motivo: remarcar visita, corrigir a data de um
andamento, editar as datas do LOG, "Saiu em" da carga e "Entregue no CD em".

Cada uso passa `send(values, reason, link, confirm_dates)`, que chama a API. Avisos de data
(409) abrem a pergunta "Marcar mesmo assim / Escolher outra data" e reenviam com
`confirm_dates=True`.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from PySide6.QtWidgets import QDialog, QLabel, QLineEdit

from app.ui.background_worker import start_worker
from app.ui.components.date_quick_field import DateQuickField
from app.ui.components.detail_widgets import make_panel
from app.ui.components.dialog_shell import dialog_footer, dialog_header, dialog_layout, set_notice_kind
from app.ui.components.modern_button import ModernButton
from app.ui.components.path_field import PathField
from app.ui.date_warnings import handle_date_warning
from app.ui.dialog_utils import style_dialog_from_parent

# (chave, legenda, data atual ou None)
DateSpec = tuple[str, str, "date | None"]


class DateEditDialog(QDialog):
    """`dates`: campos de data (chave, legenda, valor atual). `send(values, reason, link, confirm)` devolve a
    resposta da API; `values` so tem as datas que mudaram (ou todas, com `only_changed=False`).
    `reason_needed(values)` diz se o motivo e obrigatorio. `link`: (legenda, valor atual) para o comprovante."""

    def __init__(
        self,
        parent,
        *,
        title: str,
        subtitle: str,
        dates: list[DateSpec],
        send: Callable[[dict[str, str], str, str | None, bool], Any],
        ok_text: str = "Salvar",
        reason_needed: Callable[[dict[str, str]], bool] = lambda values: True,
        only_changed: bool = True,
        shortcuts: bool = False,
        link: tuple[str, str] | None = None,
    ):
        super().__init__(parent)
        self._send_call = send
        self._reason_needed = reason_needed
        self._only_changed = only_changed
        self._initial = {key: value for key, _caption, value in dates}
        self._link_initial = link[1] if link else None
        self._busy = False
        self.result_data: Any = None
        self.date_fields: dict[str, DateQuickField] = {}
        self.link_field: PathField | None = None
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        style_dialog_from_parent(self, parent)
        root = dialog_layout(self)
        root.addWidget(dialog_header(title, subtitle))
        panel, layout = make_panel()
        for key, caption, value in dates:
            layout.addWidget(QLabel(caption))
            field = DateQuickField(caption.lower(), initial=value, shortcuts=shortcuts)
            self.date_fields[key] = field
            layout.addWidget(field)
        if link:
            layout.addWidget(QLabel(link[0]))
            self.link_field = PathField("Escolha o arquivo ou a pasta do comprovante", link[0])
            self.link_field.setText(link[1])
            layout.addWidget(self.link_field)
        layout.addWidget(QLabel("Motivo"))
        self.reason_field = QLineEdit()
        self.reason_field.setMinimumHeight(34)
        self.reason_field.setPlaceholderText("Por que a data mudou?")
        self.reason_field.setAccessibleName("Motivo")
        layout.addWidget(self.reason_field)
        self.error_label = set_notice_kind(QLabel(""), "danger")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)
        root.addWidget(panel)
        cancel = ModernButton("Cancelar", "close", variant="ghost")
        cancel.clicked.connect(self.reject)
        self.ok_button = ModernButton(ok_text, "check", variant="primary")
        self.ok_button.clicked.connect(lambda _=False: self.submit())
        root.addWidget(dialog_footer(right=[cancel, self.ok_button]))

    def _collect(self) -> tuple[dict[str, str], str, str | None]:
        values = {key: field.date_iso() for key, field in self.date_fields.items()}
        link = self.link_field.text().strip() if self.link_field is not None else None
        link_changed = link is not None and link != (self._link_initial or "")
        changed = {k: v for k, v in values.items() if (self._initial.get(k).isoformat() if self._initial.get(k) else None) != v}
        if self._only_changed and not changed and not link_changed:
            raise ValueError("Nada foi alterado.")
        if not self._only_changed:
            changed = values
        reason = self.reason_field.text().strip()
        if not reason and self._reason_needed(changed):
            raise ValueError("Informe o motivo.")
        return changed, reason, link if link_changed else None

    def submit(self, confirm_dates: bool = False) -> None:
        if self._busy:
            return
        self.error_label.setVisible(False)
        try:
            values, reason, link = self._collect()
        except ValueError as exc:
            self._fail(str(exc))
            return
        self._dispatch(values, reason, link, confirm_dates)

    def _dispatch(self, values: dict[str, str], reason: str, link: str | None, confirm: bool) -> None:
        self._busy = True
        self.ok_button.setEnabled(False)
        start_worker(
            self,
            lambda: self._send_call(values, reason, link, confirm),
            self._done,
            lambda exc: self._error(exc, values, reason, link),
        )

    def _done(self, result: Any) -> None:
        self.result_data = result
        self.accept()

    def _error(self, exc: Exception, values: dict[str, str], reason: str, link: str | None) -> None:
        self._busy = False
        self.ok_button.setEnabled(True)
        if handle_date_warning(self, exc, lambda: self._dispatch(values, reason, link, True)):
            return
        self._fail(str(exc))

    def _fail(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)
