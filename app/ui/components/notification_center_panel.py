from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from app.ui.background_worker import start_worker
from app.ui.components.modern_button import ModernButton
from app.ui.icons import make_icon


PAGE_SIZE = 30
SCROLL_TOP_THRESHOLD_PX = 4

FILTERS = [
    (None, "Todas"),
    ("unread", "Nao lidas"),
]

_TYPE_ICON = {
    "MENCAO": "at",
    "RESPOSTA": "chat",
    "PERGUNTA_ATRIBUIDA": "question",
    "PERGUNTA_ATRASADA": "question",
    "PERGUNTA_RESPONDIDA": "question",
    "NOTA_DIRECIONADA": "doc",
    "NOTA_IMPORTANTE": "doc",
}

_TYPE_VERB = {
    "MENCAO": "mencionou voce",
    "RESPOSTA": "respondeu sua mensagem",
    "PERGUNTA_ATRIBUIDA": "atribuiu uma pergunta a voce",
    "PERGUNTA_ATRASADA": "pergunta atribuida a voce esta atrasada",
    "PERGUNTA_RESPONDIDA": "respondeu sua pergunta",
    "NOTA_DIRECIONADA": "registrou uma nota interna para voce",
    "NOTA_IMPORTANTE": "registrou uma nota interna importante",
}

# Tipos que, se OPEN/RESOLVED/CANCELADA, mostram um chip de status --
# so pergunta atribuida representa uma pendencia de verdade (ETAPA 5).
_PENDING_TYPES = {"PERGUNTA_ATRIBUIDA", "PERGUNTA_ATRASADA"}


