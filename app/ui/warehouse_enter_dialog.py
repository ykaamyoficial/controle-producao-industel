from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QWidget,
)

from app.services.app_logging import get_logger
from app.ui.background_worker import start_worker
from app.ui.components.dialog_shell import dialog_footer, dialog_header, dialog_layout, set_notice_kind, set_validation_state
from app.ui.components.modern_button import ModernButton
from app.ui.components.status_badge import area_badge
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.icons import AppIcons
from app.ui.theme_tokens import ui_tokens

log = get_logger("warehouse_enter_dialog")

# Limite da API por chamada (corpo de 1 a 200 numeros).
MAX_NUMBERS = 200

_SEPARATORS = re.compile(r"[,;\s​﻿]+")  # \s ja cobre o espaco nao separavel ( )
# Aspas (retas e curvas) e pontuacao final de e-mail/planilha coladas ao numero. A API so faz trim.
_EDGE_CHARS = "\"'`“”‘’«».,;"

# Resultado da API -> (texto do selo, token de cor). Cor so por token.
RESULT_BADGES = {
    "ENTROU": ("Entrou", "success"),
    "JA_NA_ABA": ("Já estava na aba", "accent"),
    "JA_ENTREGUE": ("Já entregue", "warning"),
    "NAO_ENCONTRADA": ("Não encontrada", "danger"),
    "CANCELADA": ("Cancelada", "danger"),
    "PROPOSTA_PARCIAL": ("Proposta parcial", "warning"),
}


def parse_proposal_numbers(text: str) -> list[str]:
    """Numeros digitados/colados -> lista limpa, sem vazios nem repetidos (ignora caixa), na ordem em que vieram.

    Separa por virgula, ponto e virgula, espaco (inclusive nao separavel), tab e quebra de linha; tira aspas e
    ponto/virgula/ponto e virgula nas pontas de cada numero."""
    seen: set[str] = set()
    numbers: list[str] = []
    for token in _SEPARATORS.split(text or ""):
        number = token.strip(_EDGE_CHARS)
        key = number.lower()
        if number and key not in seen:
            seen.add(key)
            numbers.append(number)
    return numbers


