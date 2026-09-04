"""Fase 7 - "Midia e arquivos": area derivada do historico da conversa
(imagens/videos, documentos e links compartilhados), sem duplicar nenhum
anexo/mensagem. Reutiliza integralmente a infraestrutura das Fases 1-6:
MediaViewerDialog (Fase 6) para abrir imagem/video, o fluxo de abrir/baixar
documento ja existente (Fase 5) e o "ir para mensagem" do ChatConversationPanel."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.background_worker import start_worker
from app.ui.components.chat_message_attachments import (
    MediaViewerDialog,
    attachment_local_image_path,
    attachment_local_media_path,
    format_file_size,
    format_viewer_datetime,
    load_oriented_pixmap,
    resolve_file_presentation,
    scaled_cover_pixmap,
)
from app.ui.icons import make_icon


SEARCH_DEBOUNCE_MS = 320
MEDIA_TILE_SIZE = QSize(74, 74)
PAGE_SIZE = 40

FILTERS = (("media", "Midia"), ("document", "Documentos"), ("link", "Links"))


def _shared_item_to_attachment(item: dict) -> dict:
    """Remapeia um SharedContentItem (resposta da API) para o formato de anexo
    que os componentes das Fases 2-6 ja entendem -- sem duplicar dado nenhum,
    so adapta o formato para reuso."""
    kind = item.get("kind")
    category = "video" if kind == "video" else ("image" if kind == "image" else "document")
    return {
        "id": item.get("attachment_id"),
        "message_id": item.get("message_id"),
        "original_filename": item.get("name"),
        "mime_type": item.get("mime_type") or "",
        "category": category,
        "file_size": item.get("size") or 0,
        "sha256": item.get("sha256") or "",
        "created_at": item.get("created_at"),
        "_sender_name": item.get("sender_name"),
        "_message_created_at": item.get("created_at"),
    }


class _FilterButton(QPushButton):
    def __init__(self, text: str, palette: dict, parent=None):
        super().__init__(text, parent)
        self._palette = palette
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("SharedContentFilterButton")
        self._apply_style()
        self.toggled.connect(self._apply_style)

    def _apply_style(self) -> None:
        palette = self._palette
        accent = palette.get("accent", "#0078d4")
        if self.isChecked():
            self.setStyleSheet(
                f"QPushButton#SharedContentFilterButton {{ background: {accent}; color: #ffffff; "
                f"border: none; border-radius: 14px; padding: 4px 14px; font-weight: 700; font-size: 11px; }}"
            )
        else:
            self.setStyleSheet(
                f"QPushButton#SharedContentFilterButton {{ background: {palette.get('surface_alt', '#e2e8f0')}; "
                f"color: {palette.get('muted', '#64748b')}; border: none; border-radius: 14px; padding: 4px 14px; "
                f"font-weight: 600; font-size: 11px; }}"
            )


class _MediaTile(QFrame):
    activated = Signal(int)

    def __init__(self, attachment: dict, index: int, palette: dict, parent=None):
        super().__init__(parent)
        self.attachment = attachment
        self.index = index
        self.setObjectName("SharedMediaTile")
        self.setFixedSize(MEDIA_TILE_SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"QFrame#SharedMediaTile {{ background: {palette.get('surface_alt', '#e2e8f0')}; "
            f"border: 1px solid {palette.get('border', '#cbd5e1')}; border-radius: 8px; }}"
        )
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        thumb = QLabel()
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setStyleSheet("background: transparent;")
        path = attachment_local_media_path(attachment) if attachment.get("category") == "video" else attachment_local_image_path(attachment)
        if path is not None:
            pixmap = load_oriented_pixmap(path)
            if not pixmap.isNull():
                thumb.setPixmap(scaled_cover_pixmap(pixmap, MEDIA_TILE_SIZE))
        else:
            icon_name = "play" if attachment.get("category") == "video" else "image"
            thumb.setPixmap(make_icon(icon_name, palette.get("muted", "#64748b"), 26).pixmap(26, 26))
        grid.addWidget(thumb, 0, 0)
        if attachment.get("category") == "video":
            play_badge = QLabel()
            play_badge.setPixmap(make_icon("play", "#ffffff", 16).pixmap(16, 16))
            play_badge.setStyleSheet("background: rgba(15, 23, 42, 150); border-radius: 10px; padding: 2px;")
            grid.addWidget(play_badge, 0, 0, alignment=Qt.AlignCenter)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.activated.emit(self.index)
            return
        super().mousePressEvent(event)


class _DocumentRow(QFrame):
    open_requested = Signal(dict)
    download_requested = Signal(dict)
    jump_requested = Signal(int)

    def __init__(self, item: dict, palette: dict, parent=None):
        super().__init__(parent)
        self.item = item
        self.attachment = _shared_item_to_attachment(item)
        self.setObjectName("SharedDocumentRow")
        self.setStyleSheet(
            f"QFrame#SharedDocumentRow {{ background: {palette.get('surface', '#ffffff')}; "
            f"border: 1px solid {palette.get('border', '#cbd5e1')}; border-radius: 8px; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(6)

        presentation = resolve_file_presentation(self.attachment)
        icon_label = QLabel()
        icon_label.setFixedSize(24, 24)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setPixmap(make_icon(presentation["icon_key"], palette.get("accent", "#0078d4"), 17).pixmap(17, 17))
        layout.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        name_label = QLabel(presentation["filename"])
        name_label.setStyleSheet("font-weight: 700; font-size: 11px;")
        name_label.setToolTip(presentation["filename"])
        text_col.addWidget(name_label)
        size = item.get("size") or 0
        meta_parts = [presentation["display_type"]]
        if size > 0:
            meta_parts.append(format_file_size(size))
        sender = item.get("sender_name")
        if sender:
            meta_parts.append(sender)
        date_text = format_viewer_datetime(item.get("created_at"))
        if date_text:
            meta_parts.append(date_text)
        meta_label = QLabel(" - ".join(meta_parts))
        meta_label.setStyleSheet(f"font-size: 9px; color: {palette.get('muted', '#64748b')};")
        text_col.addWidget(meta_label)
        layout.addLayout(text_col, 1)

        menu_btn = QToolButton()
        menu_btn.setText("...")
        menu_btn.setFixedSize(20, 20)
        menu_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(menu_btn)
        open_action = menu.addAction("Abrir")
        open_action.triggered.connect(lambda: self.open_requested.emit(self.attachment))
        save_action = menu.addAction("Salvar como...")
        save_action.triggered.connect(lambda: self.download_requested.emit(self.attachment))
        jump_action = menu.addAction("Ir para mensagem")
        jump_action.triggered.connect(lambda: self.jump_requested.emit(item.get("message_id")))
        menu_btn.setMenu(menu)
        layout.addWidget(menu_btn)


class _LinkRow(QFrame):
    jump_requested = Signal(int)

    def __init__(self, item: dict, palette: dict, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("SharedLinkRow")
        self.setStyleSheet(
            f"QFrame#SharedLinkRow {{ background: {palette.get('surface', '#ffffff')}; "
            f"border: 1px solid {palette.get('border', '#cbd5e1')}; border-radius: 8px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(1)

        url = str(item.get("name") or "")
        url_label = QLabel(url)
        url_label.setStyleSheet(f"font-weight: 700; font-size: 11px; color: {palette.get('accent', '#0078d4')};")
        url_label.setWordWrap(True)
        layout.addWidget(url_label)

        meta_parts = []
        sender = item.get("sender_name")
        if sender:
            meta_parts.append(f"Enviado por {sender}")
        date_text = format_viewer_datetime(item.get("created_at"))
        if date_text:
            meta_parts.append(date_text)
        if meta_parts:
            meta_label = QLabel(" - ".join(meta_parts))
            meta_label.setStyleSheet(f"font-size: 9px; color: {palette.get('muted', '#64748b')};")
            layout.addWidget(meta_label)

        snippet = item.get("snippet")
        if snippet:
            snippet_label = QLabel(snippet)
            snippet_label.setWordWrap(True)
            snippet_label.setStyleSheet(f"font-size: 10px; color: {palette.get('text', '#0f172a')};")
            layout.addWidget(snippet_label)

        actions = QHBoxLayout()
        actions.addStretch()
        open_btn = QPushButton("Abrir")
        open_btn.setStyleSheet("font-size: 10px; padding: 2px 8px;")
        open_btn.clicked.connect(lambda: self._open_url(url))
        actions.addWidget(open_btn)
        jump_btn = QPushButton("Ir para mensagem")
        jump_btn.setStyleSheet("font-size: 10px; padding: 2px 8px;")
        jump_btn.clicked.connect(lambda: self.jump_requested.emit(item.get("message_id")))
        actions.addWidget(jump_btn)
        layout.addLayout(actions)

    def _open_url(self, url: str) -> None:
        # So http(s):// -- nunca interpreta o texto da mensagem como comando/local file.
        if url.startswith("http://") or url.startswith("https://"):
            QDesktopServices.openUrl(QUrl(url))


class SharedContentPanel(QFrame):
    """Painel lateral "Midia e arquivos" de uma conversa (Fase 7)."""

    open_attachment_requested = Signal(dict)
    download_attachment_requested = Signal(dict)
    jump_to_message_requested = Signal(int)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.conversation_id: int | None = None
        self._filter = "media"
        self._query = ""
        self._items: list[dict] = []
        self._has_more = False
        self._loading = False
        self._request_thread = None
        self._request_generation = 0
        self.setObjectName("Panel")
        self.setMinimumWidth(0)
        self.setMaximumWidth(0)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(SEARCH_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._reload)
        self._build()

    def set_conversation_id(self, conversation_id: int | None) -> None:
        if conversation_id == self.conversation_id:
            return
        self.conversation_id = conversation_id
        self._items = []
        self._render()

    def _build(self) -> None:
        palette = self.service.palette
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title = QLabel("Midia e arquivos")
        title.setStyleSheet("font-weight: 800; font-size: 13px;")
        layout.addWidget(title)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Pesquisar nesta conversa...")
        self.search_edit.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search_edit)

        filters_row = QHBoxLayout()
        filters_row.setSpacing(6)
        self._filter_buttons: dict[str, _FilterButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key, label in FILTERS:
            btn = _FilterButton(label, palette)
            btn.setChecked(key == self._filter)
            btn.clicked.connect(lambda _checked, key=key: self._on_filter_changed(key))
            filters_row.addWidget(btn)
            group.addButton(btn)
            self._filter_buttons[key] = btn
        filters_row.addStretch()
        layout.addLayout(filters_row)

        self.status_label = QLabel()
        self.status_label.setObjectName("Caption")
        self.status_label.setWordWrap(True)
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.results_host = QWidget()
        self.results_layout = QVBoxLayout(self.results_host)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(6)
        self.scroll.setWidget(self.results_host)
        layout.addWidget(self.scroll, 1)

        self.load_more_btn = QPushButton("Carregar mais")
        self.load_more_btn.clicked.connect(self._load_more)
        self.load_more_btn.setVisible(False)
        layout.addWidget(self.load_more_btn)

    def refresh(self) -> None:
        self._reload()

    def _on_search_changed(self, text: str) -> None:
        self._query = text.strip()
        self._debounce.start()

    def _on_filter_changed(self, key: str) -> None:
        if key == self._filter:
            return
        self._filter = key
        self._reload()

    def _reload(self) -> None:
        self._items = []
        self._has_more = False
        self._fetch(offset=0)

    def _load_more(self) -> None:
        if self._loading:
            return
        self._fetch(offset=len(self._items))

    def _fetch(self, *, offset: int) -> None:
        if self.conversation_id is None:
            self._render()
            return
        self._loading = True
        self._request_generation += 1
        generation = self._request_generation
        conversation_id = self.conversation_id
        filters = {"kind": self._filter, "q": self._query or None, "limit": PAGE_SIZE, "offset": offset}
        self._set_status("Carregando...", visible=not self._items)
        loader = lambda: self.service.chat_shared_content(conversation_id, **filters)
        self._request_thread = start_worker(
            self,
            loader,
            lambda result: self._on_fetch_success(generation, conversation_id, offset, result),
            lambda exc: self._on_fetch_error(generation, exc),
        )

    def _on_fetch_success(self, generation: int, conversation_id: int, offset: int, result: dict) -> None:
        self._loading = False
        # Corrida assincrona: se o usuario trocou de filtro/conversa nesse meio tempo, descarta.
        if generation != self._request_generation or conversation_id != self.conversation_id:
            return
        items = (result or {}).get("items") or []
        if offset == 0:
            self._items = items
        else:
            seen = {(item.get("kind"), item.get("message_id"), item.get("attachment_id")) for item in self._items}
            for item in items:
                key = (item.get("kind"), item.get("message_id"), item.get("attachment_id"))
                if key not in seen:
                    self._items.append(item)
                    seen.add(key)
        self._has_more = bool((result or {}).get("has_more"))
        self._render()

    def _on_fetch_error(self, generation: int, exc) -> None:
        self._loading = False
        if generation != self._request_generation:
            return
        self._set_status("Nao foi possivel carregar os arquivos desta conversa.", visible=True, show_retry=True)

    def _set_status(self, text: str, *, visible: bool, show_retry: bool = False) -> None:
        self.status_label.setText(text)
        self.status_label.setVisible(visible)
        if show_retry:
            self.status_label.setText(text + "  (clique em Carregar mais para tentar novamente)")

    def _render(self) -> None:
        while self.results_layout.count():
            child = self.results_layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()

        self.load_more_btn.setVisible(self._has_more)
        if not self._items:
            if not self._loading:
                self._set_status(self._empty_message(), visible=True)
            return
        self.status_label.setVisible(False)

        if self._filter == "media":
            media_attachments = [_shared_item_to_attachment(item) for item in self._items]
            grid_host = QWidget()
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(4)
            columns = 3
            for index, attachment in enumerate(media_attachments):
                tile = _MediaTile(attachment, index, self.service.palette)
                tile.activated.connect(lambda idx, seq=media_attachments: self._open_media_viewer(seq, idx))
                grid.addWidget(tile, index // columns, index % columns)
            self.results_layout.addWidget(grid_host)
        elif self._filter == "document":
            for item in self._items:
                row = _DocumentRow(item, self.service.palette)
                row.open_requested.connect(self.open_attachment_requested)
                row.download_requested.connect(self.download_attachment_requested)
                row.jump_requested.connect(self._on_jump_requested)
                self.results_layout.addWidget(row)
        else:
            for item in self._items:
                row = _LinkRow(item, self.service.palette)
                row.jump_requested.connect(self._on_jump_requested)
                self.results_layout.addWidget(row)
        self.results_layout.addStretch()

    def _empty_message(self) -> str:
        if self._query:
            return "Nenhum resultado para esta busca."
        return {
            "media": "Nenhuma midia compartilhada nesta conversa.\nAs fotos e videos enviados aqui aparecerao nesta area.",
            "document": "Nenhum documento compartilhado nesta conversa.\nOs documentos enviados aqui aparecerao nesta area.",
            "link": "Nenhum link compartilhado nesta conversa.\nOs links enviados aqui aparecerao nesta area.",
        }[self._filter]

    def _open_media_viewer(self, sequence: list[dict], index: int) -> None:
        if not sequence:
            return
        dialog = MediaViewerDialog(sequence, index, service=self.service, has_more_history=self._has_more, parent=self.window())
        dialog.exec()

    def _on_jump_requested(self, message_id) -> None:
        if message_id is not None:
            self.jump_to_message_requested.emit(int(message_id))

    def notify_new_attachment(self, attachment: dict, *, sender_name: str | None) -> None:
        """Fase 7 - tempo real: insere no topo sem reconstruir a lista, so
        quando o anexo pertence ao filtro ativo e a conversa exibida agora."""
        if attachment.get("message_id") is None:
            return
        category = attachment.get("category")
        kind = "video" if category == "video" else ("image" if category == "image" else "document")
        target_filter = "media" if kind in ("image", "video") else "document"
        if target_filter != self._filter:
            return
        key = (kind, attachment.get("message_id"), attachment.get("id"))
        if any((item.get("kind"), item.get("message_id"), item.get("attachment_id")) == key for item in self._items):
            return
        item = {
            "kind": kind,
            "message_id": attachment.get("message_id"),
            "attachment_id": attachment.get("id"),
            "name": attachment.get("original_filename"),
            "mime_type": attachment.get("mime_type"),
            "size": attachment.get("file_size") or attachment.get("size"),
            "sha256": attachment.get("sha256"),
            "created_at": attachment.get("created_at"),
            "sender_name": sender_name,
        }
        self._items.insert(0, item)
        self._render()