def _format_relative(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    now = datetime.now(parsed.tzinfo)
    delta = now - parsed
    seconds = delta.total_seconds()
    if seconds < 60:
        return "Agora ha pouco"
    if seconds < 3600:
        return f"Ha {int(seconds // 60)} min"
    if seconds < 86400:
        return f"Ha {int(seconds // 3600)} h"
    return parsed.strftime("%d/%m/%Y %H:%M")


def _parse_day(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _day_label(day) -> str:
    today = datetime.now().date()
    if day == today:
        return "Hoje"
    if day == today - timedelta(days=1):
        return "Ontem"
    return day.strftime("%d/%m/%Y")


class NotificationCenterPanel(QFrame):
    """Central de Notificacoes aberta pelo sino — popover nao-bloqueante
    (ETAPA 10: a spec proibe explicitamente um QDialog modal aqui). So
    mostra o que exige atencao (mencao, resposta, pergunta atribuida/
    atrasada, nota interna direcionada/importante); atividade operacional
    nunca aparece aqui. Historico nunca e apagado ao ser lido — ver
    a regra "READ != RESOLVED" no service.py (ler uma Notification nunca
    resolve ActionRequired nem avanca last_read_message_id)."""

    def __init__(self, service, parent=None, on_open_conversation=None):
        super().__init__(parent, Qt.Popup)
        self.service = service
        self._on_open_conversation = on_open_conversation
        self.notifications: list[dict] = []
        self._status_filter: str | None = None
        self._filter_buttons: dict[str | None, ModernButton] = {}
        self._has_more = False
        self._loading_more = False
        self.setObjectName("Panel")
        self.setFixedWidth(420)
        self.setMaximumHeight(560)
        self._build()
        self.refresh()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Notificacoes")
        title.setStyleSheet("font-size: 14px; font-weight: 800;")
        header.addWidget(title)
        header.addStretch()
        mark_all_btn = ModernButton("Marcar todas como lidas", "status")
        mark_all_btn.clicked.connect(self._mark_all_read)
        header.addWidget(mark_all_btn)
        layout.addLayout(header)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)
        for value, label in FILTERS:
            button = ModernButton(label, accent=(value is None))
            button.setObjectName("AccentButton" if value is None else "GhostButton")
            button.setStyleSheet("padding: 3px 10px; font-size: 11px;")
            button.setMinimumHeight(24)
            button.clicked.connect(lambda _checked=False, v=value: self._set_filter(v))
            self._filter_buttons[value] = button
            filter_row.addWidget(button)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        self.loading_label = QLabel("Carregando...")
        self.loading_label.setObjectName("Caption")
        self.loading_label.setVisible(False)
        layout.addWidget(self.loading_label)

        self.new_items_banner = ModernButton("Novas notificacoes — toque para atualizar", "status")
        self.new_items_banner.setStyleSheet("padding: 4px 10px; font-size: 11px;")
        self.new_items_banner.setVisible(False)
        self.new_items_banner.clicked.connect(self._on_banner_clicked)
        layout.addWidget(self.new_items_banner)

        self.error_state = self._build_error_state()
        self.error_state.setVisible(False)
        layout.addWidget(self.error_state)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(6)
        self.list_layout.addStretch()
        self.scroll.setWidget(self.list_widget)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        layout.addWidget(self.scroll, 1)

    def _build_error_state(self) -> QWidget:
        container = QWidget()
        col = QVBoxLayout(container)
        col.setContentsMargins(0, 12, 0, 12)
        col.setSpacing(8)
        message = QLabel("Nao foi possivel carregar as notificacoes.")
        message.setObjectName("Caption")
        message.setAlignment(Qt.AlignCenter)
        col.addWidget(message)
        retry_btn = ModernButton("Tentar novamente", "status")
        retry_btn.clicked.connect(self.refresh)
        retry_row = QHBoxLayout()
        retry_row.addStretch()
        retry_row.addWidget(retry_btn)
        retry_row.addStretch()
        col.addLayout(retry_row)
        return container

    # -- filtro -----------------------------------------------------

    def _set_filter(self, value: str | None):
        if value == self._status_filter:
            return
        self._status_filter = value
        for key, button in self._filter_buttons.items():
            button.setObjectName("AccentButton" if key == value else "GhostButton")
            button.style().unpolish(button)
            button.style().polish(button)
        self.refresh()

    # -- carregamento -------------------------------------------------

    def refresh(self):
        """Recarrega a primeira pagina do zero — NAO marca nada como lido,
        so consulta (ETAPA 10: abrir/listar a Central e sempre read-only)."""
        self.new_items_banner.setVisible(False)
        self.error_state.setVisible(False)
        self.loading_label.setVisible(True)
        self._refresh_thread = start_worker(
            self,
            lambda: self.service.chat_notifications_page(status=self._status_filter, limit=PAGE_SIZE, offset=0),
            self._refresh_success,
            self._refresh_error,
        )

    def _refresh_success(self, payload: dict):
        self.notifications = list(payload.get("items") or [])
        self._has_more = bool(payload.get("has_more"))
        self.loading_label.setVisible(False)
        self.error_state.setVisible(False)
        self._render()

    def _refresh_error(self, _exc):
        self.loading_label.setVisible(False)
        if not self.notifications:
            self.error_state.setVisible(True)
        else:
            self.new_items_banner.setText("Nao foi possivel atualizar — toque para tentar de novo")
            self.new_items_banner.setVisible(True)

    def _load_more(self):
        if self._loading_more or not self._has_more:
            return
        self._loading_more = True
        self._load_more_btn.setEnabled(False)
        self._load_more_btn.setText("Carregando...")
        start_worker(
            self,
            lambda: self.service.chat_notifications_page(status=self._status_filter, limit=PAGE_SIZE, offset=len(self.notifications)),
            self._load_more_success,
            self._load_more_error,
        )

    def _load_more_success(self, payload: dict):
        self._loading_more = False
        self.notifications.extend(payload.get("items") or [])
        self._has_more = bool(payload.get("has_more"))
        self._render()

    def _load_more_error(self, _exc):
        self._loading_more = False
        self._load_more_btn.setEnabled(True)
        self._load_more_btn.setText("Carregar mais")

    # -- realtime -----------------------------------------------------

    def apply_realtime_event(self, event_type: str, _data: dict) -> None:
        """Chamado pelo MainWindow quando um evento notification.* chega
        via WebSocket enquanto o painel esta aberto. Nunca confia no corpo
        do evento — so usa como gatilho pra rebuscar via REST (mesma
        filosofia das ETAPAS 7-9). Se o usuario esta lendo historico mais
        abaixo, NAO puxa o scroll pra cima sozinho (pedido explicito da
        spec) — so mostra um aviso discreto."""
        if event_type not in ("notification.created", "notification.read", "notification.read_all"):
            return
        if self._is_scrolled_to_top():
            self.refresh()
        else:
            self.new_items_banner.setText("Novas notificacoes — toque para atualizar")
            self.new_items_banner.setVisible(True)

    def _is_scrolled_to_top(self) -> bool:
        return self.scroll.verticalScrollBar().value() <= SCROLL_TOP_THRESHOLD_PX

    def _on_scroll_changed(self, _value: int) -> None:
        if self._is_scrolled_to_top() and self.new_items_banner.isVisible():
            self.new_items_banner.setVisible(False)

    def _on_banner_clicked(self):
        self.new_items_banner.setVisible(False)
        self.refresh()

    # -- render ---------------------------------------------------------

    def _render(self):
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not self.notifications:
            empty_text = "Nenhuma notificacao nao lida." if self._status_filter == "unread" else "Nenhuma notificacao."
            empty = QLabel(empty_text)
            empty.setObjectName("Caption")
            self.list_layout.insertWidget(0, empty)
            return

        index = 0
        last_day = None
        for notification in self.notifications:
            day = _parse_day(notification.get("created_at"))
            if day != last_day:
                last_day = day
                header = QLabel(_day_label(day) if day else "")
                header.setObjectName("Caption")
                header.setStyleSheet("font-weight: 700; font-size: 10px; margin-top: 4px;")
                self.list_layout.insertWidget(index, header)
                index += 1
            self.list_layout.insertWidget(index, self._build_row(notification))
            index += 1

        if self._has_more:
            self._load_more_btn = ModernButton("Carregar mais", "history")
            self._load_more_btn.clicked.connect(self._load_more)
            self.list_layout.insertWidget(index, self._load_more_btn)

    def _build_row(self, notification: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("Panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        notification_type = notification.get("notification_type")
        priority = notification.get("priority") or "normal"
        unread = notification.get("read_at") is None
        palette = self.service.palette
        colors = {
            "acao_obrigatoria": palette.get("warning", "#d97706"),
            "atrasada": palette.get("danger", "#dc2626"),
            "atencao": palette.get("accent", "#0078d4"),
        }
        color = colors.get(priority, palette.get("muted", "#94a3b8")) if unread else palette.get("muted", "#94a3b8")

        header = QHBoxLayout()
        header.setSpacing(6)
        icon_label = QLabel()
        icon_label.setPixmap(make_icon(_TYPE_ICON.get(notification_type, "bell"), color, 15).pixmap(15, 15))
        header.addWidget(icon_label)
        who = notification.get("author_name") or "Alguem"
        verb = _TYPE_VERB.get(notification_type, "gerou uma notificacao")
        proposal_number = notification.get("proposal_number")
        customer_name = notification.get("customer_name")
        if proposal_number and customer_name:
            where = f" em {proposal_number} - {customer_name}"
        elif proposal_number:
            where = f" em {proposal_number}"
        else:
            where = " no Chat Geral" if notification.get("kind") == "GERAL" else ""
        title_label = QLabel(f"{who} {verb}{where}")
        title_label.setWordWrap(True)
        title_label.setStyleSheet(f"font-weight: 700; font-size: 12px; color: {color};" if unread else "font-weight: 600; font-size: 12px;")
        header.addWidget(title_label, 1)
        time_label = QLabel(_format_relative(notification.get("created_at")))
        time_label.setObjectName("Caption")
        time_label.setStyleSheet("font-size: 9px;")
        header.addWidget(time_label)
        layout.addLayout(header)

        body = (notification.get("message_body") or "").strip().replace("\n", " ")
        if len(body) > 140:
            body = body[:137] + "..."
        if body:
            body_label = QLabel(f"“{body}”")
            body_label.setWordWrap(True)
            body_label.setStyleSheet("font-size: 11px;")
            layout.addWidget(body_label)

        if notification_type in _PENDING_TYPES:
            layout.addWidget(self._build_pending_chip(notification))

        card.setCursor(Qt.PointingHandCursor)
        card.mousePressEvent = lambda _event, n=notification: self._open(n)
        return card

    def _build_pending_chip(self, notification: dict) -> QLabel:
        # ETAPA 10: a Notification pode estar READ sem que a pendencia
        # (question_status, ETAPA 5) tenha sido resolvida — o chip deixa
        # isso visualmente claro, sem inventar um estado novo aqui: quem
        # decide "resolvida"/"cancelada" continua sendo o backend, nunca
        # o clique nesta notificacao.
        status = notification.get("question_status")
        text = {"RESPONDIDA": "Resolvida", "CANCELADA": "Cancelada"}.get(status, "Pendente")
        chip = QLabel(text)
        chip.setObjectName("Caption")
        chip.setStyleSheet("font-size: 9px; font-weight: 700; padding: 1px 6px; border-radius: 4px; background: rgba(148,163,184,0.18);")
        return chip

    def _open(self, notification: dict):
        proposal_id = notification.get("proposal_id")
        conversation_id = None if proposal_id else notification.get("conversation_id")
        message_id = notification.get("message_id")
        notification_id = notification.get("id")
        self.close()
        if self._on_open_conversation is not None:
            self._on_open_conversation(proposal_id, conversation_id, message_id)
        if notification_id and notification_id > 0:
            try:
                self.service.chat_mark_notification_read(notification_id)
            except Exception:
                pass

    def _mark_all_read(self):
        try:
            self.service.chat_mark_all_notifications_read()
        except Exception:
            self.new_items_banner.setText("Nao foi possivel marcar todas como lidas — toque pra tentar de novo")
            self.new_items_banner.setVisible(True)
            return
        self.refresh()