class WarehouseEnterDialog(QDialog):
    """"Adicionar propostas" ao Almoxarifado pelo numero: o Henrique digita/cola os numeros, a API devolve um
    resultado por numero (entrou, ja estava, nao encontrada...). `changed` fica True se alguma entrou, para a
    pagina que abriu o dialogo recarregar a lista."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.changed = False
        self.results: list[dict] = []
        self._running = False
        self._thread = None
        self.setWindowTitle("Adicionar propostas ao Almoxarifado")
        style_dialog_from_parent(self, parent)
        self.setMinimumWidth(640)
        self._build()
        self._update_state()

    def _build(self):
        root = dialog_layout(self)
        root.addWidget(dialog_header(
            "Adicionar propostas ao Almoxarifado",
            "Digite ou cole os números das propostas, separados por vírgula, espaço ou linha. Elas entram em separação.",
        ))

        self.numbers_edit = QTextEdit()
        self.numbers_edit.setAcceptRichText(False)
        self.numbers_edit.setAccessibleName("Números das propostas")
        self.numbers_edit.setPlaceholderText("CP05389, CP05401\nCP05515")
        self.numbers_edit.setFixedHeight(110)
        self.numbers_edit.textChanged.connect(self._on_text_changed)
        root.addWidget(self.numbers_edit)

        self.counter_label = QLabel("")
        self.counter_label.setObjectName("Caption")
        root.addWidget(self.counter_label)

        # Aviso/erro sempre em linha (nunca QMessageBox).
        self.notice_label = set_notice_kind(QLabel(""), "")
        self.notice_label.setWordWrap(True)
        self.notice_label.setVisible(False)
        root.addWidget(self.notice_label)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("Caption")
        self.summary_label.setVisible(False)
        root.addWidget(self.summary_label)

        self.results_table = QTableWidget(0, 3)
        self.results_table.setHorizontalHeaderLabels(["Número", "Resultado", "Detalhe"])
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setSelectionMode(QTableWidget.NoSelection)
        self.results_table.setAlternatingRowColors(True)
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.results_table.setMinimumHeight(180)
        self.results_table.setVisible(False)
        root.addWidget(self.results_table, 1)

        self.close_button = ModernButton("Fechar", AppIcons.CLOSE, variant="ghost")
        self.add_button = ModernButton("Adicionar", AppIcons.NEW, accent=True)
        self.close_button.clicked.connect(self.reject)
        self.add_button.clicked.connect(self.submit)
        root.addWidget(dialog_footer(right=[self.close_button, self.add_button]))

    # -- estado ----------------------------------------------------------

    def numbers(self) -> list[str]:
        return parse_proposal_numbers(self.numbers_edit.toPlainText())

    def _on_text_changed(self):
        # Texto novo: o ultimo resultado ja nao descreve o que esta no campo.
        self._clear_notice()
        self._update_state()

    def _update_state(self):
        count = len(self.numbers())
        too_many = count > MAX_NUMBERS
        if too_many:
            self.counter_label.setText(f"{count} números informados. O máximo é {MAX_NUMBERS} por vez.")
            self._show_notice(f"Informe no máximo {MAX_NUMBERS} números por vez. Divida a lista e adicione em duas etapas.", "danger")
        else:
            self.counter_label.setText("Nenhum número informado." if not count else f"{count} {'número' if count == 1 else 'números'}.")
        set_validation_state(self.numbers_edit, "error" if too_many else "")
        self.add_button.setEnabled(0 < count <= MAX_NUMBERS and not self._running)
        self.numbers_edit.setEnabled(not self._running)

    def _show_notice(self, text: str, kind: str):
        set_notice_kind(self.notice_label, kind)
        self.notice_label.setText(text)
        self.notice_label.setVisible(True)

    def _clear_notice(self):
        self.notice_label.setVisible(False)
        self.notice_label.setText("")

    # -- envio ------------------------------------------------------------

    def submit(self):
        if self._running:
            return
        numbers = self.numbers()
        # O limite e conferido aqui tambem: a API recusaria (422) e nao ha por que chama-la.
        if not numbers or len(numbers) > MAX_NUMBERS:
            self._update_state()
            return
        self._clear_notice()
        self._running = True
        self._update_state()
        self._thread = start_worker(self, lambda: self.service.warehouse_enter(numbers), self._on_success, self._on_error)

    def _on_success(self, results):
        self._running = False
        self.results = list(results or [])
        if any(item.get("result") == "ENTROU" for item in self.results):
            self.changed = True
        self._show_results(self.results)
        # Os numeros ja foram processados: o botao so volta com texto novo (repetir seria inofensivo, mas confunde).
        self.numbers_edit.setEnabled(True)
        self.add_button.setEnabled(False)

    def _on_error(self, exc):
        self._running = False
        log.warning("Falha ao adicionar propostas ao Almoxarifado: %s", exc)
        self._show_notice(str(exc) or "Não foi possível adicionar as propostas. Tente novamente.", "danger")
        self._update_state()

    def _show_results(self, results: list[dict]):
        tokens = ui_tokens(self.service.palette)
        self.results_table.setRowCount(0)
        counts: dict[str, int] = {}
        for item in results:
            result = str(item.get("result") or "")
            counts[result] = counts.get(result, 0) + 1
            label, token = RESULT_BADGES.get(result, (result or "—", "muted"))
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            self.results_table.setItem(row, 0, QTableWidgetItem(str(item.get("number") or "")))
            holder = QWidget()
            holder_layout = QHBoxLayout(holder)
            holder_layout.setContentsMargins(8, 4, 8, 4)
            holder_layout.setAlignment(Qt.AlignCenter)
            holder_layout.addWidget(area_badge(label, tokens[token]))
            self.results_table.setCellWidget(row, 1, holder)
            self.results_table.setItem(row, 2, QTableWidgetItem(str(item.get("message") or "")))
            self.results_table.setRowHeight(row, 36)
        self.results_table.setVisible(bool(results))
        entered = counts.get("ENTROU", 0)
        others = len(results) - entered
        parts = [f"{entered} {'proposta entrou' if entered == 1 else 'propostas entraram'} no Almoxarifado"]
        if others:
            parts.append(f"{others} não {'entrou' if others == 1 else 'entraram'}")
        self.summary_label.setText(". ".join(parts) + ".")
        self.summary_label.setVisible(True)
