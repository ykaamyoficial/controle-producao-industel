from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFrame, QHBoxLayout, QLabel, QStackedLayout, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from app.services.app_logging import get_logger
from app.ui.background_worker import start_worker
from app.ui.components.dialog_shell import dialog_footer, dialog_header, set_notice_kind, set_validation_state
from app.ui.components.modern_button import ModernButton
from app.ui.components.skeleton import SkeletonRows
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.icons import AppIcons

log = get_logger("undo_dialog")

REASON_MAX_LENGTH = 1000
_EMPTY = "—"
_UNDO_CLASS_LABELS = {
    "A": "Reversão simples",
    "B": "Reversão com cuidado",
    "C": "Reversão com efeito externo",
}

# Mensagens (pt-BR) por codigo de erro do POST /proposals/{id}/undo. A API ja manda
# texto proprio em UNDO_NOT_SUPPORTED (motivo + alternativa) e a lista em UNDO_BLOCKED;
# aqui ficam os textos fixos dos demais codigos.
UNDO_ERROR_MESSAGES = {
    "PROPOSAL_VERSION_CONFLICT": "Esta proposta foi alterada por outra pessoa. Recarregamos os dados; revise e confirme de novo.",
    "UNDO_NOT_LATEST": "Esta ação não é mais a última da proposta. Recarregamos os dados; confira a nova última ação.",
    "UNDO_ALREADY_UNDONE": "Esta ação já foi desfeita. Recarregamos os dados.",
    "UNDO_ACTION_NOT_FOUND": "A ação a desfazer não foi encontrada. Recarregamos os dados.",
    "UNDO_IDEMPOTENCY_CONFLICT": "A solicitação anterior conflitou com esta. Confirme de novo para enviar uma nova.",
    "UNDO_BLOCKED": "Não é possível desfazer agora:",
    "UNDO_NOT_SUPPORTED": "Esta ação não pode ser desfeita.",
    "PERMISSION_DENIED": "Você não tem permissão para desfazer esta ação.",
}
# Codigos em que o estado mudou: o dialogo recarrega o candidato. So o conflito de
# versao preserva o motivo digitado; nos demais o alvo mudou, entao o motivo e limpo.
_RELOAD_KEEP_REASON = ("PROPOSAL_VERSION_CONFLICT",)
_RELOAD_CLEAR_REASON = ("UNDO_NOT_LATEST", "UNDO_ALREADY_UNDONE", "UNDO_ACTION_NOT_FOUND")


