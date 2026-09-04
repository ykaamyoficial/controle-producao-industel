from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import shutil
import uuid

from PySide6.QtCore import QEvent, QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFileDialog,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ui.animations import fade_in
from app.ui.background_worker import start_worker
from app.ui.components.app_icon_button import AppIconButton
from app.ui.components.chat_pending_attachments import AttachmentState
from app.ui.chat_attachment_download_worker import AttachmentCacheManager, ChatAttachmentDownloadWorker, cached_attachment_path, safe_attachment_filename
from app.ui.components.chat_message_attachments import MediaViewerDialog, attachment_display_category, attachment_filename, build_media_sequence, resolve_media_kind
from app.ui.components.chat_shared_content import SharedContentPanel
from app.ui.components.mention_compose_bar import MentionComposeBar
from app.ui.components.modern_button import ModernButton
from app.ui.components.proposal_activity_panel import ProposalActivityPanel
from app.ui.components.timeline_entries import (
    GROUP_WINDOW_SECONDS,
    CurrentUserMessageWidget,
    DirectedQuestionWidget,
    InternalNoteWidget,
    OtherUserMessageWidget,
    ReplyMessageWidget,
    TimelineDaySeparator,
    TimelineEntryWidget,
    entry_fingerprint,
)
from app.ui.components.toast_notification import ToastNotification
from app.ui.resilience import show_operation_error
from app.ui.icons import AppIcons, IconSize, make_icon
from app.ui.chat_attachment_upload_worker import ChatAttachmentUploadWorker
from app.ui.process_detail_dialog import ProcessDetailDialog
from app.ui.styles import status_color


NOTE_AREA_OPTIONS = [
    "CONTROLE GERAL",
    "PRODUCAO",
    "GALVANIZACAO",
    "EXPEDICAO",
    "FISCAL",
    "ALMOXARIFADO",
]


def _messages_to_entries(messages: list[dict]) -> list[dict]:
    return [
        {
            "id": message.get("id"),
            "source": "chat",
            "entry_kind": message.get("message_type"),
            "client_message_id": message.get("client_message_id"),
            "author_user_id": message.get("author_user_id"),
            "author_name": message.get("author_name"),
            "mentioned_user_id": message.get("mentioned_user_id"),
            "mentioned_user_name": message.get("mentioned_user_name"),
            "question_status": message.get("question_status"),
            "answered_message_id": message.get("answered_message_id"),
            "body": message.get("body"),
            "area": message.get("area"),
            "created_at": message.get("created_at"),
            "seen_by_count": message.get("seen_by_count"),
            "attachments": message.get("attachments") or [],
        }
        for message in messages
    ]