def _format_when(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return _EMPTY
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return text


def _blockers_from(exc: Exception) -> list[str]:
    details = getattr(exc, "details", None)
    rows = details.get("blockers") if isinstance(details, dict) else None
    if not isinstance(rows, list):
        return []
    return [str(row.get("message") or row.get("code") or "") for row in rows if isinstance(row, dict)]


class UndoActionDialog(QDialog):
    """Desfazer a ultima acao da proposta: mostra o que a API vai restaurar
    (mudancas antes -> depois), avisos, bloqueios e pede o motivo. Toda regra
    (permissao, classe, bloqueios, versao) e da API - aqui so se apresenta o
    `GET /proposals/{id}/undo/candidate` e se envia o `POST .../undo`. Sem
    QMessageBox: erros aparecem em linha, no proprio dialogo.

    `candidate` opcional evita a primeira consulta (a Central de Acoes ja a
    tinha); sem ele o dialogo busca em segundo plano ao abrir."""

    def __init__(self, service, process_id: int, parent=None, candidate: dict | None = None):
        super().__init__(parent)
        self.service = service
        self.process_id = int(process_id)
        self.candidate: dict | None = None
        self.updated_process: dict | None = None
        self._loading = False
        self._submitting = False
        self._blocked = False  # UNDO_BLOCKED / UNDO_NOT_SUPPORTED: nao adianta reenviar
        self._thread = None
        self._pending_notice: tuple[str, list[str]] = ("", [])
        self._idempotency_key = str(uuid4())
        self._key_signature: tuple | None = None
        self.setWindowTitle("Desfazer última ação")
        self.setMinimumWidth(680)
        style_dialog_from_parent(self, parent)
        self._build()
        if candidate is not None:
            self._apply_candidate(candidate)
        else:
            self.reload()

    # -- layout --------------------------------------------------------

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        root.addWidget(dialog_header(
            "Desfazer última ação",
            "Restaura o estado anterior da proposta. A operação fica registrada no histórico.",
        ))

        self.skeleton = SkeletonRows(top_offset=0)
        self.skeleton.setMinimumHeight(160)
        self.content = QWidget()
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        panel = QFrame()
        panel.setObjectName("DetailPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 12, 14, 12)
        panel_layout.setSpacing(4)
        self.action_title = QLabel("")
        self.action_title.setObjectName("PanelTitle")
        self.action_title.setWordWrap(True)
        self.action_meta = QLabel("")
        self.action_meta.setObjectName("Caption")
        self.action_meta.setWordWrap(True)
        panel_layout.addWidget(self.action_title)
        panel_layout.addWidget(self.action_meta)
        content_layout.addWidget(panel)

        # Motivo pelo qual nao da para desfazer (texto pronto da API, com a alternativa).
        self.reason_notice = self._notice("warning")
        content_layout.addWidget(self.reason_notice)

        self.changes_label = QLabel("O que será restaurado")
        self.changes_label.setObjectName("PanelTitle")
        self.changes_table = QTableWidget(0, 3)
        self.changes_table.setHorizontalHeaderLabels(["O que muda", "Agora", "Depois de desfazer"])
        self.changes_table.verticalHeader().setVisible(False)
        self.changes_table.verticalHeader().setDefaultSectionSize(36)
        self.changes_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.changes_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.changes_table.setShowGrid(False)
        self.changes_table.setAlternatingRowColors(True)
        self.changes_table.setWordWrap(True)
        self.changes_table.horizontalHeader().setStretchLastSection(True)
        self.changes_table.setColumnWidth(0, 220)
        self.changes_table.setColumnWidth(1, 190)
        content_layout.addWidget(self.changes_label)
        content_layout.addWidget(self.changes_table)

        self.side_effects_box = QVBoxLayout()
        self.side_effects_box.setSpacing(4)
        content_layout.addLayout(self.side_effects_box)
        self.blockers_box = QVBoxLayout()
        self.blockers_box.setSpacing(4)
        content_layout.addLayout(self.blockers_box)

        self.reason_label = QLabel("Motivo (obrigatório)")
        self.reason_label.setObjectName("FieldLabel")
        self.reason = QTextEdit()
        self.reason.setAcceptRichText(False)
        self.reason.setPlaceholderText("Explique por que esta ação está sendo desfeita")
        self.reason.setFixedHeight(84)
        self.reason.textChanged.connect(self._update_state)
        self.reason_counter = QLabel("")
        self.reason_counter.setObjectName("Caption")
        self.reason_counter.setAlignment(Qt.AlignRight)
        content_layout.addWidget(self.reason_label)
        content_layout.addWidget(self.reason)
        content_layout.addWidget(self.reason_counter)

        # Erro de envio/carga, sempre em linha (nunca QMessageBox).
        self.error_label = self._notice("danger")
        self.error_blockers_box = QVBoxLayout()
        self.error_blockers_box.setSpacing(2)
        content_layout.addWidget(self.error_label)
        content_layout.addLayout(self.error_blockers_box)

        self.body_stack_host = QWidget()
        self.body_stack = QStackedLayout(self.body_stack_host)
        self.body_stack.setContentsMargins(0, 0, 0, 0)
        self.body_stack.addWidget(self.skeleton)
        self.body_stack.addWidget(self.content)
        root.addWidget(self.body_stack_host, 1)

        self.cancel_button = ModernButton("Cancelar", AppIcons.CLOSE, variant="ghost")
        self.undo_button = ModernButton("Desfazer", AppIcons.HISTORY, accent=True)
        self.cancel_button.clicked.connect(self.reject)
        self.undo_button.clicked.connect(self.submit)
        root.addWidget(dialog_footer(right=[self.cancel_button, self.undo_button]))
        self.undo_button.setEnabled(False)

    @staticmethod
    def _notice(kind: str) -> QLabel:
        label = set_notice_kind(QLabel(""), kind)
        label.setWordWrap(True)
        label.setVisible(False)
        return label

    @staticmethod
    def _clear(layout: QVBoxLayout):
        while layout.count():
            widget = layout.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    # -- carga ---------------------------------------------------------

    def reload(self, notice: str = "", blockers: list[str] | None = None):
        """Reconsulta o candidato (em segundo plano). `notice` fica visivel depois
        da recarga - explica por que o dialogo mudou."""
        if self._loading:
            return
        self._loading = True
        self._blocked = False
        self._pending_notice = (notice, blockers or [])
        self.body_stack.setCurrentWidget(self.skeleton)
        self._update_state()
        self._thread = start_worker(
            self, self._fetch_candidate, self._reload_success, self._reload_error
        )

    def _fetch_candidate(self):
        # Recarrega na mesma pista do candidato aberto (Almoxarifado/Fiscal); o fluxo geral e o default da API.
        lane = (self.candidate or {}).get("lane")
        return self.service.undo_candidate(self.process_id, **({"lane": lane} if lane and lane != "GERAL" else {}))

    def _reload_success(self, candidate):
        self._loading = False
        self._apply_candidate(candidate if isinstance(candidate, dict) else {})
        notice, blockers = self._pending_notice
        if notice:
            self._show_error(notice, blockers)

    def _reload_error(self, exc):
        self._loading = False
        log.warning("Falha ao carregar a ultima acao desfazivel: proposal_id=%s", self.process_id, exc_info=exc)
        self.body_stack.setCurrentWidget(self.content)
        self.candidate = None
        self._render_candidate({})
        self.action_title.setText("Não foi possível consultar a última ação")
        self.reason_notice.setVisible(False)
        self._show_error(str(exc) or "Não foi possível consultar a última ação desta proposta.")
        self._update_state()

    def _apply_candidate(self, candidate: dict):
        self.candidate = dict(candidate or {})
        self._render_candidate(self.candidate)
        self.body_stack.setCurrentWidget(self.content)
        self._update_state()

    def _render_candidate(self, candidate: dict):
        action = candidate.get("action") if isinstance(candidate.get("action"), dict) else None
        self._show_error("")
        if action:
            self.action_title.setText(str(action.get("title") or action.get("label") or "Última ação"))
            who = str(action.get("actor_name") or "").strip() or (
                f"usuário {action['actor_user_id']}" if action.get("actor_user_id") else _EMPTY
            )
            meta = f"Feita por {who} em {_format_when(action.get('created_at'))}"
            if int(action.get("event_count") or 1) > 1:
                meta += f" ({int(action['event_count'])} registros agrupados)"
            undo_class = _UNDO_CLASS_LABELS.get(str(candidate.get("undo_class") or ""))
            if undo_class and candidate.get("undoable"):
                meta += f" · {undo_class}"
            self.action_meta.setText(meta)
        else:
            self.action_title.setText("Nenhuma ação para desfazer")
            self.action_meta.setText("")

        reason = str(candidate.get("cannot_undo_reason") or "").strip()
        if not reason and not candidate.get("can_undo"):
            reason = "Não há nenhuma ação para desfazer nesta proposta."
        self.reason_notice.setText(reason)
        self.reason_notice.setVisible(bool(reason) and not candidate.get("can_undo"))

        changes = [row for row in candidate.get("changes") or [] if isinstance(row, dict)]
        self.changes_table.setRowCount(len(changes))
        for row, change in enumerate(changes):
            for col, value in enumerate((
                change.get("label") or change.get("field"),
                change.get("current_value"),
                change.get("restored_value"),
            )):
                text = str(value) if value not in (None, "") else _EMPTY
                cell = QTableWidgetItem(text)
                cell.setToolTip(text)
                self.changes_table.setItem(row, col, cell)
        visible_rows = min(max(len(changes), 1), 6)
        self.changes_table.setFixedHeight(34 + visible_rows * 36 + 2)
        self.changes_label.setVisible(bool(changes))
        self.changes_table.setVisible(bool(changes))

        self._clear(self.side_effects_box)
        for effect in candidate.get("side_effects") or []:
            if isinstance(effect, dict) and effect.get("message"):
                label = set_notice_kind(QLabel(str(effect["message"])), "warning")
                label.setWordWrap(True)
                self.side_effects_box.addWidget(label)
        self._clear(self.blockers_box)
        for blocker in candidate.get("blockers") or []:
            if isinstance(blocker, dict) and blocker.get("message"):
                label = set_notice_kind(QLabel(f"• {blocker['message']}"), "danger")
                label.setWordWrap(True)
                self.blockers_box.addWidget(label)

    # -- estado --------------------------------------------------------

    def _can_submit(self) -> bool:
        candidate = self.candidate or {}
        reason = self.reason.toPlainText().strip()
        return bool(
            candidate.get("can_undo")
            and candidate.get("undoable")
            and candidate.get("proposal_version") is not None
            and isinstance(candidate.get("action"), dict)
            and candidate["action"].get("request_id")
            and reason
            and len(reason) <= REASON_MAX_LENGTH
            and not (self._loading or self._submitting or self._blocked)
        )

    def _update_state(self, *_):
        length = len(self.reason.toPlainText().strip())
        self.reason_counter.setText(f"{length}/{REASON_MAX_LENGTH}")
        set_validation_state(self.reason, "error" if length > REASON_MAX_LENGTH else "")
        busy = self._loading or self._submitting
        self.reason.setEnabled(not busy)
        self.cancel_button.setEnabled(not self._submitting)
        self.undo_button.setEnabled(self._can_submit())

    def _show_error(self, message: str, blockers: list[str] | None = None):
        self._clear(self.error_blockers_box)
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))
        for text in blockers or []:
            label = set_notice_kind(QLabel(f"• {text}"), "danger")
            label.setWordWrap(True)
            self.error_blockers_box.addWidget(label)

    # -- envio ---------------------------------------------------------

    def _key_for(self, signature: tuple) -> str:
        """A chave so muda quando motivo, versao ou alvo mudam (ou apos conflito de
        idempotencia); um reenvio igual - ex.: depois de timeout - reaproveita a chave."""
        if self._key_signature is not None and self._key_signature != signature:
            self._idempotency_key = str(uuid4())
        self._key_signature = signature
        return self._idempotency_key

    def submit(self):
        if not self._can_submit():
            return
        candidate = self.candidate or {}
        reason = self.reason.toPlainText().strip()
        version = int(candidate["proposal_version"])
        target = str(candidate["action"]["request_id"])
        key = self._key_for((reason, version, target))
        self._submitting = True
        self._show_error("")
        self._update_state()
        self._thread = start_worker(
            self,
            lambda: self.service.undo_last_action(self.process_id, version, target, reason, key),
            self._submit_success,
            self._submit_error,
        )

    def _submit_success(self, result):
        self._submitting = False
        self.updated_process = result if isinstance(result, dict) else None
        self.accept()

    def _submit_error(self, exc):
        self._submitting = False
        code = getattr(exc, "error_code", None) or ""
        log.warning("Falha ao desfazer a ultima acao: proposal_id=%s code=%s", self.process_id, code or "-")
        message = UNDO_ERROR_MESSAGES.get(code)
        if code == "UNDO_NOT_SUPPORTED":
            # A API manda o motivo e a alternativa no proprio texto.
            self._blocked = True
            self._show_error(str(exc) or message)
        elif code == "UNDO_BLOCKED":
            self._blocked = True
            self._show_error(message, _blockers_from(exc))
        elif code == "UNDO_IDEMPOTENCY_CONFLICT":
            self._key_signature = None
            self._idempotency_key = str(uuid4())
            self._show_error(message)
        elif code in _RELOAD_KEEP_REASON + _RELOAD_CLEAR_REASON:
            if code in _RELOAD_CLEAR_REASON:
                self.reason.clear()
            self.reload(notice=message)
            return
        else:
            self._show_error(message or str(exc) or "Não foi possível desfazer a ação.")
        self._update_state()

    def reject(self):
        if self._submitting:
            return
        super().reject()