class InternalNoteDialog(QDialog):
    """Dialogo compacto para registrar uma nota interna manual — nunca
    disparado automaticamente, so quando o usuario escolhe explicitamente
    "Registrar nota interna" no composer."""

    def __init__(self, parent=None, mentionable_users: list[dict] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Registrar nota interna")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        area_label = QLabel("Area de origem")
        layout.addWidget(area_label)
        self.area_combo = QComboBox()
        for area in NOTE_AREA_OPTIONS:
            self.area_combo.addItem(area.title(), area)
        layout.addWidget(self.area_combo)

        recipient_label = QLabel("Destinatario (opcional)")
        layout.addWidget(recipient_label)
        self.recipient_combo = QComboBox()
        self.recipient_combo.addItem("Nenhum — visivel para quem acessa a conversa", None)
        for user in mentionable_users or []:
            self.recipient_combo.addItem(user.get("display_name") or "-", user.get("id"))
        layout.addWidget(self.recipient_combo)

        self.important_checkbox = QCheckBox("Marcar como importante")
        layout.addWidget(self.important_checkbox)

        body_label = QLabel("Nota")
        layout.addWidget(body_label)
        self.body_edit = QTextEdit()
        self.body_edit.setPlaceholderText("Descreva a informacao interna importante...")
        self.body_edit.setMinimumHeight(100)
        layout.addWidget(self.body_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_data(self) -> tuple[str, str, int | None, bool]:
        return (
            self.body_edit.toPlainText().strip(),
            self.area_combo.currentData(),
            self.recipient_combo.currentData(),
            self.important_checkbox.isChecked(),
        )


def _format_datetime(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    return parsed.strftime("%d/%m/%Y %H:%M")


def _parse_day(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _parse_datetime(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _day_label(day) -> str:
    today = datetime.now().date()
    if day == today:
        return "Hoje"
    if day == today - timedelta(days=1):
        return "Ontem"
    return day.strftime("%d/%m/%Y")


class ChatTabButton(QPushButton):
    """Item de navegacao com aparencia de aba (texto + indicador inferior),
    usado no cabecalho do chat para Atividade/Participantes/Informacoes.
    Puramente visual: quem chama continua responsavel por conectar o
    `clicked` e por chamar `set_active()` quando o estado que o botao
    representa mudar (painel aberto/fechado) - o widget nao sabe se a acao
    por tras dele e um toggle ou um disparo unico (ex.: abrir um dialogo)."""

    def __init__(self, text: str, icon, palette: dict, parent=None):
        super().__init__(text, parent)
        self._palette = palette
        self.setObjectName("ChatTabButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setIcon(make_icon(icon, palette.get("muted", "#64748b"), 15))
        self.setIconSize(QSize(15, 15))
        self.setFlat(True)
        self.set_active(False)

    def set_active(self, active: bool) -> None:
        palette = self._palette
        accent = palette.get("accent", "#0078d4")
        muted = palette.get("muted", "#64748b")
        text_color = palette.get("text", "#0f172a")
        color = accent if active else muted
        underline = accent if active else "transparent"
        self.setStyleSheet(f"""
            QPushButton#ChatTabButton {{
                background: transparent;
                border: none;
                border-bottom: 2px solid {underline};
                border-radius: 0;
                padding: 6px 2px 7px 2px;
                color: {color};
                font-weight: {700 if active else 600};
                font-size: 12px;
                text-align: left;
            }}
            QPushButton#ChatTabButton:hover {{
                color: {accent if active else text_color};
            }}
        """)


class _TopFadeOverlay(QWidget):
    """Fade no topo da lista de mensagens: quando ha historico rolado por
    tras do cabecalho, ele dissolve em vez de ser cortado seco - mesma
    sensacao do fade no topo da lista de mensagens do chat do Claude. So
    aparece quando ha algo rolado pra cima (ver _on_scroll_value_changed)."""

    HEIGHT = 32

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._color = QColor("#ffffff")
        self.hide()

    def set_color(self, hex_color: str):
        self._color = QColor(hex_color)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, 0, self.height())
        top = QColor(self._color)
        top.setAlpha(255)
        bottom = QColor(self._color)
        bottom.setAlpha(0)
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(1.0, bottom)
        painter.fillRect(self.rect(), gradient)


class _BottomFadeOverlay(QWidget):
    """Mascara a regiao inteira entre o fim visivel das mensagens e a borda
    inferior real do painel - nao so uma faixa de fade solta no meio do
    caminho. Duas regioes dentro da mesma geometria (ver
    _reposition_compose_overlay, que define altura/posicao):

    - primeiros `fade_height` px: transicao transparente -> opaco (a
      "dissolvencia" visual da mensagem sumindo);
    - resto (da barra de composicao pra baixo ate o fundo real do
      painel): 100% opaco, sem voltar a ficar transparente - garante que
      nenhuma mensagem role e reapareca atras/abaixo da barra.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._color = QColor("#ffffff")
        self._fade_height = 80

    def set_color(self, hex_color: str):
        self._color = QColor(hex_color)
        self.update()

    def set_fade_height(self, fade_height: int):
        self._fade_height = max(1, int(fade_height))
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        total_height = max(1, self.height())
        fade_ratio = min(1.0, self._fade_height / total_height)
        gradient = QLinearGradient(0, 0, 0, total_height)
        for stop, alpha in ((0.0, 0), (fade_ratio * 0.55, 150), (fade_ratio, 255), (1.0, 255)):
            color = QColor(self._color)
            color.setAlpha(alpha)
            gradient.setColorAt(min(1.0, max(0.0, stop)), color)
        painter.fillRect(self.rect(), gradient)


class ChatConversationPanel(QWidget):
    """Timeline + composicao de uma conversa (proposta ou Chat Geral).
    Widget reaproveitavel: usado tanto dentro do dialogo modal quanto
    embutido na coluna central da tela "Chats". Mensagens do time chegam
    misturadas com observacoes das areas e eventos automaticos, que o
    backend ja registra a cada mudanca de status — aqui so mostramos
    tudo junto, sem duplicar nada."""

    entries_loaded = Signal()

    def __init__(self, service, proposal_id: int | None = None, conversation_id: int | None = None, parent=None):
        super().__init__(parent)
        self.service = service
        self.proposal_id = proposal_id
        self.conversation_id = conversation_id
        self.entries: list[dict] = []
        self._entries_by_id: dict[int, dict] = {}
        self._refresh_thread = None
        self._refresh_in_flight = False
        self._refresh_pending = False
        self._closing = False
        self._last_marked_read_message_id: int | None = None
        self._scroll_animation: QPropertyAnimation | None = None
        self._catch_up_to_bottom = False
        self._mentionable_names: list[str] = []
        self._mentionable_users: list[dict] = []
        self._user_sectors: dict[int, str] = {}
        self._entry_widgets: dict[tuple, tuple[QWidget, TimelineEntryWidget]] = {}
        self._day_separator_widgets: dict[object, TimelineDaySeparator] = {}
        self._max_bubble_width = 420
        self._has_more_older = False
        self._oldest_created_at: str | None = None
        self._message_offset = 0
        self._loading_older = False
        self._older_thread = None
        self._upload_thread: QThread | None = None
        self._upload_worker: ChatAttachmentUploadWorker | None = None
        self._download_jobs: dict[int, tuple[QThread, ChatAttachmentDownloadWorker, str]] = {}
        self._attachment_cache = AttachmentCacheManager()
        self._pending_attachment_message_id: int | None = None
        self.proposal: dict | None = None
        self.activity_panel: ProposalActivityPanel | None = None
        self._activity_open = False
        self._activity_animation: QParallelAnimationGroup | None = None
        self._pending_focus_message_id: int | None = None
        self._attachment_drag_active = False
        self.shared_content_panel: SharedContentPanel | None = None
        self._shared_content_open = False
        self._shared_content_animation: QParallelAnimationGroup | None = None
        self._pending_jump_message_id: int | None = None

        if proposal_id is not None:
            try:
                self.proposal = self.service.get_process_dict(proposal_id)
            except Exception:
                self.proposal = None

        self._build()
        self.setAcceptDrops(True)
        self.refresh()
        # Rede de seguranca: cobre o caso do dialogo modal (ChatCenterDialog
        # aberto via process_page.py/main_window.py), que nao recebe o
        # ChatRealtimeClient da MainWindow — sem isso, uma mensagem de outra
        # pessoa so aparecia saindo e reabrindo a conversa.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(15000)
        self._poll_timer.timeout.connect(self.refresh)
        self._poll_timer.start()

    def title(self) -> str:
        if self.proposal_id is None:
            return "Chat Geral"
        if self.proposal:
            return f"Chat — {self.proposal.get('proposta') or self.proposal_id} — {self.proposal.get('cliente') or ''}"
        return "Chat da proposta"

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.drawer: QFrame | None = None
        self._drawer_open = False
        self._drawer_animation: QParallelAnimationGroup | None = None
        self._drawer_participants_layout: QVBoxLayout | None = None

        # Cabecalho (titulo/status + abas Atividade/Participantes/Informacoes,
        # ou so o refresh no Chat Geral) e a UNICA divisoria - QFrame#ChatHeaderCard
        # (styles.py) e flush com o fundo, so um border-bottom marca onde a
        # "parte de cima" termina. Do header pra baixo e tudo edge-to-edge,
        # sem nenhuma margem reservando espaco vazio ao redor.
        if self.proposal_id is not None:
            root.addWidget(self._build_proposal_header())
        else:
            root.addWidget(self._build_general_header())

        self.loading = QLabel("Carregando...")
        self.loading.setObjectName("Caption")
        self.loading.setContentsMargins(16, 6, 16, 0)
        self.loading.setVisible(False)
        root.addWidget(self.loading)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(0)

        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(0)

        self._load_older_btn = ModernButton("Carregar mensagens anteriores", "history")
        self._load_older_btn.clicked.connect(self._load_older_messages)
        self._load_older_btn.setVisible(False)
        left_col.addWidget(self._load_older_btn)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("ChatScrollArea")
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.feed = QWidget()
        self.feed_layout = QVBoxLayout(self.feed)
        self.feed_layout.setContentsMargins(16, 12, 0, 120)
        self.feed_layout.setSpacing(4)
        self.feed_layout.addStretch()
        self.scroll.setWidget(self.feed)

        self._empty_state = self._build_empty_state()

        self._new_messages_btn = AppIconButton(
            AppIcons.ARROW_DOWN,
            "Novas mensagens",
            color="#ffffff",
            accent=True,
            size=IconSize.SM,
            parent=self.scroll.viewport(),
        )
        self._new_messages_btn.clicked.connect(self._scroll_to_bottom_and_hide_button)
        self._new_messages_btn.hide()

        # Fade no topo da lista (mesma sensacao do chat do Claude): so
        # aparece quando ha historico rolado por tras do cabecalho.
        self._top_fade = _TopFadeOverlay(self.scroll.viewport())
        self._top_fade.set_color(self.service.palette.get("bg", "#ffffff"))
        self._reposition_top_fade()

        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_value_changed)
        self.scroll.verticalScrollBar().rangeChanged.connect(self._on_scroll_range_changed)

        feed_stack_host = QWidget()
        feed_stack_host.setObjectName("ChatFeedStack")
        feed_stack_host.setAcceptDrops(True)
        feed_stack_host.setStyleSheet("QWidget#ChatFeedStack { border: 0; }")
        self._feed_stack_host = feed_stack_host
        self._feed_stack = QStackedLayout(feed_stack_host)
        self._feed_stack.setContentsMargins(0, 0, 0, 0)
        self._feed_stack.addWidget(self.scroll)
        self._feed_stack.addWidget(self._empty_state)

        # Campo de composicao sobreposto ao canvas: a lista ocupa a altura
        # inteira e as mensagens continuam passando por tras do composer. O
        # fade e o wrapper ficam como filhos posicionados, sem uma camada cheia
        # interceptando scroll/cliques no restante da conversa.
        self._bottom_fade = _BottomFadeOverlay(feed_stack_host)
        self._bottom_fade.set_color(self.service.palette.get("bg", "#ffffff"))
        self._bottom_fade.raise_()
        self._compose_wrapper = QWidget(feed_stack_host)
        self._compose_wrapper.setObjectName("ComposeBarWrapper")
        compose_wrapper_layout = QHBoxLayout(self._compose_wrapper)
        compose_wrapper_layout.setContentsMargins(16, 0, 16, 14)
        self.compose_bar = MentionComposeBar(self.service)
        self.compose_bar.send_requested.connect(self.send_message)
        self.compose_bar.action_unavailable.connect(self._show_action_unavailable)
        self.compose_bar.attachment_warning.connect(lambda message: ToastNotification(self.window(), message, "error"))
        self.compose_bar.attachment_cancel_requested.connect(self._cancel_attachment_upload)
        self.compose_bar.internal_note_requested.connect(self._open_internal_note_dialog)
        self.compose_bar.height_changed.connect(self._on_compose_height_changed)
        compose_wrapper_layout.addWidget(self.compose_bar)
        self._compose_wrapper.raise_()
        left_col.addWidget(feed_stack_host, 1)
        self._reposition_compose_overlay()

        content_row.addLayout(left_col, 1)

        if self.proposal_id is not None:
            content_row.addSpacing(8)
            content_row.addWidget(self._build_drawer())
            self.activity_panel = ProposalActivityPanel(self.service, self.proposal_id)
            content_row.addSpacing(8)
            content_row.addWidget(self.activity_panel)

        # Fase 7 - "Midia e arquivos": disponivel tanto em propostas quanto no
        # Chat Geral (ao contrario do drawer/atividade, que sao so de proposta).
        content_row.addSpacing(8)
        self.shared_content_panel = SharedContentPanel(self.service)
        self.shared_content_panel.open_attachment_requested.connect(self._open_attachment)
        self.shared_content_panel.download_attachment_requested.connect(self._save_attachment_as)
        self.shared_content_panel.jump_to_message_requested.connect(self._jump_from_shared_content)
        content_row.addWidget(self.shared_content_panel)

        root.addLayout(content_row, 1)

        self._load_mentionable_users()

    def dragEnterEvent(self, event) -> None:
        if self._drag_attachment_paths(event.mimeData()):
            event.acceptProposedAction()
            self._set_attachment_drag_active(True)
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._drag_attachment_paths(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_attachment_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._set_attachment_drag_active(False)
        paths = self._drag_attachment_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        self.compose_bar.add_attachment_paths(paths)
        self.compose_bar.text_edit.setFocus()
        event.acceptProposedAction()

    @staticmethod
    def _drag_attachment_paths(mime_data) -> list[str]:
        if not mime_data or not mime_data.hasUrls():
            return []
        return [url.toLocalFile() for url in mime_data.urls() if url.isLocalFile()]

    def _set_attachment_drag_active(self, active: bool) -> None:
        if active == self._attachment_drag_active or not hasattr(self, "_feed_stack_host"):
            return
        self._attachment_drag_active = active
        if active:
            palette = self.service.palette
            self._feed_stack_host.setStyleSheet(
                f"QWidget#ChatFeedStack {{ border: 2px dashed {palette.get('accent', '#0078d4')}; "
                f"background: {palette.get('surface_alt', '#e2e8f0')}; }}"
            )
            self.loading.setText("Solte os arquivos para anexar")
            self.loading.setVisible(True)
            return
        self._feed_stack_host.setStyleSheet("QWidget#ChatFeedStack { border: 0; }")
        if self.loading.text() == "Solte os arquivos para anexar":
            self.loading.setVisible(False)
            self.loading.setText("Carregando...")

    def _build_empty_state(self) -> QWidget:
        widget = QWidget()
        widget.setVisible(False)
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)

        palette = self.service.palette
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setPixmap(make_icon(AppIcons.CHAT, palette.get("muted", "#94a3b8"), 32).pixmap(32, 32))
        layout.addWidget(icon_label)

        title = QLabel("Nenhuma mensagem nesta proposta")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-weight: 700; font-size: 13px;")
        layout.addWidget(title)

        subtitle = QLabel("Inicie uma conversa com os participantes da proposta.")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setObjectName("Caption")
        layout.addWidget(subtitle)

        return widget

    def _update_empty_state(self) -> None:
        has_entries = bool(self.entries)
        self.scroll.setVisible(has_entries)
        self._empty_state.setVisible(not has_entries)
        self._feed_stack.setCurrentWidget(self.scroll if has_entries else self._empty_state)
        self._bottom_fade.raise_()
        self._compose_wrapper.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        new_width = max(240, int(self.scroll.viewport().width() * 0.68))
        if abs(new_width - self._max_bubble_width) > 6:
            self._max_bubble_width = new_width
            for _row, content in self._entry_widgets.values():
                self._apply_bubble_width(content)
            # setMaximumWidth() muda a largura de quebra do texto, o que muda a
            # altura necessaria de cada bolha — forca o QVBoxLayout a recalcular
            # tudo agora em vez de confiar soh na invalidacao implicita do Qt.
            self.feed_layout.invalidate()
            self.feed_layout.activate()
        self._reposition_new_messages_button()
        self._reposition_top_fade()
        self._reposition_compose_overlay()

    def _apply_bubble_width(self, content: TimelineEntryWidget):
        if isinstance(content, (CurrentUserMessageWidget, OtherUserMessageWidget, ReplyMessageWidget)):
            content.set_max_bubble_width(self._max_bubble_width)

    def _is_scrolled_to_bottom(self, threshold: int = 48) -> bool:
        bar = self.scroll.verticalScrollBar()
        return bar.value() >= bar.maximum() - threshold

    def _reposition_new_messages_button(self):
        btn = self._new_messages_btn
        btn.adjustSize()
        viewport = self.scroll.viewport()
        x = (viewport.width() - btn.width()) // 2
        y = viewport.height() - btn.height() - 118
        btn.move(max(0, x), max(0, y))

    def _reposition_top_fade(self):
        viewport = self.scroll.viewport()
        self._top_fade.setFixedWidth(viewport.width())
        self._top_fade.move(0, 0)

    def _reposition_compose_overlay(self):
        host = self._compose_wrapper.parentWidget()
        if host is None:
            return
        width = host.width()
        height = host.height()
        wrapper_height = max(self._compose_wrapper.sizeHint().height(), 58)
        wrapper_y = max(0, height - wrapper_height)
        self._compose_wrapper.setGeometry(0, wrapper_y, width, wrapper_height)

        # fade_height e so o tamanho da TRANSICAO (transparente -> opaco).
        # O overlay em si cobre bem mais que isso: comeca fade_height px
        # acima do topo da barra e vai ate o fundo real do painel (height),
        # nunca so ate o topo da barra - senao a regiao atras/abaixo da
        # barra (quando ela cresce com texto multi-linha, por exemplo) fica
        # sem nenhuma mascara e mensagens rolando voltam a aparecer ali.
        # _BottomFadeOverlay.paintEvent so faz a transicao nos primeiros
        # fade_height px do proprio overlay; o resto fica 100% opaco.
        fade_height = 80
        overlay_top = max(0, wrapper_y - fade_height)
        overlay_height = height - overlay_top
        self._bottom_fade.set_fade_height(fade_height)
        self._bottom_fade.setGeometry(0, overlay_top, width, overlay_height)
        self._bottom_fade.raise_()
        self._compose_wrapper.raise_()

    def _on_compose_height_changed(self):
        bottom_margin = max(120, self._compose_wrapper.sizeHint().height() + 28)
        margins = self.feed_layout.contentsMargins()
        if margins.bottom() != bottom_margin:
            self.feed_layout.setContentsMargins(margins.left(), margins.top(), margins.right(), bottom_margin)
        self._reposition_compose_overlay()
        self._reposition_new_messages_button()

    def _show_new_messages_button(self):
        self._reposition_new_messages_button()
        self._new_messages_btn.show()
        self._new_messages_btn.raise_()
        self._top_fade.raise_()

    def _scroll_to_bottom_and_hide_button(self):
        self._new_messages_btn.hide()
        self._scroll_to_bottom()

    def _on_scroll_value_changed(self, value):
        if self._new_messages_btn.isVisible() and self._is_scrolled_to_bottom():
            self._new_messages_btn.hide()
        if value > 0:
            self._top_fade.raise_()
            self._top_fade.show()
        else:
            self._top_fade.hide()

    def _build_proposal_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("ChatHeaderCard")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(16, 10, 16, 0)
        layout.setSpacing(2)

        palette = self.service.palette
        proposal = self.proposal or {}
        area, _label, status = self.service.current_location(proposal) if proposal else ("", "", "")

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        proposal_label = QLabel(proposal.get("proposta") or str(self.proposal_id))
        proposal_label.setStyleSheet("font-size: 17px; font-weight: 800;")
        title_col.addWidget(proposal_label)
        client_label = QLabel(proposal.get("cliente") or "-")
        client_label.setObjectName("Caption")
        title_col.addWidget(client_label)
        top_row.addLayout(title_col)

        top_row.addStretch()

        if status:
            bg, fg = status_color(status, palette, area or "")
            status_badge = QLabel(self.service.status_label(status))
            status_badge.setStyleSheet(
                f"background: {bg}; color: {fg}; border-radius: 9px; padding: 2px 10px; font-weight: 700; font-size: 11px;"
            )
            top_row.addWidget(status_badge)

        refresh_btn = AppIconButton(AppIcons.REFRESH, palette=palette, size=IconSize.LG, tooltip="Atualizar conversa")
        refresh_btn.setFixedSize(36, 36)
        refresh_btn.clicked.connect(self.refresh)
        top_row.addWidget(refresh_btn)

        self.info_btn = AppIconButton(AppIcons.INFO, palette=palette, size=IconSize.LG, tooltip="Ver detalhes da proposta")
        self.info_btn.setFixedSize(36, 36)
        self.info_btn.clicked.connect(self._toggle_drawer)
        top_row.addWidget(self.info_btn)
        layout.addLayout(top_row)

        tabs_row = QHBoxLayout()
        tabs_row.setContentsMargins(0, 4, 0, 0)
        tabs_row.setSpacing(18)
        self.activity_btn = ChatTabButton("Atividade", AppIcons.HISTORY, palette)
        self.activity_btn.clicked.connect(self._toggle_activity_panel)
        tabs_row.addWidget(self.activity_btn)

        self.participants_btn = ChatTabButton("Participantes", AppIcons.CHAT, palette)
        self.participants_btn.clicked.connect(self._toggle_drawer)
        tabs_row.addWidget(self.participants_btn)

        self.info_header_btn = ChatTabButton("Informacoes", AppIcons.INFO, palette)
        self.info_header_btn.clicked.connect(self._open_full_details)
        tabs_row.addWidget(self.info_header_btn)

        self.shared_content_btn = ChatTabButton("Midia e arquivos", AppIcons.ATTACH, palette)
        self.shared_content_btn.clicked.connect(self._toggle_shared_content_panel)
        tabs_row.addWidget(self.shared_content_btn)
        tabs_row.addStretch()
        layout.addLayout(tabs_row)

        self._apply_header_shadow(header)
        return header

    def _build_general_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("ChatHeaderCard")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 10, 16, 10)
        self.shared_content_btn = ChatTabButton("Midia e arquivos", AppIcons.ATTACH, self.service.palette)
        self.shared_content_btn.clicked.connect(self._toggle_shared_content_panel)
        layout.addWidget(self.shared_content_btn)
        layout.addStretch()
        refresh_btn = AppIconButton(AppIcons.REFRESH, palette=self.service.palette, size=IconSize.LG, tooltip="Atualizar conversa")
        refresh_btn.setFixedSize(36, 36)
        refresh_btn.clicked.connect(self.refresh)
        layout.addWidget(refresh_btn)
        self._apply_header_shadow(header)
        return header

    def _apply_header_shadow(self, header: QFrame) -> None:
        """Profundidade: o cabecalho "flutua" sobre o canvas mais escuro das
        mensagens ({bg} vs {surface} do header) — mesmo padrao de sombra
        usado nos cards do dashboard (app/ui/components/card_indicador.py)."""
        shadow = QGraphicsDropShadowEffect(header)
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 3)
        shadow_color = QColor(self.service.palette.get("text", "#0f172a"))
        shadow_color.setAlpha(28)
        shadow.setColor(shadow_color)
        header.setGraphicsEffect(shadow)

    def _build_drawer(self) -> QFrame:
        self.drawer = QFrame()
        self.drawer.setObjectName("Panel")
        self.drawer.setMinimumWidth(0)
        self.drawer.setMaximumWidth(0)
        layout = QVBoxLayout(self.drawer)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("Detalhes da proposta")
        title.setStyleSheet("font-weight: 800;")
        layout.addWidget(title)

        proposal = self.proposal or {}
        area, _label, _status = self.service.current_location(proposal) if proposal else ("", "", "")
        fields = [
            ("Cliente", proposal.get("cliente") or "-"),
            ("Obra/Site", proposal.get("obra_site") or "-"),
            ("Prazo", proposal.get("prazo_entrega") or "-"),
            ("Peso", f"{proposal.get('peso') or '0'} kg"),
            ("Area atual", str(area or "-").replace("_", " ").title()),
        ]
        for label, value in fields:
            cell = QVBoxLayout()
            cell.setSpacing(0)
            caption = QLabel(label)
            caption.setObjectName("Caption")
            content = QLabel(str(value))
            content.setStyleSheet("font-weight: 700;")
            content.setWordWrap(True)
            cell.addWidget(caption)
            cell.addWidget(content)
            layout.addLayout(cell)

        participants_title = QLabel("Participantes")
        participants_title.setStyleSheet("font-weight: 800;")
        layout.addWidget(participants_title)
        self._drawer_participants_layout = QVBoxLayout()
        self._drawer_participants_layout.setSpacing(4)
        layout.addLayout(self._drawer_participants_layout)

        layout.addStretch()

        question_btn = ModernButton("Fazer pergunta", "chat")
        question_btn.clicked.connect(lambda: self.focus_question_mode())
        layout.addWidget(question_btn)

        return self.drawer

    def _toggle_drawer(self):
        if self.drawer is None:
            return
        self._drawer_open = not self._drawer_open
        if hasattr(self, "participants_btn"):
            self.participants_btn.set_active(self._drawer_open)
        target = 300 if self._drawer_open else 0
        if self._drawer_animation is not None:
            self._drawer_animation.stop()

        min_anim = QPropertyAnimation(self.drawer, b"minimumWidth", self.drawer)
        min_anim.setDuration(240)
        min_anim.setStartValue(self.drawer.minimumWidth())
        min_anim.setEndValue(target)
        min_anim.setEasingCurve(QEasingCurve.OutCubic)

        max_anim = QPropertyAnimation(self.drawer, b"maximumWidth", self.drawer)
        max_anim.setDuration(240)
        max_anim.setStartValue(self.drawer.maximumWidth())
        max_anim.setEndValue(target)
        max_anim.setEasingCurve(QEasingCurve.OutCubic)

        group = QParallelAnimationGroup(self.drawer)
        group.addAnimation(min_anim)
        group.addAnimation(max_anim)

        if self._drawer_open:
            effect = QGraphicsOpacityEffect(self.drawer)
            self.drawer.setGraphicsEffect(effect)
            opacity_anim = QPropertyAnimation(effect, b"opacity", self.drawer)
            opacity_anim.setDuration(240)
            opacity_anim.setStartValue(0.0)
            opacity_anim.setEndValue(1.0)
            opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
            group.addAnimation(opacity_anim)
            group.finished.connect(lambda: self.drawer.setGraphicsEffect(None))

        self._drawer_animation = group
        group.start()

    def _toggle_activity_panel(self):
        if self.activity_panel is None:
            return
        self._activity_open = not self._activity_open
        if hasattr(self, "activity_btn"):
            self.activity_btn.set_active(self._activity_open)
        target = 340 if self._activity_open else 0
        if self._activity_animation is not None:
            self._activity_animation.stop()

        min_anim = QPropertyAnimation(self.activity_panel, b"minimumWidth", self.activity_panel)
        min_anim.setDuration(240)
        min_anim.setStartValue(self.activity_panel.minimumWidth())
        min_anim.setEndValue(target)
        min_anim.setEasingCurve(QEasingCurve.OutCubic)

        max_anim = QPropertyAnimation(self.activity_panel, b"maximumWidth", self.activity_panel)
        max_anim.setDuration(240)
        max_anim.setStartValue(self.activity_panel.maximumWidth())
        max_anim.setEndValue(target)
        max_anim.setEasingCurve(QEasingCurve.OutCubic)

        group = QParallelAnimationGroup(self.activity_panel)
        group.addAnimation(min_anim)
        group.addAnimation(max_anim)

        if self._activity_open:
            self.activity_panel.refresh()
            effect = QGraphicsOpacityEffect(self.activity_panel)
            self.activity_panel.setGraphicsEffect(effect)
            opacity_anim = QPropertyAnimation(effect, b"opacity", self.activity_panel)
            opacity_anim.setDuration(240)
            opacity_anim.setStartValue(0.0)
            opacity_anim.setEndValue(1.0)
            opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
            group.addAnimation(opacity_anim)
            group.finished.connect(lambda: self.activity_panel.setGraphicsEffect(None))

        self._activity_animation = group
        group.start()

    def _toggle_shared_content_panel(self):
        if self.shared_content_panel is None:
            return
        self._shared_content_open = not self._shared_content_open
        if hasattr(self, "shared_content_btn"):
            self.shared_content_btn.set_active(self._shared_content_open)
        target = 320 if self._shared_content_open else 0
        if self._shared_content_animation is not None:
            self._shared_content_animation.stop()

        min_anim = QPropertyAnimation(self.shared_content_panel, b"minimumWidth", self.shared_content_panel)
        min_anim.setDuration(240)
        min_anim.setStartValue(self.shared_content_panel.minimumWidth())
        min_anim.setEndValue(target)
        min_anim.setEasingCurve(QEasingCurve.OutCubic)

        max_anim = QPropertyAnimation(self.shared_content_panel, b"maximumWidth", self.shared_content_panel)
        max_anim.setDuration(240)
        max_anim.setStartValue(self.shared_content_panel.maximumWidth())
        max_anim.setEndValue(target)
        max_anim.setEasingCurve(QEasingCurve.OutCubic)

        group = QParallelAnimationGroup(self.shared_content_panel)
        group.addAnimation(min_anim)
        group.addAnimation(max_anim)

        if self._shared_content_open:
            self.shared_content_panel.set_conversation_id(self.conversation_id)
            self.shared_content_panel.refresh()
            effect = QGraphicsOpacityEffect(self.shared_content_panel)
            self.shared_content_panel.setGraphicsEffect(effect)
            opacity_anim = QPropertyAnimation(effect, b"opacity", self.shared_content_panel)
            opacity_anim.setDuration(240)
            opacity_anim.setStartValue(0.0)
            opacity_anim.setEndValue(1.0)
            opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
            group.addAnimation(opacity_anim)
            group.finished.connect(lambda: self.shared_content_panel.setGraphicsEffect(None))

        self._shared_content_animation = group
        group.start()

    def _open_full_details(self):
        if self.proposal_id is None:
            return
        dialog = ProcessDetailDialog(self.service, self.proposal_id, self)
        dialog.exec()

    def _refresh_drawer_participants(self):
        layout = self._drawer_participants_layout
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        participants = self.participants()
        if not participants:
            empty = QLabel("Sem participantes ainda.")
            empty.setObjectName("Caption")
            layout.addWidget(empty)
            return
        for person in participants:
            row = QHBoxLayout()
            name_label = QLabel(person.get("name") or "-")
            row.addWidget(name_label)
            row.addStretch()
            layout.addLayout(row)

    def _load_mentionable_users(self):
        try:
            users = self.service.chat_mentionable_users()
        except Exception:
            users = []
        current_user_id = (self.service.user or {}).get("id")
        others = [user for user in users if user.get("id") != current_user_id]
        self.compose_bar.set_mentionable_users(others)
        self._mentionable_users = others
        self._mentionable_names = [user.get("display_name") for user in users if user.get("display_name")]
        self._user_sectors = {user.get("id"): user.get("sector") for user in users if user.get("sector")}

    def _show_action_unavailable(self, action: str):
        messages = {
            "attach": "Anexos ainda nao estao disponiveis nesta versao.",
            "mic": "Gravacao de audio ainda nao esta disponivel nesta versao.",
        }
        ToastNotification(self.window(), messages.get(action, "Ainda nao disponivel nesta versao."), "error")

    def refresh(self):
        if self._closing:
            return
        if self._refresh_in_flight:
            self._refresh_pending = True
            return
        self._refresh_in_flight = True
        self._set_loading(True)
        if self.proposal_id is not None:
            loader = lambda: self.service.chat_proposal_timeline(self.proposal_id)
        else:
            def loader():
                page = self.service.chat_messages_page(self.conversation_id, {"limit": 50, "offset": 0})
                total = int(page.get("total") or 0)
                offset = max(0, total - 50)
                if offset:
                    page = self.service.chat_messages_page(self.conversation_id, {"limit": 50, "offset": offset})
                return {
                    "conversation_id": self.conversation_id,
                    "items": _messages_to_entries(page.get("items") or []),
                    "has_more": offset > 0,
                    "message_offset": offset,
                }
        self._refresh_thread = start_worker(self, loader, self._refresh_success, self._refresh_error)

    def _refresh_success(self, timeline: dict):
        if self._closing:
            self._finish_refresh()
            return
        self.conversation_id = timeline.get("conversation_id")
        if self.shared_content_panel is not None:
            self.shared_content_panel.set_conversation_id(self.conversation_id)
        self.entries = timeline.get("items") or []
        self._has_more_older = bool(timeline.get("has_more"))
        self._message_offset = int(timeline.get("message_offset") or 0)
        self._oldest_created_at = self.entries[0].get("created_at") if self.entries else None
        self._update_load_older_button()
        self._annotate_entries()
        has_new_from_others = self._render_entries()
        self._update_empty_state()
        self._refresh_drawer_participants()
        self._set_loading(False)
        # so avanca o cursor de leitura se o usuario realmente estava no
        # fundo do scroll — se ele estava lendo historico quando este
        # refresh trouxe mensagem nova de outra pessoa, essa mensagem
        # continua nao lida ate ele efetivamente rolar ate ela (vale tanto
        # pro refresh manual quanto pro disparado por evento realtime).
        if not has_new_from_others:
            self._mark_read()
        self._consume_pending_focus()
        self.entries_loaded.emit()
        self._finish_refresh()

    def _update_load_older_button(self):
        self._load_older_btn.setVisible(self._has_more_older)

    def _load_older_messages(self):
        if self._closing:
            return
        if self._loading_older or (self.proposal_id is None and not self._has_more_older) or (self.proposal_id is not None and not self._oldest_created_at):
            return
        self._loading_older = True
        self._load_older_btn.setEnabled(False)
        self._load_older_btn.setText("Carregando...")
        if self.proposal_id is not None:
            loader = lambda: self.service.chat_proposal_timeline(self.proposal_id, before=self._oldest_created_at, limit=100)
        else:
            offset = max(0, self._message_offset - 50)
            def loader():
                page = self.service.chat_messages_page(self.conversation_id, {"limit": 50, "offset": offset})
                return {
                    "items": _messages_to_entries(page.get("items") or []),
                    "has_more": offset > 0,
                    "message_offset": offset,
                }
        self._older_thread = start_worker(self, loader, self._older_loaded, self._older_error)

    def _older_loaded(self, timeline: dict):
        if self._closing:
            return
        self._loading_older = False
        self._load_older_btn.setEnabled(True)
        self._load_older_btn.setText("Carregar mensagens anteriores")
        older_entries = timeline.get("items") or []
        self._has_more_older = bool(timeline.get("has_more"))
        if older_entries:
            if self.proposal_id is not None:
                self.entries = older_entries + self.entries
                self._oldest_created_at = older_entries[0].get("created_at")
            else:
                self.entries = older_entries + self.entries
                self._message_offset = int(timeline.get("message_offset") or 0)
            self._annotate_entries()
        self._update_load_older_button()

        bar = self.scroll.verticalScrollBar()
        old_max = bar.maximum()
        old_value = bar.value()
        self._render_entries(suppress_autoscroll=True)

        def _restore_scroll():
            bar.setValue(old_value + (bar.maximum() - old_max))

        QTimer.singleShot(0, _restore_scroll)
        self._continue_pending_jump()

    def _continue_pending_jump(self) -> None:
        message_id = self._pending_jump_message_id
        if message_id is None:
            return
        if ("chat", message_id) in self._entry_widgets:
            self._pending_jump_message_id = None
            self._jump_to_message(message_id)
            return
        if self._has_more_older and not self._loading_older:
            self._load_older_messages()
            return
        self._pending_jump_message_id = None
        ToastNotification(self.window(), "Mensagem original nao esta mais disponivel no historico carregado.", "error")

    def _older_error(self, exc):
        self._loading_older = False
        self._load_older_btn.setEnabled(True)
        self._load_older_btn.setText("Carregar mensagens anteriores")
        ToastNotification(self.window(), str(exc), "error")

    def _annotate_entries(self):
        for entry in self.entries:
            if entry.get("source") == "chat":
                entry["author_sector"] = self._user_sectors.get(entry.get("author_user_id"))
        self._entries_by_id = {entry.get("id"): entry for entry in self.entries if entry.get("source") == "chat"}

    def _append_sent_message(self, message: dict):
        """Mostra a mensagem enviada na hora, sem esperar o round-trip do
        refresh() (mesmo comportamento otimista do WhatsApp) — o refresh()
        chamado logo em seguida ainda reconcilia com o servidor (seen_by_count,
        etc.), casando pelo mesmo id e sem duplicar a entrada."""
        if not isinstance(message, dict) or message.get("id") is None:
            return
        existing_ids = {entry.get("id") for entry in self.entries if entry.get("source") == "chat"}
        if message["id"] in existing_ids:
            return
        previous_entries = list(self.entries)
        try:
            self.entries.append(_messages_to_entries([message])[0])
            self._annotate_entries()
            self._render_entries()
        except Exception:
            self.entries = previous_entries
            self._annotate_entries()

    def apply_realtime_event(self, event_type: str, data: dict) -> None:
        if event_type not in {"attachment.created", "attachment.deleted"} or not isinstance(data, dict):
            return
        attachment = data.get("attachment")
        if not isinstance(attachment, dict):
            return
        message_id = data.get("message_id") or attachment.get("message_id")
        if message_id is None:
            return
        for entry in self.entries:
            if entry.get("source") == "chat" and entry.get("id") == message_id:
                attachments = entry.setdefault("attachments", [])
                existing = next((item for item in attachments if isinstance(item, dict) and item.get("id") == attachment.get("id")), None)
                if existing is None:
                    attachments.append(dict(attachment))
                    if event_type == "attachment.created" and self.shared_content_panel is not None:
                        # Fase 7: insere no topo do painel "Midia e arquivos" se estiver aberto
                        # e o item pertencer ao filtro ativo -- sem reconstruir a lista inteira.
                        realtime_attachment = dict(attachment)
                        realtime_attachment.setdefault("message_id", message_id)
                        self.shared_content_panel.notify_new_attachment(realtime_attachment, sender_name=entry.get("author_name"))
                else:
                    existing.update(dict(attachment))
                self._annotate_entries()
                self._render_entries()
                return

    def _refresh_error(self, exc):
        if self._closing:
            self._finish_refresh()
            return
        self._set_loading(False)
        show_operation_error(self, exc, self.refresh, title="Chat")
        self._finish_refresh()

    def _finish_refresh(self):
        self._refresh_in_flight = False
        if self._refresh_pending and not self._closing:
            self._refresh_pending = False
            QTimer.singleShot(0, self.refresh)

    def _set_loading(self, loading: bool):
        self.loading.setVisible(loading)

    def cleanup(self):
        if self._closing:
            return
        self._closing = True
        self._stop_all_media()
        if hasattr(self, "_poll_timer"):
            self._poll_timer.stop()
        if self._scroll_animation is not None:
            self._scroll_animation.stop()
        if self._upload_worker is not None:
            self._upload_worker.cancel()
        for _attachment_id, (_thread, worker, _mode) in list(self._download_jobs.items()):
            worker.cancel()
        if self._upload_thread is not None:
            try:
                if self._upload_thread.isRunning():
                    self._upload_thread.quit()
                    self._upload_thread.wait(3000)
            except RuntimeError:
                pass
            self._upload_thread = None
            self._upload_worker = None
        for thread_name in ("_refresh_thread", "_older_thread"):
            thread = getattr(self, thread_name, None)
            try:
                if thread is not None and thread.isRunning():
                    thread.quit()
                    thread.wait(2000)
            except RuntimeError:
                pass
            setattr(self, thread_name, None)

    def _stop_all_media(self) -> None:
        """Pausa/libera qualquer video ou audio tocando na conversa (Fase 4)."""
        for _row, content in list(self._entry_widgets.values()):
            stop_media = getattr(content, "stop_media", None)
            if callable(stop_media):
                try:
                    stop_media()
                except RuntimeError:
                    pass

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)

    def event(self, event):
        if event.type() == QEvent.DeferredDelete:
            self.cleanup()
        return super().event(event)

    def participants(self) -> list[dict]:
        seen: dict[int, dict] = {}
        for entry in self.entries:
            author_id = entry.get("author_user_id")
            if not author_id or author_id in seen:
                continue
            seen[author_id] = {"id": author_id, "name": entry.get("author_name") or "-", "area": entry.get("area")}
        return list(seen.values())

    def focus_question_mode(self, mentioned_user: dict | None = None):
        self.compose_bar.focus_with_mention(mentioned_user)

    def _mark_read(self):
        if not self.conversation_id:
            return
        chat_entries = [entry for entry in self.entries if entry.get("source") == "chat"]
        if not chat_entries:
            return
        last_id = max(int(entry["id"]) for entry in chat_entries)
        if self._last_marked_read_message_id is not None and last_id <= self._last_marked_read_message_id:
            return
        try:
            self.service.chat_mark_read(self.conversation_id, last_id)
        except Exception:
            return
        self._last_marked_read_message_id = last_id
        # so avisa depois que o backend confirmou — o badge global do
        # cabecalho nao pode adiantar a leitura.
        on_marked_read = getattr(self.service, "on_conversation_marked_read", None)
        if callable(on_marked_read):
            on_marked_read()

    def _compute_grouping(self, filtered: list[dict]) -> list[bool]:
        flags: list[bool] = []
        last_author = None
        last_time = None
        last_groupable = False
        for entry in filtered:
            groupable = (
                entry.get("source") == "chat"
                and entry.get("entry_kind") == "MENSAGEM"
                and not entry.get("answered_message_id")
            )
            author = entry.get("author_user_id")
            created = _parse_datetime(entry.get("created_at"))
            grouped = (
                groupable
                and last_groupable
                and author is not None
                and author == last_author
                and last_time is not None
                and created is not None
                and (created - last_time).total_seconds() <= GROUP_WINDOW_SECONDS
            )
            flags.append(grouped)
            last_author = author
            last_time = created
            last_groupable = groupable
        return flags

    def _dispatch_entry_widget(self, entry: dict, current_user_id, grouped: bool) -> tuple[QWidget, TimelineEntryWidget]:
        kind = entry.get("entry_kind") or "MENSAGEM"

        if entry.get("answered_message_id"):
            enriched = dict(entry)
            enriched["_reply_original"] = self._entries_by_id.get(entry.get("answered_message_id"))
            content = ReplyMessageWidget(enriched, self.service, current_user_id, self._mentionable_names, grouped)
            content.jump_to_message_requested.connect(self._jump_to_message)
            self._connect_entry_widget(content)
            align = "right" if entry.get("author_user_id") == current_user_id else "left"
            return self._wrap_row(content, align), content
        if kind == "PERGUNTA":
            content = DirectedQuestionWidget(entry, self.service, current_user_id, self._mentionable_names, grouped)
            content.answer_requested.connect(self._answer_question)
            content.cancel_requested.connect(self._cancel_question)
            content.reassign_requested.connect(self._reassign_question)
            self._connect_entry_widget(content)
            if entry.get("mentioned_user_id") == current_user_id and not entry.get("viewed_at"):
                try:
                    self.service.chat_mark_question_viewed(entry.get("id"))
                except Exception:
                    pass
            return content, content
        if kind == "NOTA_INTERNA":
            content = InternalNoteWidget(entry, self.service, current_user_id, self._mentionable_names, grouped)
            self._connect_entry_widget(content)
            return content, content
        if entry.get("author_user_id") == current_user_id:
            content = CurrentUserMessageWidget(entry, self.service, current_user_id, self._mentionable_names, grouped)
            content.reply_requested.connect(self._start_reply)
            self._connect_entry_widget(content)
            return self._wrap_row(content, "right"), content
        content = OtherUserMessageWidget(entry, self.service, current_user_id, self._mentionable_names, grouped)
        content.reply_requested.connect(self._start_reply)
        self._connect_entry_widget(content)
        return self._wrap_row(content, "left"), content

    def _connect_entry_widget(self, content: TimelineEntryWidget) -> None:
        content.attachment_download_requested.connect(self._save_attachment_as)
        content.attachment_open_requested.connect(self._open_attachment)
        content.attachment_preview_requested.connect(self._preview_attachment)
        content.attachment_delete_requested.connect(self._delete_attachment)

    def _start_reply(self, message_id: int):
        original = self._entries_by_id.get(message_id)
        if original is None:
            return
        self.compose_bar.set_reply_preview(original.get("author_name"), original.get("body"), message_id)

    def _jump_to_message(self, message_id: int):
        cached = self._entry_widgets.get(("chat", message_id))
        if cached is None:
            ToastNotification(self.window(), "Mensagem original nao esta carregada nesta pagina.", "error")
            return
        row, _content = cached
        self.scroll.ensureWidgetVisible(row)
        self._flash_highlight(row)

    def _jump_from_shared_content(self, message_id: int) -> None:
        """Fase 7 - "Ir para mensagem": fecha o painel de midia/arquivos e localiza
        a mensagem, carregando paginas historicas adicionais se ela ainda nao
        estiver no lote atual (sem baixar o historico inteiro de uma vez)."""
        if self._shared_content_open:
            self._toggle_shared_content_panel()
        if ("chat", message_id) in self._entry_widgets:
            self._jump_to_message(message_id)
            return
        if not self._has_more_older:
            ToastNotification(self.window(), "Mensagem original nao esta mais disponivel no historico carregado.", "error")
            return
        self._pending_jump_message_id = message_id
        if not self._loading_older:
            self._load_older_messages()

    def focus_message(self, message_id: int):
        """Usado pela Central de Notificacoes: rola ate a mensagem/pergunta
        alvo e destaca. Se o timeline ainda nao carregou (refresh() em voo),
        agenda uma unica tentativa apos o proximo carregamento bem-sucedido."""
        if ("chat", message_id) in self._entry_widgets:
            self._jump_to_message(message_id)
            return
        self._pending_focus_message_id = message_id

    def _consume_pending_focus(self):
        message_id = getattr(self, "_pending_focus_message_id", None)
        if message_id is None:
            return
        self._pending_focus_message_id = None
        if ("chat", message_id) in self._entry_widgets:
            QTimer.singleShot(0, lambda: self._jump_to_message(message_id))

    def _flash_highlight(self, row: QWidget):
        original_style = row.styleSheet()
        row.setStyleSheet(original_style + "background: rgba(0, 120, 212, 60);")
        QTimer.singleShot(700, lambda: row.setStyleSheet(original_style))

    def _wrap_row(self, content: QWidget, align: str) -> QWidget:
        row = QWidget()
        row.setAttribute(Qt.WA_StyledBackground, True)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        if align in ("right", "center"):
            row_layout.addStretch()
        row_layout.addWidget(content)
        if align in ("left", "center"):
            row_layout.addStretch()
        return row

    def _render_entries(self, *, suppress_autoscroll: bool = False) -> bool:
        """Retorna True se chegou entrada nova de outra pessoa enquanto o
        usuario NAO estava no fundo do scroll (ou seja, ele esta lendo
        historico) — quem chama usa isso pra decidir se pode avancar o
        cursor de leitura (ETAPA 7: refresh disparado por evento realtime
        nao pode marcar como lida uma mensagem que o usuario nem chegou a
        ver por estar rolado pra cima)."""
        current_user_id = (self.service.user or {}).get("id")
        filtered = self.entries
        grouped_flags = self._compute_grouping(filtered)

        at_bottom = self._is_scrolled_to_bottom()
        has_new_from_others = False

        seen_keys: set[tuple] = set()
        seen_days: set = set()
        last_day = None
        insert_index = 0
        for entry, grouped in zip(filtered, grouped_flags):
            entry_day = _parse_day(entry.get("created_at"))
            if entry_day is not None and entry_day != last_day:
                separator = self._day_separator_widgets.get(entry_day)
                if separator is None:
                    separator = TimelineDaySeparator(_day_label(entry_day), self.service)
                    self._day_separator_widgets[entry_day] = separator
                else:
                    # reusa o widget existente (nao recria a cada refresh) — so
                    # atualiza o texto, caso "Hoje"/"Ontem" tenham ficado
                    # desatualizados por o app continuar aberto ate virar o dia.
                    separator.update_text(_day_label(entry_day))
                    self.feed_layout.removeWidget(separator)
                self.feed_layout.insertWidget(insert_index, separator)
                seen_days.add(entry_day)
                insert_index += 1
                last_day = entry_day

            key = (entry.get("source"), entry.get("id"))
            seen_keys.add(key)
            cached = self._entry_widgets.get(key)

            if cached is not None:
                row, content = cached
                if content._fingerprint != entry_fingerprint(entry, grouped):
                    stop_media = getattr(content, "stop_media", None)
                    if callable(stop_media):
                        try:
                            stop_media()
                        except RuntimeError:
                            pass
                    self.feed_layout.removeWidget(row)
                    row.deleteLater()
                    row, content = self._dispatch_entry_widget(entry, current_user_id, grouped)
                    self._apply_bubble_width(content)
                    self._entry_widgets[key] = (row, content)
                    self.feed_layout.insertWidget(insert_index, row)
                else:
                    self.feed_layout.removeWidget(row)
                    self.feed_layout.insertWidget(insert_index, row)
            else:
                row, content = self._dispatch_entry_widget(entry, current_user_id, grouped)
                self._apply_bubble_width(content)
                self.feed_layout.insertWidget(insert_index, row)
                self._entry_widgets[key] = (row, content)
                is_mine = entry.get("source") == "chat" and entry.get("author_user_id") == current_user_id
                # Fade de opacidade apenas — nunca animar pos()/geometry() de um
                # widget gerenciado por layout (QVBoxLayout reposiciona os itens
                # a cada insercao/remocao, e uma animacao de posicao em voo fica
                # "puxando" o widget de volta para uma coordenada que o layout ja
                # abandonou, causando sobreposicao visual).
                if is_mine:
                    fade_in(row, duration=160)
                else:
                    fade_in(row, duration=220)
                    if not at_bottom:
                        has_new_from_others = True
            insert_index += 1

        for key in list(self._entry_widgets.keys()):
            if key not in seen_keys:
                row, content = self._entry_widgets.pop(key)
                stop_media = getattr(content, "stop_media", None)
                if callable(stop_media):
                    try:
                        stop_media()
                    except RuntimeError:
                        pass
                self.feed_layout.removeWidget(row)
                row.deleteLater()

        for day in list(self._day_separator_widgets.keys()):
            if day not in seen_days:
                separator = self._day_separator_widgets.pop(day)
                self.feed_layout.removeWidget(separator)
                separator.deleteLater()

        if suppress_autoscroll:
            return has_new_from_others
        if at_bottom or not has_new_from_others:
            QTimer.singleShot(0, self._scroll_to_bottom)
        else:
            self._show_new_messages_button()
        return has_new_from_others

    def _scroll_to_bottom(self):
        # A bolha recem-inserida as vezes so ganha a altura final (texto
        # quebrado em varias linhas) um instante DEPOIS deste metodo rodar —
        # o QScrollArea manda o range novo do scrollbar num evento de layout
        # proprio, que pode chegar depois do singleShot(0) que disparou esta
        # chamada. Sem isso, a animacao mirava no maximo antigo e parava
        # alguns pixels antes do fundo de verdade. _catch_up_to_bottom
        # mantem a rolagem "grudada" no fundo por uma janela curta,
        # reagindo a qualquer novo rangeChanged nesse meio tempo.
        self._catch_up_to_bottom = True
        QTimer.singleShot(400, self._stop_catching_up_to_bottom)
        self._animate_scroll_to_current_bottom()

    def _stop_catching_up_to_bottom(self):
        self._catch_up_to_bottom = False

    def _on_scroll_range_changed(self, _minimum, _maximum):
        if self._catch_up_to_bottom:
            self._animate_scroll_to_current_bottom()

    def _animate_scroll_to_current_bottom(self):
        bar = self.scroll.verticalScrollBar()
        target = bar.maximum()
        if bar.value() == target:
            return
        self._scroll_animation = QPropertyAnimation(bar, b"value", self)
        self._scroll_animation.setDuration(280)
        self._scroll_animation.setStartValue(bar.value())
        self._scroll_animation.setEndValue(target)
        self._scroll_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._scroll_animation.start()

    def _answer_question(self, message_id: int):
        text, ok = QInputDialog.getMultiLineText(self, "Responder pergunta", "Resposta:")
        if not ok or not text.strip():
            return
        try:
            answer = self.service.chat_answer_question(message_id, text.strip())
        except Exception as exc:
            ToastNotification(self.window(), str(exc), "error")
            return
        ToastNotification(self.window(), "Resposta enviada.", "success")
        self._append_sent_message(answer)
        self.refresh()

    def _cancel_question(self, message_id: int):
        reason, ok = QInputDialog.getMultiLineText(self, "Cancelar pergunta", "Motivo do cancelamento:")
        if not ok or not reason.strip():
            return
        try:
            self.service.chat_cancel_question(message_id, reason.strip())
        except Exception as exc:
            ToastNotification(self.window(), str(exc), "error")
            return
        ToastNotification(self.window(), "Pergunta cancelada.", "success")
        self.refresh()

    def _reassign_question(self, message_id: int):
        if not self._mentionable_users:
            ToastNotification(self.window(), "Nenhum usuario disponivel para reatribuicao.", "error")
            return
        names = [user.get("display_name") or "-" for user in self._mentionable_users]
        name, ok = QInputDialog.getItem(self, "Reatribuir pergunta", "Novo responsavel:", names, 0, False)
        if not ok or not name:
            return
        new_assignee = next((user for user in self._mentionable_users if (user.get("display_name") or "-") == name), None)
        if new_assignee is None:
            return
        reason, ok = QInputDialog.getMultiLineText(self, "Reatribuir pergunta", "Motivo da troca de responsavel:")
        if not ok or not reason.strip():
            return
        try:
            self.service.chat_reassign_question(message_id, new_assignee["id"], reason.strip())
        except Exception as exc:
            ToastNotification(self.window(), str(exc), "error")
            return
        ToastNotification(self.window(), "Pergunta reatribuida.", "success")
        self.refresh()

    def _open_internal_note_dialog(self):
        if not self.conversation_id:
            ToastNotification(self.window(), "Conversa ainda nao carregada, tente novamente.", "error")
            return
        dialog = InternalNoteDialog(self, mentionable_users=self._mentionable_users)
        if dialog.exec() != QDialog.Accepted:
            return
        body, area, recipient_id, is_important = dialog.result_data()
        if not body:
            return
        try:
            note = self.service.chat_send_message(
                self.conversation_id, body, "NOTA_INTERNA", recipient_id, None, area, None, is_important
            )
        except Exception as exc:
            ToastNotification(self.window(), str(exc), "error")
            return
        ToastNotification(self.window(), "Nota interna registrada.", "success")
        self._append_sent_message(note)
        self.refresh()

    def send_message(self):
        body = self.compose_bar.body()
        attachments = self.compose_bar.pending_attachments()
        if not body and not attachments:
            ToastNotification(self.window(), "Escreva uma mensagem ou adicione um anexo antes de enviar.", "error")
            return
        if not self.conversation_id:
            ToastNotification(self.window(), "Conversa ainda nao carregada, tente novamente.", "error")
            return
        if self._upload_thread is not None and self._upload_thread.isRunning():
            ToastNotification(self.window(), "Aguarde o envio dos anexos em andamento.", "error")
            return
        retry_attachments = [item for item in attachments if item.state in {AttachmentState.FAILED, AttachmentState.CANCELLED}]
        if self._pending_attachment_message_id and retry_attachments:
            self.compose_bar.set_sending(True)
            self._start_attachment_uploads(self._pending_attachment_message_id, retry_attachments)
            return
        message_type = self.compose_bar.message_type()
        if not body and message_type != "MENSAGEM":
            ToastNotification(self.window(), "Perguntas e notas precisam ter texto.", "error")
            return
        mentioned_user_id = self.compose_bar.mentioned_user_id()
        reply_to_message_id = self.compose_bar.reply_to_message_id()
        due_at = self.compose_bar.due_at() if message_type == "PERGUNTA" else None
        message_body = body or "[Anexo]"
        client_message_id = uuid.uuid4().hex
        try:
            sent = self.service.chat_send_message(
                self.conversation_id,
                message_body,
                message_type,
                mentioned_user_id,
                reply_to_message_id,
                None,
                due_at,
                False,
                client_message_id,
            )
        except Exception as exc:
            ToastNotification(self.window(), str(exc), "error")
            return
        self.compose_bar.set_sending(True)
        self._append_sent_message(sent)
        if attachments:
            self._pending_attachment_message_id = int(sent["id"])
            self._start_attachment_uploads(sent["id"], attachments)
        else:
            self._pending_attachment_message_id = None
            self.compose_bar.clear()
            self.refresh()

    def _start_attachment_uploads(self, message_id: int, attachments) -> None:
        for attachment in attachments:
            attachment.state = AttachmentState.UPLOADING
            attachment.progress = 0
            attachment.error = None
            self.compose_bar.attachments_queue.refresh_attachment(attachment.local_id)
        self._upload_thread = QThread(self)
        self._upload_worker = ChatAttachmentUploadWorker(self.service, message_id, attachments)
        self._upload_worker.moveToThread(self._upload_thread)
        self._upload_thread.started.connect(self._upload_worker.run)
        self._upload_worker.progress_changed.connect(self._on_attachment_progress)
        self._upload_worker.upload_succeeded.connect(self._on_attachment_success)
        self._upload_worker.upload_failed.connect(self._on_attachment_failed)
        self._upload_worker.upload_cancelled.connect(self._on_attachment_cancelled)
        self._upload_worker.finished.connect(self._on_attachment_uploads_finished)
        self._upload_worker.finished.connect(self._upload_thread.quit)
        self._upload_worker.finished.connect(self._upload_worker.deleteLater)
        self._upload_thread.finished.connect(self._upload_thread.deleteLater)
        self._upload_thread.start()

    def _find_pending_attachment(self, local_id: str):
        return next((item for item in self.compose_bar.pending_attachments() if item.local_id == local_id), None)

    def _on_attachment_progress(self, local_id: str, progress: int) -> None:
        attachment = self._find_pending_attachment(local_id)
        if attachment is None:
            return
        attachment.state = AttachmentState.UPLOADING
        attachment.progress = progress
        self.compose_bar.attachments_queue.refresh_attachment(local_id)

    def _on_attachment_success(self, local_id: str, result) -> None:
        attachment = self._find_pending_attachment(local_id)
        if attachment is None:
            return
        attachment.state = AttachmentState.SUCCESS
        attachment.progress = 100
        if isinstance(result, dict):
            attachment.remote_attachment_id = result.get("id")
            if attachment.category == "image" and attachment.local_path.exists():
                result = dict(result)
                cache_path = cached_attachment_path(result)
                try:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(attachment.local_path, cache_path)
                    result["_local_cache_path"] = str(cache_path)
                except OSError:
                    result["_local_source_path"] = str(attachment.local_path)
            self._merge_uploaded_attachment(result)
        self.compose_bar.attachments_queue.refresh_attachment(local_id)

    def _merge_uploaded_attachment(self, result: dict) -> None:
        message_id = result.get("message_id") or self._pending_attachment_message_id
        if message_id is None:
            return
        for entry in self.entries:
            if entry.get("source") == "chat" and entry.get("id") == message_id:
                attachments = entry.setdefault("attachments", [])
                if not any(isinstance(item, dict) and item.get("id") == result.get("id") for item in attachments):
                    attachments.append(dict(result))
                self._annotate_entries()
                self._render_entries()
                return

    def _on_attachment_failed(self, local_id: str, message: str) -> None:
        attachment = self._find_pending_attachment(local_id)
        if attachment is None:
            return
        attachment.state = AttachmentState.FAILED
        attachment.error = self._friendly_attachment_error(message)
        self.compose_bar.attachments_queue.refresh_attachment(local_id)

    def _on_attachment_cancelled(self, local_id: str) -> None:
        attachment = self._find_pending_attachment(local_id)
        if attachment is None:
            return
        attachment.state = AttachmentState.CANCELLED
        attachment.error = "Cancelado"
        self.compose_bar.attachments_queue.refresh_attachment(local_id)

    def _cancel_attachment_upload(self, local_id: str) -> None:
        if self._upload_worker is not None:
            self._upload_worker.cancel(local_id)

    def _save_attachment_as(self, attachment: dict) -> None:
        if attachment.get("deleted_at"):
            ToastNotification(self.window(), "Este anexo foi removido.", "error")
            return
        filename = safe_attachment_filename(attachment_filename(attachment))
        destination, _filter = QFileDialog.getSaveFileName(self, "Salvar anexo", filename)
        if not destination:
            return
        self._start_attachment_download(attachment, Path(destination), "save")

    def _open_attachment(self, attachment: dict) -> None:
        if attachment.get("deleted_at"):
            ToastNotification(self.window(), "Este anexo foi removido.", "error")
            return
        destination = cached_attachment_path(attachment)
        if self._attachment_cache.is_valid(attachment, destination):
            self._open_downloaded_attachment(attachment, str(destination))
            return
        self._start_attachment_download(attachment, destination, "open")

    def _preview_attachment(self, attachment: dict) -> None:
        if attachment.get("deleted_at"):
            ToastNotification(self.window(), "Este anexo foi removido.", "error")
            return
        category = attachment_display_category(attachment)
        if category != "image" and resolve_media_kind(attachment) != "video":
            self._open_attachment(attachment)
            return
        self._show_media_viewer(attachment)

    def _delete_attachment(self, attachment: dict) -> None:
        reason, ok = QInputDialog.getText(self, "Remover anexo", "Justificativa:")
        reason = str(reason or "").strip()
        if not ok:
            return
        if len(reason) < 3:
            ToastNotification(self.window(), "Informe uma justificativa com pelo menos 3 caracteres.", "error")
            return
        try:
            deleted = self.service.chat_delete_attachment(int(attachment["id"]), reason)
        except Exception as exc:
            ToastNotification(self.window(), str(exc), "error")
            return
        self.apply_realtime_event(
            "attachment.deleted",
            {"conversation_id": self.conversation_id, "message_id": deleted.get("message_id"), "attachment": deleted},
        )
        ToastNotification(self.window(), "Anexo removido.", "success")

    def _start_attachment_download(self, attachment: dict, destination: Path, mode: str) -> None:
        try:
            attachment_id = int(attachment["id"])
        except (KeyError, TypeError, ValueError):
            ToastNotification(self.window(), "Anexo invalido para download.", "error")
            return
        if attachment_id in self._download_jobs:
            ToastNotification(self.window(), "Este anexo ja esta sendo baixado.", "error")
            return
        thread = QThread(self)
        worker = ChatAttachmentDownloadWorker(self.service, attachment, destination)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.download_succeeded.connect(lambda downloaded, path, current_mode=mode: self._on_attachment_download_success(downloaded, path, current_mode))
        worker.download_failed.connect(self._on_attachment_download_failed)
        worker.download_cancelled.connect(lambda _downloaded: ToastNotification(self.window(), "Download cancelado.", "error"))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda attachment_id=attachment_id: self._download_jobs.pop(attachment_id, None))
        self._download_jobs[attachment_id] = (thread, worker, mode)
        thread.start()
        if mode == "save":
            ToastNotification(self.window(), "Baixando anexo...", "success")
        else:
            ToastNotification(self.window(), "Carregando anexo...", "success")

    def _on_attachment_download_success(self, attachment: dict, path: str, mode: str) -> None:
        self._remember_attachment_cache_path(attachment, path)
        if mode == "save":
            ToastNotification(self.window(), "Anexo salvo.", "success")
            return
        if mode == "preview":
            self._show_media_viewer(attachment)
            return
        self._open_downloaded_attachment(attachment, path)

    def _on_attachment_download_failed(self, attachment: dict, message: str) -> None:
        name = attachment_filename(attachment)
        self._remember_attachment_error(attachment, message)
        ToastNotification(self.window(), f"Nao foi possivel baixar {name}: {message}", "error")

    def _open_downloaded_attachment(self, attachment: dict, path: str) -> None:
        if attachment_display_category(attachment) == "image" or resolve_media_kind(attachment) == "video":
            self._show_media_viewer(attachment)
            return
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        if not opened:
            ToastNotification(self.window(), "Nao foi possivel abrir o arquivo no Windows.", "error")

    def _remember_attachment_cache_path(self, attachment: dict, path: str) -> None:
        attachment_id = attachment.get("id")
        for entry in self.entries:
            for item in entry.get("attachments") or []:
                if isinstance(item, dict) and item.get("id") == attachment_id:
                    item["_local_cache_path"] = path

    def _remember_attachment_error(self, attachment: dict, message: str) -> None:
        attachment_id = attachment.get("id")
        changed = False
        for entry in self.entries:
            for item in entry.get("attachments") or []:
                if isinstance(item, dict) and item.get("id") == attachment_id:
                    item["_download_error"] = message or "Falha ao carregar"
                    changed = True
        if changed:
            self._render_entries(suppress_autoscroll=True)

    def _show_media_viewer(self, attachment: dict) -> None:
        """MediaSequenceProvider (Fase 6): sequencia imagem/video de toda a conversa ja carregada,
        na ordem real das mensagens -- nao apenas os anexos da mensagem clicada. O dialog resolve o
        arquivo local de cada item sob demanda (Fase 5), entao nao precisamos ter baixado nada aqui."""
        current_id = attachment.get("id")
        sequence = build_media_sequence(self.entries)
        start_index = next((index for index, item in enumerate(sequence) if item.get("id") == current_id), None)
        if start_index is None:
            sequence = [dict(attachment)]
            start_index = 0
        MediaViewerDialog(sequence, start_index, service=self.service, has_more_history=self._has_more_older, parent=self).exec()

    def _on_attachment_uploads_finished(self) -> None:
        self._upload_thread = None
        self._upload_worker = None
        failed = [item for item in self.compose_bar.pending_attachments() if item.state in {AttachmentState.FAILED, AttachmentState.CANCELLED}]
        if failed:
            self.compose_bar.set_sending(False)
            ToastNotification(self.window(), "Alguns anexos nao foram enviados. Voce pode remover ou tentar novamente.", "error")
            self.refresh()
            return
        self._pending_attachment_message_id = None
        self.compose_bar.clear()
        ToastNotification(self.window(), "Mensagem enviada.", "success")
        self.refresh()

    @staticmethod
    def _friendly_attachment_error(message: str) -> str:
        text = str(message or "")
        if "CHAT_ATTACHMENT_TOO_LARGE" in text or "tamanho" in text.lower() or "limite" in text.lower():
            return "O arquivo excede o tamanho maximo permitido."
        if "CHAT_ATTACHMENT_TYPE_NOT_ALLOWED" in text or "tipo" in text.lower():
            return "Este tipo de arquivo nao e permitido."
        if "PERMISSION" in text or "permiss" in text.lower():
            return "Voce nao possui permissao para enviar arquivos nesta conversa."
        if "CHAT_ATTACHMENT_STORAGE_ERROR" in text or "storage" in text.lower():
            return "Nao foi possivel salvar o arquivo no servidor."
        if "connect" in text.lower() or "offline" in text.lower():
            return "Nao foi possivel conectar ao servidor."
        if "timeout" in text.lower():
            return "O envio demorou mais do que o esperado."
        return text or "Falha ao enviar anexo."
