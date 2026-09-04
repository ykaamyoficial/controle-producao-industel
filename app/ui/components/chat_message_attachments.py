from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImageReader, QKeySequence, QPainter, QPainterPath, QPixmap, QRegion, QShortcut, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

    QT_MULTIMEDIA_AVAILABLE = True
except ImportError:  # pragma: no cover - ambiente sem QtMultimedia
    QAudioOutput = None
    QMediaPlayer = None
    QT_MULTIMEDIA_AVAILABLE = False

try:
    from PySide6.QtMultimediaWidgets import QVideoWidget
except ImportError:  # pragma: no cover - ambiente sem QtMultimediaWidgets
    QVideoWidget = None
    QT_MULTIMEDIA_AVAILABLE = False

from app.ui.chat_attachment_download_worker import AttachmentCacheManager, ChatAttachmentDownloadWorker, cached_attachment_path
from app.ui.components.chat_pending_attachments import attachment_category, format_file_size, icon_for_category
from app.ui.icons import make_icon


IMAGE_PREVIEW_SIZE = QSize(280, 240)
IMAGE_PREVIEW_COMPACT_SIZE = QSize(230, 190)
IMAGE_LOADING_SIZE = QSize(180, 120)
MEDIA_CORNER_RADIUS = 10

# Fase 2 - galeria de imagens
GALLERY_WIDTH = 280
GALLERY_WIDTH_COMPACT = 230
GALLERY_GAP = 3
GALLERY_ROW_HEIGHT = 130
GALLERY_ROW_HEIGHT_COMPACT = 108
GALLERY_RADIUS = 10
GALLERY_MAX_TILES = 4


def load_oriented_pixmap(path) -> QPixmap:
    """Le a imagem aplicando a orientacao EXIF (fotos de celular nao ficam deitadas)."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        return QPixmap(str(path))
    return QPixmap.fromImage(image)


def rounded_pixmap(pixmap: QPixmap, radius: int) -> QPixmap:
    if pixmap.isNull() or radius <= 0:
        return pixmap
    result = QPixmap(pixmap.size())
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, pixmap.width(), pixmap.height(), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return result


def apply_rounded_mask(widget, radius: int) -> None:
    """QSS border-radius nao recorta o conteudo de filhos (pixmap de QLabel,
    saida de video de QVideoWidget) -- so o fundo. Uma mascara real (QRegion)
    no widget garante canto arredondado de verdade para imagem/video."""
    size = widget.size()
    if size.width() <= 0 or size.height() <= 0:
        return
    path = QPainterPath()
    path.addRoundedRect(0, 0, size.width(), size.height(), radius, radius)
    widget.setMask(QRegion(path.toFillPolygon().toPolygon()))


def calculate_preview_size(original_width: int, original_height: int, max_width: int, max_height: int, *, min_width: int = 120) -> QSize:
    width = max(1, int(original_width or 1))
    height = max(1, int(original_height or 1))
    max_width = max(1, int(max_width or 1))
    max_height = max(1, int(max_height or 1))
    scale = min(max_width / width, max_height / height, 1.0)
    target_width = max(1, int(width * scale))
    target_height = max(1, int(height * scale))
    if target_width < min_width and width >= min_width:
        grow = min(min_width / target_width, max_width / target_width, max_height / target_height)
        target_width = max(1, int(target_width * grow))
        target_height = max(1, int(target_height * grow))
    return QSize(target_width, target_height)


def attachment_display_category(attachment: dict) -> str:
    category = str(attachment.get("category") or "").lower()
    if category:
        return category
    filename = attachment.get("original_filename") or attachment.get("filename") or ""
    return attachment_category(Path(filename).suffix.lower())


def attachment_filename(attachment: dict) -> str:
    return str(attachment.get("original_filename") or attachment.get("filename") or "anexo")


def sanitize_display_filename(raw: str | None) -> str:
    """Nome seguro para exibicao: sem componentes de caminho e sem caracteres de controle."""
    if not raw:
        return "Arquivo"
    name = str(raw).replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return name or "Arquivo"


# Fase 3 - documentos e file cards
EXECUTABLE_EXTENSIONS = {".exe", ".msi", ".bat", ".cmd", ".ps1"}

EXTENSION_ICON_KEYS = {
    ".pdf": "pdf",
    ".doc": "doc", ".docx": "doc", ".odt": "doc", ".rtf": "doc",
    ".xls": "excel", ".xlsx": "excel", ".ods": "excel", ".csv": "excel",
    ".ppt": "doc", ".pptx": "doc", ".odp": "doc",
    ".zip": "backup", ".rar": "backup", ".7z": "backup", ".tar": "backup", ".gz": "backup",
    ".txt": "doc", ".log": "doc", ".json": "doc", ".xml": "doc",
    ".dwg": "control", ".dxf": "control",
    ".step": "control", ".stp": "control", ".igs": "control", ".iges": "control", ".ifc": "control",
    ".exe": "doc", ".msi": "doc", ".bat": "doc", ".cmd": "doc", ".ps1": "doc",
}


def attachment_type_label(attachment: dict) -> str:
    category = attachment_display_category(attachment)
    filename = attachment_filename(attachment).lower()
    extension = Path(filename).suffix
    if category == "image":
        return "Imagem"
    if category == "video":
        return "Video"
    if category == "spreadsheet" or extension in {".xls", ".xlsx", ".ods", ".csv"}:
        return "Planilha"
    if category == "archive" or extension in {".zip", ".rar", ".7z", ".tar", ".gz"}:
        return "Arquivo compactado"
    if extension == ".dwg":
        return "DWG"
    if extension == ".dxf":
        return "DXF"
    if category == "cad":
        return "Desenho CAD"
    if extension in {".step", ".stp", ".igs", ".iges", ".ifc"}:
        return "Modelo 3D"
    if extension in EXECUTABLE_EXTENSIONS:
        return "Executavel"
    if extension == ".pdf":
        return "PDF"
    if extension in {".doc", ".docx", ".odt", ".rtf"}:
        return "Word"
    if extension in {".ppt", ".pptx", ".odp"}:
        return "Apresentacao"
    if extension in {".txt", ".log", ".json", ".xml"}:
        return "Texto"
    if category == "document":
        return "Documento"
    return "Arquivo"


def resolve_file_presentation(attachment: dict) -> dict:
    """FileTypeResolver: classifica um anexo para apresentacao (nao decide regra de negocio)."""
    category = attachment_display_category(attachment)
    filename = sanitize_display_filename(attachment_filename(attachment))
    extension = Path(filename).suffix.lower()
    return {
        "category": category,
        "display_type": attachment_type_label(attachment),
        "icon_key": EXTENSION_ICON_KEYS.get(extension) or icon_for_category(category),
        "is_previewable": category in ("image", "video"),
        "is_executable": extension in EXECUTABLE_EXTENSIONS,
        "filename": filename,
    }


def attachment_size(attachment: dict) -> int:
    return int(attachment.get("file_size") if attachment.get("file_size") is not None else attachment.get("size") or 0)


def attachment_local_image_path(attachment: dict) -> Path | None:
    if attachment_display_category(attachment) != "image":
        return None
    candidates = [attachment.get("_local_cache_path"), attachment.get("_local_source_path"), cached_attachment_path(attachment)]
    cache = AttachmentCacheManager()
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if cache.is_valid(attachment, path):
            return path
    return None


# Fase 4 - video e audio
VIDEO_MIME_PREFIX = "video/"
AUDIO_MIME_PREFIX = "audio/"
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".m4v"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".oga"}


def resolve_media_kind(attachment: dict) -> str | None:
    """Classifica video/audio priorizando mime_type (fonte confiavel), com extensao como fallback."""
    mime = str(attachment.get("mime_type") or "").lower()
    if mime.startswith(VIDEO_MIME_PREFIX):
        return "video"
    if mime.startswith(AUDIO_MIME_PREFIX):
        return "audio"
    if attachment_display_category(attachment) == "video":
        return "video"
    extension = Path(attachment_filename(attachment)).suffix.lower()
    if extension in VIDEO_EXTENSIONS:
        return "video"
    if extension in AUDIO_EXTENSIONS:
        return "audio"
    return None


def attachment_local_media_path(attachment: dict) -> Path | None:
    if resolve_media_kind(attachment) is None:
        return None
    candidates = [attachment.get("_local_cache_path"), attachment.get("_local_source_path"), cached_attachment_path(attachment)]
    cache = AttachmentCacheManager()
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if cache.is_valid(attachment, path):
            return path
    return None


def format_media_time(seconds: float) -> str:
    total = max(0, int(seconds or 0))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def attachment_duration_seconds(attachment: dict) -> float | None:
    for key in ("duration_seconds", "duration"):
        value = attachment.get(key)
        if value is None:
            continue
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            continue
        if seconds > 0:
            return seconds
    return None


class MediaPlaybackCoordinator:
    """Coordenador leve: garante um unico player de audio/video ativo por conversa (sem singleton global pesado)."""

    _active = None

    @classmethod
    def notify_playing(cls, widget) -> None:
        previous = cls._active
        if previous is not None and previous is not widget:
            try:
                previous.pause()
            except RuntimeError:
                pass
        cls._active = widget

    @classmethod
    def notify_stopped(cls, widget) -> None:
        if cls._active is widget:
            cls._active = None


# Fase 6 - visualizador de midia
def format_viewer_datetime(value) -> str:
    if not value:
        return ""
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed.strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return str(value)


def build_media_sequence(entries: list[dict]) -> list[dict]:
    """MediaSequenceProvider: sequencia deterministica de imagens/videos visiveis da conversa,
    na ordem real das mensagens e dos anexos dentro delas (nao por nome/tamanho/horario aproximado)."""
    sequence: list[dict] = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        for item in entry.get("attachments") or []:
            if not isinstance(item, dict) or item.get("deleted_at"):
                continue
            kind = resolve_media_kind(item)
            if kind != "video" and attachment_display_category(item) != "image":
                continue
            enriched = dict(item)
            enriched["_sender_name"] = entry.get("author_name")
            enriched["_message_created_at"] = entry.get("created_at")
            sequence.append(enriched)
    return sequence


def scaled_cover_pixmap(pixmap: QPixmap, target: QSize) -> QPixmap:
    if pixmap.isNull() or target.width() <= 0 or target.height() <= 0:
        return pixmap
    scaled = pixmap.scaled(target, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x = max(0, (scaled.width() - target.width()) // 2)
    y = max(0, (scaled.height() - target.height()) // 2)
    return scaled.copy(x, y, target.width(), target.height())


def scaled_contained_pixmap(pixmap: QPixmap, target: QSize) -> QPixmap:
    if pixmap.isNull() or target.width() <= 0 or target.height() <= 0:
        return pixmap
    return pixmap.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)


class MediaViewerDialog(QDialog):
    """Visualizador interno de midia (Fase 6): imagens e videos da conversa, com navegacao,
    zoom/pan, painel de informacoes e download sob demanda reutilizando a infraestrutura da
    Fase 5. `items` sao anexos (imagem/video) na ordem real da conversa (ver build_media_sequence),
    cada um opcionalmente enriquecido com `_sender_name`/`_message_created_at`."""

    ZOOM_MIN = 0.10
    ZOOM_MAX = 5.0
    ZOOM_STEP = 1.25

    def __init__(self, items: list[dict], start_index: int = 0, service=None, has_more_history: bool = False, parent=None):
        super().__init__(parent)
        self.items = items
        self.index = max(0, min(start_index, len(items) - 1)) if items else 0
        self.service = service
        self.has_more_history = has_more_history
        self.zoom = 1.0
        self._pixmap = QPixmap()
        self._current_path = ""
        self._generation = 0
        self._seeking = False
        self._workers: dict[int, tuple[QThread, ChatAttachmentDownloadWorker]] = {}
        self._player = None
        self._audio_output = None
        self._video_widget = None
        self._panning = False
        self._pan_origin = None
        self._pan_scroll_origin = (0, 0)
        self._closed = False
        self.setWindowTitle("Midia")
        self.resize(980, 700)
        self._build()
        self._install_shortcuts()
        self.finished.connect(self._cleanup_resources)
        self._load_current()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        header = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-weight: 700; font-size: 13px;")
        header.addWidget(self.title_label, 1)
        self.counter_label = QLabel()
        self.counter_label.setStyleSheet("font-size: 11px; color: #94a3b8;")
        header.addWidget(self.counter_label)
        self.info_btn = QPushButton("Info")
        self.info_btn.setCheckable(True)
        self.info_btn.clicked.connect(self._toggle_info_panel)
        header.addWidget(self.info_btn)
        self.save_btn = QPushButton("Salvar")
        self.save_btn.clicked.connect(self.save_current)
        header.addWidget(self.save_btn)
        self.copy_btn = QPushButton("Copiar")
        self.copy_btn.clicked.connect(self.copy_current)
        header.addWidget(self.copy_btn)
        self.open_original_btn = QPushButton("Abrir original")
        self.open_original_btn.clicked.connect(self.open_original)
        header.addWidget(self.open_original_btn)
        close_btn = QPushButton("Fechar")
        close_btn.clicked.connect(self.accept)
        header.addWidget(close_btn)
        outer.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(8)
        canvas_col = QVBoxLayout()
        canvas_col.setSpacing(6)

        nav_row = QHBoxLayout()
        self.prev_btn = QPushButton("< Anterior")
        self.prev_btn.clicked.connect(self.previous_media)
        nav_row.addWidget(self.prev_btn)
        nav_row.addStretch()
        self.next_btn = QPushButton("Proxima >")
        self.next_btn.clicked.connect(self.next_media)
        nav_row.addWidget(self.next_btn)
        canvas_col.addLayout(nav_row)

        self._stack = QStackedWidget()
        self._stack.setMinimumHeight(420)
        self._stack.setStyleSheet("background: #111827;")

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { background: #111827; border: none; }")
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background: #111827; color: #e5e7eb;")
        self.scroll.setWidget(self.image_label)
        self.scroll.viewport().installEventFilter(self)
        self._stack.addWidget(self.scroll)

        if QT_MULTIMEDIA_AVAILABLE:
            self._video_widget = QVideoWidget()
            self._video_widget.setStyleSheet("background: #111827;")
            self._stack.addWidget(self._video_widget)

        self._status_page = QWidget()
        self._status_page.setStyleSheet("background: #111827;")
        status_layout = QVBoxLayout(self._status_page)
        status_layout.setAlignment(Qt.AlignCenter)
        self._status_label = QLabel()
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color: #e5e7eb; font-size: 13px;")
        status_layout.addWidget(self._status_label)
        self._retry_btn = QPushButton("Tentar novamente")
        self._retry_btn.clicked.connect(self._retry_current)
        status_layout.addWidget(self._retry_btn, alignment=Qt.AlignCenter)
        self._stack.addWidget(self._status_page)

        canvas_col.addWidget(self._stack, 1)

        self._image_toolbar = QWidget()
        zoom_row = QHBoxLayout(self._image_toolbar)
        zoom_row.setContentsMargins(0, 0, 0, 0)
        for text, handler in (("-", self.zoom_out), ("Ajustar", self.fit_to_window), ("100%", self.actual_size), ("+", self.zoom_in)):
            btn = QPushButton(text)
            btn.clicked.connect(handler)
            zoom_row.addWidget(btn)
        self._zoom_label = QLabel("Ajustar")
        self._zoom_label.setStyleSheet("font-size: 11px; color: #94a3b8;")
        zoom_row.addWidget(self._zoom_label)
        zoom_row.addStretch()
        canvas_col.addWidget(self._image_toolbar)

        self._video_toolbar = QWidget()
        video_row = QHBoxLayout(self._video_toolbar)
        video_row.setContentsMargins(0, 0, 0, 0)
        self._playpause_btn = QToolButton()
        self._playpause_btn.setIcon(make_icon("play", "#e5e7eb", 18))
        self._playpause_btn.setCursor(Qt.PointingHandCursor)
        self._playpause_btn.clicked.connect(self.toggle_play_pause)
        video_row.addWidget(self._playpause_btn)
        self._time_label = QLabel("00:00")
        self._time_label.setStyleSheet("font-size: 10px; color: #94a3b8;")
        video_row.addWidget(self._time_label)
        self._seek_slider = QSlider(Qt.Horizontal)
        self._seek_slider.setRange(0, 0)
        self._seek_slider.sliderMoved.connect(self._on_slider_moved)
        self._seek_slider.sliderPressed.connect(self._on_slider_pressed)
        self._seek_slider.sliderReleased.connect(self._on_slider_released)
        video_row.addWidget(self._seek_slider, 1)
        self._duration_label = QLabel("00:00")
        self._duration_label.setStyleSheet("font-size: 10px; color: #94a3b8;")
        video_row.addWidget(self._duration_label)
        self._mute_btn = QToolButton()
        self._mute_btn.setIcon(make_icon("volume", "#e5e7eb", 16))
        self._mute_btn.setCursor(Qt.PointingHandCursor)
        self._mute_btn.clicked.connect(self.toggle_mute)
        video_row.addWidget(self._mute_btn)
        canvas_col.addWidget(self._video_toolbar)

        self._transfer_bar = TransferProgressBar()
        self._transfer_bar.setVisible(False)
        self._transfer_bar.cancel_requested.connect(self._cancel_current_download)
        canvas_col.addWidget(self._transfer_bar)

        body.addLayout(canvas_col, 1)

        self._info_panel = QWidget()
        self._info_panel.setFixedWidth(220)
        self._info_panel.setVisible(False)
        info_layout = QVBoxLayout(self._info_panel)
        info_layout.setAlignment(Qt.AlignTop)
        self._info_labels: dict[str, QLabel] = {}
        for key, label_text in (("filename", "Nome"), ("type", "Tipo"), ("size", "Tamanho"), ("duration", "Duracao"), ("sender", "Remetente"), ("date", "Data")):
            title = QLabel(label_text)
            title.setStyleSheet("font-size: 10px; font-weight: 700; color: #64748b; margin-top: 6px;")
            info_layout.addWidget(title)
            value = QLabel("-")
            value.setWordWrap(True)
            value.setStyleSheet("font-size: 12px;")
            info_layout.addWidget(value)
            self._info_labels[key] = value
        body.addWidget(self._info_panel)

        outer.addLayout(body, 1)

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.accept)
        QShortcut(QKeySequence("Ctrl++"), self, activated=self.zoom_in)
        QShortcut(QKeySequence("Ctrl+="), self, activated=self.zoom_in)
        QShortcut(QKeySequence("Ctrl+-"), self, activated=self.zoom_out)
        QShortcut(QKeySequence("Ctrl+0"), self, activated=self.fit_to_window)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_current)
        QShortcut(QKeySequence("Ctrl+C"), self, activated=self.copy_current)

    def keyPressEvent(self, event) -> None:
        # Setas nao devem "roubar" o seek do video quando o foco esta explicitamente no slider.
        if event.key() in (Qt.Key_Left, Qt.Key_Right) and QApplication.focusWidget() is self._seek_slider:
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key_Left:
            self.previous_media()
            return
        if event.key() == Qt.Key_Right:
            self.next_media()
            return
        super().keyPressEvent(event)

    # -- navegacao / sequencia -------------------------------------------------

    def previous_media(self) -> None:
        if self.index > 0:
            self.index -= 1
            self._load_current()

    def next_media(self) -> None:
        if self.index < len(self.items) - 1:
            self.index += 1
            self._load_current()

    def current_attachment(self) -> dict | None:
        if not self.items:
            return None
        return self.items[self.index]

    def _update_header(self) -> None:
        attachment = self.current_attachment()
        if attachment is None:
            self.title_label.setText("")
            self.counter_label.setText("")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            return
        sender = attachment.get("_sender_name") or ""
        date = format_viewer_datetime(attachment.get("_message_created_at"))
        title = " - ".join(part for part in (sender, date) if part) or attachment_filename(attachment)
        self.title_label.setText(title)
        if self.has_more_history:
            self.counter_label.setText(f"{self.index + 1}")
        else:
            self.counter_label.setText(f"{self.index + 1} de {len(self.items)}")
        self.prev_btn.setEnabled(self.index > 0)
        self.next_btn.setEnabled(self.index < len(self.items) - 1)

    def _update_info_panel(self, attachment: dict) -> None:
        presentation = resolve_file_presentation(attachment)
        self._info_labels["filename"].setText(presentation["filename"])
        self._info_labels["type"].setText(presentation["display_type"])
        size = attachment_size(attachment)
        self._info_labels["size"].setText(format_file_size(size) if size > 0 else "-")
        duration = attachment_duration_seconds(attachment)
        self._info_labels["duration"].setText(format_media_time(duration) if duration else "-")
        self._info_labels["sender"].setText(attachment.get("_sender_name") or "-")
        self._info_labels["date"].setText(format_viewer_datetime(attachment.get("_message_created_at")) or "-")

    def _toggle_info_panel(self) -> None:
        self._info_panel.setVisible(self.info_btn.isChecked())

    # -- carregamento sob demanda (Fase 5) --------------------------------------

    def _load_current(self) -> None:
        if not self.items:
            self._show_status("Midia indisponivel.")
            return
        self._generation += 1
        generation = self._generation
        attachment = self.current_attachment()
        self._release_video_player()
        self._update_header()
        self._update_info_panel(attachment)
        kind = resolve_media_kind(attachment) or "image"
        self._image_toolbar.setVisible(kind == "image")
        self._video_toolbar.setVisible(kind == "video")
        self.copy_btn.setVisible(kind == "image")
        self._transfer_bar.setVisible(False)
        path = attachment_local_media_path(attachment) if kind == "video" else attachment_local_image_path(attachment)
        if path is not None:
            self._apply_media(attachment, path, kind)
        else:
            self._show_status("Carregando...")
            self._download_item(attachment, generation, apply_on_success=True)
        self._preload_neighbors()

    def _apply_media(self, attachment: dict, path, kind: str) -> None:
        self._current_path = str(path)
        if kind == "video":
            if not QT_MULTIMEDIA_AVAILABLE:
                self._show_status("Reproducao de video nao esta disponivel neste computador.")
                return
            self._stack.setCurrentWidget(self._video_widget)
            self._start_video(path)
        else:
            self._stack.setCurrentWidget(self.scroll)
            self._pixmap = load_oriented_pixmap(path)
            if self._pixmap.isNull():
                self._show_status("Nao foi possivel carregar a imagem.", show_retry=True)
                return
            self.fit_to_window()

    def _show_status(self, text: str, *, show_retry: bool = False) -> None:
        self._stack.setCurrentWidget(self._status_page)
        self._status_label.setText(text)
        self._retry_btn.setVisible(show_retry)

    def _retry_current(self) -> None:
        attachment = self.current_attachment()
        if attachment is not None:
            self._show_status("Carregando...")
            self._download_item(attachment, self._generation, apply_on_success=True)

    def _download_item(self, attachment: dict, generation: int, *, apply_on_success: bool) -> None:
        attachment_id = attachment.get("id")
        if attachment_id is None or attachment_id in self._workers:
            return
        if self.service is None:
            if apply_on_success:
                self._show_status("Nao foi possivel carregar este arquivo.", show_retry=True)
            return
        destination = cached_attachment_path(attachment)
        thread = QThread(self)
        worker = ChatAttachmentDownloadWorker(self.service, attachment, destination)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_changed.connect(lambda sent, total, aid=attachment_id, gen=generation: self._on_item_progress(aid, gen, sent, total))
        worker.download_succeeded.connect(lambda item, path, aid=attachment_id, gen=generation, apply_=apply_on_success: self._on_item_succeeded(aid, gen, path, apply_))
        worker.download_failed.connect(lambda item, message, aid=attachment_id, gen=generation, apply_=apply_on_success: self._on_item_failed(aid, gen, apply_))
        worker.download_cancelled.connect(lambda item, aid=attachment_id: self._workers.pop(aid, None))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda aid=attachment_id: self._workers.pop(aid, None))
        self._workers[attachment_id] = (thread, worker)
        thread.start()

    def _cancel_current_download(self) -> None:
        attachment = self.current_attachment()
        if attachment is None:
            return
        entry = self._workers.get(attachment.get("id"))
        if entry is not None:
            entry[1].cancel()

    def _current_attachment_id(self):
        attachment = self.current_attachment()
        return None if attachment is None else attachment.get("id")

    def _on_item_progress(self, attachment_id, generation: int, sent: int, total: int) -> None:
        try:
            if generation != self._generation or attachment_id != self._current_attachment_id():
                return
            self._transfer_bar.setVisible(True)
            self._transfer_bar.set_progress(sent, total)
        except RuntimeError:
            pass

    def _on_item_succeeded(self, attachment_id, generation: int, path: str, apply_on_success: bool) -> None:
        for item in self.items:
            if item.get("id") == attachment_id:
                item["_local_cache_path"] = path
        if not apply_on_success:
            return
        try:
            if generation != self._generation or attachment_id != self._current_attachment_id():
                return
            attachment = self.current_attachment()
            kind = resolve_media_kind(attachment) or "image"
            self._apply_media(attachment, path, kind)
        except RuntimeError:
            pass

    def _on_item_failed(self, attachment_id, generation: int, apply_on_success: bool) -> None:
        if not apply_on_success:
            return
        try:
            if generation != self._generation or attachment_id != self._current_attachment_id():
                return
            self._show_status("Nao foi possivel carregar a midia.", show_retry=True)
        except RuntimeError:
            pass

    def _preload_neighbors(self) -> None:
        for offset in (-1, 1):
            idx = self.index + offset
            if 0 <= idx < len(self.items):
                item = self.items[idx]
                kind = resolve_media_kind(item) or "image"
                path = attachment_local_media_path(item) if kind == "video" else attachment_local_image_path(item)
                if path is None:
                    self._download_item(item, 0, apply_on_success=False)

    # -- imagem: zoom/pan --------------------------------------------------------

    def _apply_zoom(self) -> None:
        if self._pixmap.isNull():
            return
        size = QSize(max(1, int(self._pixmap.width() * self.zoom)), max(1, int(self._pixmap.height() * self.zoom)))
        scaled = self._pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        self.image_label.resize(scaled.size())
        self._zoom_label.setText(f"{int(round(self.zoom * 100))}%")

    def fit_to_window(self) -> None:
        if self._pixmap.isNull():
            return
        viewport = self.scroll.viewport().size() - QSize(24, 24)
        self.zoom = min(viewport.width() / max(1, self._pixmap.width()), viewport.height() / max(1, self._pixmap.height()), 1.0)
        self.zoom = max(self.ZOOM_MIN, self.zoom)
        self._apply_zoom()
        self._zoom_label.setText("Ajustar")

    def actual_size(self) -> None:
        self.zoom = 1.0
        self._apply_zoom()

    def zoom_in(self) -> None:
        if self._stack.currentWidget() is not self.scroll:
            return
        self.zoom = min(self.ZOOM_MAX, self.zoom * self.ZOOM_STEP)
        self._apply_zoom()

    def zoom_out(self) -> None:
        if self._stack.currentWidget() is not self.scroll:
            return
        self.zoom = max(self.ZOOM_MIN, self.zoom / self.ZOOM_STEP)
        self._apply_zoom()

    def _is_zoomed_beyond_viewport(self) -> bool:
        if self._stack.currentWidget() is not self.scroll or self._pixmap.isNull():
            return False
        pixmap = self.image_label.pixmap()
        if pixmap is None or pixmap.isNull():
            return False
        viewport = self.scroll.viewport().size()
        return pixmap.width() > viewport.width() or pixmap.height() > viewport.height()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.scroll.viewport():
            event_type = event.type()
            if event_type == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton and self._is_zoomed_beyond_viewport():
                self._panning = True
                self._pan_origin = event.position().toPoint() if hasattr(event, "position") else event.pos()
                self._pan_scroll_origin = (self.scroll.horizontalScrollBar().value(), self.scroll.verticalScrollBar().value())
                self.scroll.viewport().setCursor(Qt.ClosedHandCursor)
                return True
            if event_type == QEvent.Type.MouseMove and self._panning:
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                delta = pos - self._pan_origin
                self.scroll.horizontalScrollBar().setValue(self._pan_scroll_origin[0] - delta.x())
                self.scroll.verticalScrollBar().setValue(self._pan_scroll_origin[1] - delta.y())
                return True
            if event_type == QEvent.Type.MouseButtonRelease and self._panning:
                self._panning = False
                self.scroll.viewport().setCursor(Qt.PointingHandCursor if self._is_zoomed_beyond_viewport() else Qt.ArrowCursor)
                return True
        return super().eventFilter(obj, event)

    # -- acoes: salvar/copiar/abrir original --------------------------------------

    def save_current(self) -> None:
        if not self._current_path:
            return
        attachment = self.current_attachment()
        filename = attachment_filename(attachment) if attachment else Path(self._current_path).name
        destination, _filter = QFileDialog.getSaveFileName(self, "Salvar arquivo", filename)
        if not destination:
            return
        try:
            shutil.copyfile(self._current_path, destination)
        except OSError:
            pass

    def copy_current(self) -> None:
        if self._pixmap.isNull():
            return
        app = QApplication.instance()
        if app is not None:
            app.clipboard().setPixmap(self._pixmap)

    def open_original(self) -> None:
        if self._current_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._current_path))

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._stack.currentWidget() is self.scroll and event.modifiers() & Qt.ControlModifier:
            self.zoom_in() if event.angleDelta().y() > 0 else self.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._stack.currentWidget() is self.scroll and event.button() == Qt.LeftButton:
            if abs(self.zoom - 1.0) < 0.02:
                self.fit_to_window()
            else:
                self.actual_size()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # -- video: reutiliza a mesma logica de controle da Fase 4 --------------------

    def _start_video(self, path) -> None:
        if self._player is None:
            self._player = QMediaPlayer(self)
            self._audio_output = QAudioOutput(self)
            self._player.setAudioOutput(self._audio_output)
            self._player.setVideoOutput(self._video_widget)
            self._player.positionChanged.connect(self._on_position_changed)
            self._player.durationChanged.connect(self._on_duration_changed)
            self._player.playbackStateChanged.connect(self._on_playback_state_changed)
            self._player.errorOccurred.connect(self._on_player_error)
        self._seek_slider.setRange(0, 0)
        self._time_label.setText("00:00")
        self._duration_label.setText("00:00")
        self._playpause_btn.setIcon(make_icon("play", "#e5e7eb", 18))
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        # Autoplay proibido (Fase 6): o video abre pausado ate acao explicita do usuario.

    def toggle_play_pause(self) -> None:
        if self._player is None:
            return
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
        else:
            self._player.play()
            MediaPlaybackCoordinator.notify_playing(self)

    def toggle_mute(self) -> None:
        if self._audio_output is None:
            return
        muted = not self._audio_output.isMuted()
        self._audio_output.setMuted(muted)
        self._mute_btn.setIcon(make_icon("mute" if muted else "volume", "#e5e7eb", 16))

    def pause(self) -> None:
        if self._player is not None:
            try:
                self._player.pause()
            except RuntimeError:
                pass

    def _on_position_changed(self, position_ms: int) -> None:
        if not self._seeking:
            self._seek_slider.setValue(position_ms)
        self._time_label.setText(format_media_time(position_ms / 1000))

    def _on_duration_changed(self, duration_ms: int) -> None:
        self._seek_slider.setRange(0, max(0, duration_ms))
        self._duration_label.setText(format_media_time(duration_ms / 1000))

    def _on_slider_pressed(self) -> None:
        self._seeking = True

    def _on_slider_moved(self, value: int) -> None:
        self._time_label.setText(format_media_time(value / 1000))

    def _on_slider_released(self) -> None:
        self._seeking = False
        if self._player is not None:
            self._player.setPosition(self._seek_slider.value())

    def _on_playback_state_changed(self, state) -> None:
        if state == QMediaPlayer.PlayingState:
            self._playpause_btn.setIcon(make_icon("pause", "#e5e7eb", 18))
        else:
            self._playpause_btn.setIcon(make_icon("play", "#e5e7eb", 18))
            MediaPlaybackCoordinator.notify_stopped(self)

    def _on_player_error(self, error, error_string) -> None:
        if int(error) == 0:
            return
        self._show_status("Nao foi possivel reproduzir este video.", show_retry=True)

    def _release_video_player(self) -> None:
        if self._player is not None:
            try:
                self._player.stop()
            except RuntimeError:
                pass

    # -- ciclo de vida ------------------------------------------------------------

    def _cleanup_resources(self, *_args) -> None:
        if self._closed:
            return
        self._closed = True
        self._release_video_player()
        for _attachment_id, (_thread, worker) in list(self._workers.items()):
            worker.cancel()
        MediaPlaybackCoordinator.notify_stopped(self)

    def closeEvent(self, event) -> None:
        self._cleanup_resources()
        super().closeEvent(event)


# Alias retrocompativel -- o nome anterior (Fases 1-2) apontava para um visualizador so-de-imagens;
# MediaViewerDialog generaliza para imagem+video mantendo a mesma API de abertura via dialog.exec().
ChatImageViewerDialog = MediaViewerDialog


class TransferProgressBar(QWidget):
    """Barra de progresso compacta reutilizavel por FileCard/VideoAttachment/AudioAttachment (Fase 5).
    Progresso indeterminado (sem percentual) quando o total de bytes ainda nao e conhecido."""

    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._bar = QProgressBar()
        self._bar.setFixedHeight(6)
        self._bar.setTextVisible(False)
        self._bar.setRange(0, 0)
        layout.addWidget(self._bar, 1)
        self._label = QLabel("")
        self._label.setStyleSheet("font-size: 10px;")
        layout.addWidget(self._label)
        self._cancel_btn = QToolButton()
        self._cancel_btn.setText("×")
        self._cancel_btn.setToolTip("Cancelar")
        self._cancel_btn.setCursor(Qt.PointingHandCursor)
        self._cancel_btn.setFixedSize(18, 18)
        self._cancel_btn.clicked.connect(self.cancel_requested)
        layout.addWidget(self._cancel_btn)

    def set_progress(self, sent: int, total: int) -> None:
        if total > 0:
            percent = max(0, min(100, int(sent * 100 / total)))
            if self._bar.maximum() == 0:
                self._bar.setRange(0, 100)
            self._bar.setValue(percent)
            self._label.setText(f"{percent}%")
        else:
            self._bar.setRange(0, 0)
            self._label.setText("")

    def set_cancel_visible(self, visible: bool) -> None:
        self._cancel_btn.setVisible(visible)


class FileCard(QFrame):
    """Card compacto para documentos/arquivos sem preview de imagem (Fase 3), com download sob
    demanda e progresso real (Fase 5)."""

    download_requested = Signal(dict)
    open_requested = Signal(dict)
    preview_requested = Signal(dict)
    delete_requested = Signal(dict)

    def __init__(self, attachment: dict, palette: dict, service=None, can_delete: bool = False, parent=None):
        super().__init__(parent)
        self.attachment = attachment
        self.palette = palette
        self.service = service
        self.can_delete = can_delete
        self.presentation = resolve_file_presentation(attachment)
        self._full_name = self.presentation["filename"]
        self._name_label: QLabel | None = None
        self._meta_label: QLabel | None = None
        self._transfer_bar: TransferProgressBar | None = None
        self._retry_button: QPushButton | None = None
        self._thread = None
        self._worker = None
        self.setObjectName("FileCard")
        self.setMinimumWidth(190)
        self.setMaximumWidth(300)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setStyleSheet(
            f"QFrame#FileCard {{ background: {palette.get('surface', '#ffffff')}; "
            f"border: 1px solid {palette.get('border', '#cbd5e1')}; border-radius: 8px; }}"
        )
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(f"{self._full_name}, {self.presentation['display_type']}")
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        if self.attachment.get("deleted_at"):
            row = QHBoxLayout()
            icon_label = QLabel()
            icon_label.setPixmap(make_icon("remove", self.palette.get("muted", "#64748b"), 16).pixmap(16, 16))
            row.addWidget(icon_label)
            text = QLabel("Anexo removido")
            text.setStyleSheet(f"font-weight: 700; font-size: 11px; color: {self.palette.get('muted', '#64748b')};")
            row.addWidget(text, 1)
            layout.addLayout(row)
            name = QLabel(self._full_name)
            name.setWordWrap(True)
            name.setStyleSheet(f"font-size: 10px; color: {self.palette.get('muted', '#64748b')};")
            layout.addWidget(name)
            self.setAccessibleDescription("Anexo removido")
            return

        row = QHBoxLayout()
        row.setSpacing(6)
        icon_label = QLabel()
        icon_label.setFixedSize(30, 30)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setPixmap(make_icon(self.presentation["icon_key"], self.palette.get("accent", "#0078d4"), 20).pixmap(20, 20))
        row.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        self._name_label = QLabel(self._full_name)
        self._name_label.setObjectName("FileCardName")
        self._name_label.setWordWrap(False)
        self._name_label.setMinimumWidth(0)
        self._name_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._name_label.setToolTip(self._full_name)
        self._name_label.setStyleSheet("font-weight: 700; font-size: 11px;")
        text_col.addWidget(self._name_label)

        size = attachment_size(self.attachment)
        base_meta = self.presentation["display_type"]
        if size > 0:
            base_meta = f"{base_meta} - {format_file_size(size)}"
        self._base_meta = base_meta
        self._meta_label = QLabel(base_meta)
        self._meta_label.setObjectName("FileCardMeta")
        self._meta_label.setStyleSheet(f"font-size: 9px; color: {self.palette.get('muted', '#64748b')};")
        self.setAccessibleDescription(base_meta)
        text_col.addWidget(self._meta_label)

        self._transfer_bar = TransferProgressBar()
        self._transfer_bar.setVisible(False)
        self._transfer_bar.cancel_requested.connect(self._on_cancel_clicked)
        text_col.addWidget(self._transfer_bar)
        row.addLayout(text_col, 1)
        layout.addLayout(row)

        # Sem botoes visiveis: o card inteiro e clicavel para abrir, e o
        # menu (Salvar como/Ir para mensagem/Copiar nome/Remover) fica
        # disponivel por clique direito (contextMenuEvent). O retry so
        # aparece quando ha erro de fato.
        self.setCursor(Qt.PointingHandCursor)
        actions = QHBoxLayout()
        actions.addStretch()
        self._retry_button = QPushButton("Tentar novamente")
        self._retry_button.setVisible(False)
        self._retry_button.setStyleSheet("font-size: 10px; padding: 2px 8px;")
        self._retry_button.clicked.connect(self._on_open_clicked)
        actions.addWidget(self._retry_button)
        layout.addLayout(actions)

        self._update_elided_name()
        if self.attachment.get("_download_error"):
            self._set_error("Falha ao carregar. Tentar novamente.")

    # -- download sob demanda com progresso real (Fase 5) --------------------

    def _on_open_clicked(self) -> None:
        if self._worker is not None:
            return
        path = attachment_local_media_path(self.attachment) if resolve_media_kind(self.attachment) else None
        if path is None:
            cache = AttachmentCacheManager()
            candidate = cached_attachment_path(self.attachment)
            if cache.is_valid(self.attachment, candidate):
                path = candidate
        if path is not None or self.service is None:
            self.open_requested.emit(self.attachment)
            return
        self._start_download()

    def _start_download(self) -> None:
        self._retry_button.setVisible(False)
        self._meta_label.setVisible(False)
        self._transfer_bar.set_cancel_visible(True)
        self._transfer_bar.set_progress(0, 0)
        self._transfer_bar.setVisible(True)
        destination = cached_attachment_path(self.attachment)
        thread = QThread(self)
        worker = ChatAttachmentDownloadWorker(self.service, self.attachment, destination)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_changed.connect(self._on_progress)
        worker.download_succeeded.connect(self._on_download_succeeded)
        worker.download_failed.connect(self._on_download_failed)
        worker.download_cancelled.connect(self._on_download_cancelled)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_cancel_clicked(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None

    def _on_progress(self, sent: int, total: int) -> None:
        try:
            self._transfer_bar.set_progress(sent, total)
        except RuntimeError:
            pass

    def _on_download_succeeded(self, attachment: dict, path: str) -> None:
        try:
            self.attachment["_local_cache_path"] = path
            self._transfer_bar.setVisible(False)
            self._meta_label.setText(self._base_meta)
            self._meta_label.setVisible(True)
            self.open_requested.emit(self.attachment)
        except RuntimeError:
            pass

    def _on_download_failed(self, attachment: dict, message: str) -> None:
        try:
            self._set_error("Falha ao baixar. Tentar novamente.")
        except RuntimeError:
            pass

    def _on_download_cancelled(self, attachment: dict) -> None:
        try:
            self._transfer_bar.setVisible(False)
            self._meta_label.setText(self._base_meta)
            self._meta_label.setVisible(True)
        except RuntimeError:
            pass

    def _set_error(self, message: str) -> None:
        self._transfer_bar.setVisible(False)
        self._meta_label.setText(message)
        self._meta_label.setVisible(True)
        self._retry_button.setVisible(True)

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def _update_elided_name(self) -> None:
        if self._name_label is None:
            return
        metrics = self._name_label.fontMetrics()
        available = max(40, self.width() - 90)
        elided = metrics.elidedText(self._full_name, Qt.ElideMiddle, available)
        self._name_label.setText(elided)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_elided_name()

    def _build_context_menu(self, parent=None) -> QMenu:
        menu = QMenu(parent or self)
        open_action = menu.addAction("Abrir")
        open_action.triggered.connect(self._on_open_clicked)
        save_action = menu.addAction("Salvar como...")
        save_action.triggered.connect(lambda: self.download_requested.emit(self.attachment))
        copy_action = menu.addAction("Copiar nome")
        copy_action.triggered.connect(lambda: QApplicationClipboard.set_text(self._full_name))
        if self.can_delete:
            menu.addSeparator()
            delete_action = menu.addAction("Remover...")
            delete_action.triggered.connect(lambda: self.delete_requested.emit(self.attachment))
        return menu

    def contextMenuEvent(self, event) -> None:
        self._build_context_menu(self).exec(event.globalPos())

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self._on_open_clicked()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and not self.attachment.get("deleted_at"):
            self._on_open_clicked()
            return
        super().mousePressEvent(event)


class VideoAttachment(QFrame):
    """Preview compacto de video com player inline sob demanda (Fase 4)."""

    download_requested = Signal(dict)
    open_requested = Signal(dict)
    preview_requested = Signal(dict)
    delete_requested = Signal(dict)

    PREVIEW_SIZE = QSize(240, 136)
    COMPACT_SIZE = QSize(200, 114)

    def __init__(self, attachment: dict, palette: dict, service=None, compact: bool = False, can_delete: bool = False, parent=None):
        super().__init__(parent)
        self.attachment = attachment
        self.palette = palette
        self.service = service
        self.compact = compact
        self.can_delete = can_delete
        self._size = self.COMPACT_SIZE if compact else self.PREVIEW_SIZE
        self._state = "preview"
        self._player = None
        self._audio_output = None
        self._video_widget = None
        self._thread = None
        self._worker = None
        self._seeking = False
        self.setObjectName("VideoAttachment")
        self.setStyleSheet("QFrame#VideoAttachment { background: transparent; border: none; }")
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        self._media_box = QFrame()
        self._media_box.setObjectName("VideoMediaBox")
        self._media_box.setFixedSize(self._size)
        self._media_box.setStyleSheet(
            f"QFrame#VideoMediaBox {{ background: {self.palette.get('surface_alt', '#e2e8f0')}; "
            f"border: none; border-radius: {MEDIA_CORNER_RADIUS}px; }}"
        )
        # QSS border-radius nao recorta o video renderizado dentro (QVideoWidget
        # pode desenhar por fora dos cantos) -- a mascara real garante o canto
        # arredondado tanto no poster quanto durante a reproducao.
        apply_rounded_mask(self._media_box, MEDIA_CORNER_RADIUS)
        self._grid = QGridLayout(self._media_box)
        self._grid.setContentsMargins(0, 0, 0, 0)

        self._poster_label = QLabel()
        self._poster_label.setObjectName("VideoPoster")
        self._poster_label.setAlignment(Qt.AlignCenter)
        self._poster_label.setStyleSheet("background: transparent;")
        self._poster_label.setPixmap(make_icon("play", self.palette.get("muted", "#64748b"), 40).pixmap(40, 40))
        self._grid.addWidget(self._poster_label, 0, 0)

        self._play_button = QToolButton()
        self._play_button.setObjectName("VideoPlayButton")
        self._play_button.setIcon(make_icon("play", "#ffffff", 22))
        self._play_button.setIconSize(QSize(22, 22))
        self._play_button.setFixedSize(48, 48)
        self._play_button.setCursor(Qt.PointingHandCursor)
        self._play_button.setStyleSheet(
            "QToolButton#VideoPlayButton { background: rgba(15, 23, 42, 150); border: none; border-radius: 24px; }"
            "QToolButton#VideoPlayButton:hover { background: rgba(15, 23, 42, 200); }"
        )
        self._play_button.clicked.connect(self._on_play_clicked)
        self._grid.addWidget(self._play_button, 0, 0, alignment=Qt.AlignCenter)

        duration_seconds = attachment_duration_seconds(self.attachment)
        self._duration_label = QLabel(format_media_time(duration_seconds) if duration_seconds else "")
        self._duration_label.setObjectName("VideoDurationBadge")
        self._duration_label.setStyleSheet(
            "QLabel#VideoDurationBadge { background: rgba(15, 23, 42, 160); color: #ffffff; font-size: 10px; "
            "padding: 2px 6px; border-radius: 4px; margin: 6px; }"
        )
        self._duration_label.setVisible(bool(duration_seconds))
        self._grid.addWidget(self._duration_label, 0, 0, alignment=Qt.AlignBottom | Qt.AlignRight)

        # Fase 6: abre o MediaViewer (video comeca pausado) sem interferir no play inline.
        self._expand_button = QToolButton()
        self._expand_button.setObjectName("VideoExpandButton")
        self._expand_button.setText("⤢")
        self._expand_button.setToolTip("Abrir no visualizador")
        self._expand_button.setCursor(Qt.PointingHandCursor)
        self._expand_button.setFixedSize(24, 24)
        self._expand_button.setStyleSheet(
            "QToolButton#VideoExpandButton { background: rgba(15, 23, 42, 150); border: none; border-radius: 4px; color: #ffffff; }"
            "QToolButton#VideoExpandButton:hover { background: rgba(15, 23, 42, 200); }"
        )
        self._expand_button.clicked.connect(lambda: self.preview_requested.emit(self.attachment))
        self._grid.addWidget(self._expand_button, 0, 0, alignment=Qt.AlignTop | Qt.AlignRight)

        self._overlay = QWidget()
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(6)
        self._overlay_label = QLabel()
        self._overlay_label.setObjectName("VideoOverlayMessage")
        self._overlay_label.setAlignment(Qt.AlignCenter)
        self._overlay_label.setWordWrap(True)
        self._overlay_label.setStyleSheet(
            "QLabel#VideoOverlayMessage { background: rgba(15, 23, 42, 175); color: #ffffff; font-size: 11px; "
            "padding: 8px 12px; border-radius: 8px; }"
        )
        overlay_layout.addWidget(self._overlay_label)
        self._retry_button = QPushButton("Tentar novamente")
        self._retry_button.clicked.connect(self._on_play_clicked)
        overlay_layout.addWidget(self._retry_button, alignment=Qt.AlignCenter)
        self._overlay.setVisible(False)
        self._grid.addWidget(self._overlay, 0, 0, alignment=Qt.AlignCenter)

        outer.addWidget(self._media_box)

        self._controls = QWidget()
        self._controls.setObjectName("VideoControls")
        controls_layout = QHBoxLayout(self._controls)
        controls_layout.setContentsMargins(2, 0, 2, 0)
        controls_layout.setSpacing(6)
        self._playpause_btn = QToolButton()
        self._playpause_btn.setIcon(make_icon("pause", self.palette.get("text", "#0f172a"), 16))
        self._playpause_btn.setCursor(Qt.PointingHandCursor)
        self._playpause_btn.clicked.connect(self.toggle_play_pause)
        controls_layout.addWidget(self._playpause_btn)
        self._time_label = QLabel("00:00")
        self._time_label.setStyleSheet(f"font-size: 10px; color: {self.palette.get('muted', '#64748b')};")
        controls_layout.addWidget(self._time_label)
        self._seek_slider = QSlider(Qt.Horizontal)
        self._seek_slider.setRange(0, 0)
        self._seek_slider.sliderMoved.connect(self._on_slider_moved)
        self._seek_slider.sliderPressed.connect(self._on_slider_pressed)
        self._seek_slider.sliderReleased.connect(self._on_slider_released)
        controls_layout.addWidget(self._seek_slider, 1)
        self._duration_time_label = QLabel("00:00")
        self._duration_time_label.setStyleSheet(f"font-size: 10px; color: {self.palette.get('muted', '#64748b')};")
        controls_layout.addWidget(self._duration_time_label)
        self._mute_btn = QToolButton()
        self._mute_btn.setIcon(make_icon("volume", self.palette.get("text", "#0f172a"), 16))
        self._mute_btn.setCursor(Qt.PointingHandCursor)
        self._mute_btn.clicked.connect(self.toggle_mute)
        controls_layout.addWidget(self._mute_btn)
        self._controls.setVisible(False)
        outer.addWidget(self._controls)

        if not QT_MULTIMEDIA_AVAILABLE:
            self._set_error("Reproducao de video nao esta disponivel neste computador.")

    # -- ciclo de reproducao -------------------------------------------------

    def _on_play_clicked(self) -> None:
        if not QT_MULTIMEDIA_AVAILABLE:
            return
        if self._player is not None:
            self.toggle_play_pause()
            return
        self._start_playback()

    def _start_playback(self) -> None:
        path = attachment_local_media_path(self.attachment)
        if path is not None:
            self._create_player(path)
            return
        if self._worker is not None:
            return
        self._play_button.setVisible(False)
        self._set_overlay("Carregando...", show_retry=False)
        if self.service is None:
            self._set_error("Nao foi possivel reproduzir este arquivo.")
            return
        destination = cached_attachment_path(self.attachment)
        thread = QThread(self)
        worker = ChatAttachmentDownloadWorker(self.service, self.attachment, destination)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.download_succeeded.connect(self._on_download_succeeded)
        worker.download_failed.connect(self._on_download_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_download_thread_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_download_thread_finished(self) -> None:
        self._thread = None
        self._worker = None

    def _on_download_succeeded(self, attachment: dict, path: str) -> None:
        self.attachment["_local_cache_path"] = path
        try:
            self._create_player(path)
        except RuntimeError:
            pass

    def _on_download_failed(self, attachment: dict, message: str) -> None:
        try:
            self._set_error("Nao foi possivel reproduzir este arquivo.")
        except RuntimeError:
            pass

    def _create_player(self, path) -> None:
        self._poster_label.setVisible(False)
        self._play_button.setVisible(False)
        self._duration_label.setVisible(False)
        self._overlay.setVisible(False)
        if self._video_widget is None:
            self._video_widget = QVideoWidget(self._media_box)
            self._video_widget.setFixedSize(self._size)
            self._grid.addWidget(self._video_widget, 0, 0)
        self._video_widget.setVisible(True)
        if self._player is None:
            self._player = QMediaPlayer(self)
            self._audio_output = QAudioOutput(self)
            self._player.setAudioOutput(self._audio_output)
            self._player.setVideoOutput(self._video_widget)
            self._player.positionChanged.connect(self._on_position_changed)
            self._player.durationChanged.connect(self._on_duration_changed)
            self._player.playbackStateChanged.connect(self._on_playback_state_changed)
            self._player.errorOccurred.connect(self._on_player_error)
            self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._controls.setVisible(True)
        self._player.play()
        MediaPlaybackCoordinator.notify_playing(self)

    def toggle_play_pause(self) -> None:
        if self._player is None:
            self._start_playback()
            return
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
        else:
            self._player.play()
            MediaPlaybackCoordinator.notify_playing(self)

    def toggle_mute(self) -> None:
        if self._audio_output is None:
            return
        muted = not self._audio_output.isMuted()
        self._audio_output.setMuted(muted)
        self._mute_btn.setIcon(make_icon("mute" if muted else "volume", self.palette.get("text", "#0f172a"), 16))

    def pause(self) -> None:
        if self._player is not None:
            try:
                self._player.pause()
            except RuntimeError:
                pass

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        if self._player is not None:
            try:
                self._player.stop()
            except RuntimeError:
                pass
        MediaPlaybackCoordinator.notify_stopped(self)

    def release(self) -> None:
        self.stop()

    # -- eventos do player ----------------------------------------------------

    def _on_position_changed(self, position_ms: int) -> None:
        if not self._seeking:
            self._seek_slider.setValue(position_ms)
        self._time_label.setText(format_media_time(position_ms / 1000))

    def _on_duration_changed(self, duration_ms: int) -> None:
        self._seek_slider.setRange(0, max(0, duration_ms))
        self._duration_time_label.setText(format_media_time(duration_ms / 1000))

    def _on_slider_pressed(self) -> None:
        self._seeking = True

    def _on_slider_moved(self, value: int) -> None:
        self._time_label.setText(format_media_time(value / 1000))

    def _on_slider_released(self) -> None:
        self._seeking = False
        if self._player is not None:
            self._player.setPosition(self._seek_slider.value())

    def _on_playback_state_changed(self, state) -> None:
        if state == QMediaPlayer.PlayingState:
            self._playpause_btn.setIcon(make_icon("pause", self.palette.get("text", "#0f172a"), 16))
        else:
            self._playpause_btn.setIcon(make_icon("play", self.palette.get("text", "#0f172a"), 16))
            MediaPlaybackCoordinator.notify_stopped(self)

    def _on_player_error(self, error, error_string) -> None:
        if int(error) == 0:
            return
        self._set_error(error_string or "Nao foi possivel reproduzir este arquivo.")

    # -- estados visuais -------------------------------------------------------

    def _set_overlay(self, text: str, *, show_retry: bool) -> None:
        self._overlay_label.setText(text)
        self._retry_button.setVisible(show_retry)
        self._overlay.setVisible(True)
        self._play_button.setVisible(False)

    def _set_error(self, message: str) -> None:
        self._controls.setVisible(False)
        if self._video_widget is not None:
            self._video_widget.setVisible(False)
        self._poster_label.setVisible(True)
        self._overlay_label.setToolTip(message)
        self._set_overlay("Nao foi possivel reproduzir\neste arquivo.", show_retry=True)


class AudioAttachment(QFrame):
    """Player compacto de audio inline (Fase 4)."""

    download_requested = Signal(dict)
    open_requested = Signal(dict)
    preview_requested = Signal(dict)
    delete_requested = Signal(dict)

    def __init__(self, attachment: dict, palette: dict, service=None, compact: bool = False, can_delete: bool = False, parent=None):
        super().__init__(parent)
        self.attachment = attachment
        self.palette = palette
        self.service = service
        self.compact = compact
        self.can_delete = can_delete
        self._player = None
        self._audio_output = None
        self._thread = None
        self._worker = None
        self._seeking = False
        self.setObjectName("AudioAttachment")
        self.setMinimumWidth(190)
        self.setMaximumWidth(280)
        self.setStyleSheet(
            f"QFrame#AudioAttachment {{ background: {palette.get('surface', '#ffffff')}; "
            f"border: 1px solid {palette.get('border', '#cbd5e1')}; border-radius: 10px; }}"
        )
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        self._playpause_btn = QToolButton()
        self._playpause_btn.setObjectName("AudioPlayButton")
        self._playpause_btn.setIcon(make_icon("play", self.palette.get("accent", "#0078d4"), 15))
        self._playpause_btn.setFixedSize(26, 26)
        self._playpause_btn.setCursor(Qt.PointingHandCursor)
        self._playpause_btn.setStyleSheet(
            f"QToolButton#AudioPlayButton {{ background: {self.palette.get('surface_alt', '#e2e8f0')}; border: none; border-radius: 16px; }}"
        )
        self._playpause_btn.clicked.connect(self._on_play_clicked)
        layout.addWidget(self._playpause_btn)

        col = QVBoxLayout()
        col.setSpacing(2)
        row = QHBoxLayout()
        row.setSpacing(6)
        self._current_label = QLabel("00:00")
        self._current_label.setStyleSheet(f"font-size: 10px; color: {self.palette.get('muted', '#64748b')};")
        row.addWidget(self._current_label)
        self._seek_slider = QSlider(Qt.Horizontal)
        self._seek_slider.setRange(0, 0)
        self._seek_slider.sliderMoved.connect(self._on_slider_moved)
        self._seek_slider.sliderPressed.connect(self._on_slider_pressed)
        self._seek_slider.sliderReleased.connect(self._on_slider_released)
        row.addWidget(self._seek_slider, 1)
        duration_seconds = attachment_duration_seconds(self.attachment)
        self._duration_label = QLabel(format_media_time(duration_seconds) if duration_seconds else "00:00")
        self._duration_label.setStyleSheet(f"font-size: 10px; color: {self.palette.get('muted', '#64748b')};")
        row.addWidget(self._duration_label)
        col.addLayout(row)

        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(f"font-size: 10px; color: {self.palette.get('muted', '#64748b')};")
        self._status_label.setVisible(False)
        col.addWidget(self._status_label)
        layout.addLayout(col, 1)

        self._retry_button = QPushButton("Tentar novamente")
        self._retry_button.setVisible(False)
        self._retry_button.clicked.connect(self._on_play_clicked)
        layout.addWidget(self._retry_button)

        if not QT_MULTIMEDIA_AVAILABLE:
            self._set_error("Reproducao de audio nao esta disponivel neste computador.")

    # -- ciclo de reproducao -------------------------------------------------

    def _on_play_clicked(self) -> None:
        if not QT_MULTIMEDIA_AVAILABLE:
            return
        if self._player is not None:
            self.toggle_play_pause()
            return
        self._start_playback()

    def _start_playback(self) -> None:
        path = attachment_local_media_path(self.attachment)
        if path is not None:
            self._create_player(path)
            return
        if self._worker is not None:
            return
        self._set_status("Carregando...", show_retry=False)
        if self.service is None:
            self._set_error("Nao foi possivel reproduzir este arquivo.")
            return
        destination = cached_attachment_path(self.attachment)
        thread = QThread(self)
        worker = ChatAttachmentDownloadWorker(self.service, self.attachment, destination)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.download_succeeded.connect(self._on_download_succeeded)
        worker.download_failed.connect(self._on_download_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_download_thread_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_download_thread_finished(self) -> None:
        self._thread = None
        self._worker = None

    def _on_download_succeeded(self, attachment: dict, path: str) -> None:
        self.attachment["_local_cache_path"] = path
        try:
            self._create_player(path)
        except RuntimeError:
            pass

    def _on_download_failed(self, attachment: dict, message: str) -> None:
        try:
            self._set_error("Nao foi possivel reproduzir este arquivo.")
        except RuntimeError:
            pass

    def _create_player(self, path) -> None:
        self._set_status("", show_retry=False)
        self._status_label.setVisible(False)
        if self._player is None:
            self._player = QMediaPlayer(self)
            self._audio_output = QAudioOutput(self)
            self._player.setAudioOutput(self._audio_output)
            self._player.positionChanged.connect(self._on_position_changed)
            self._player.durationChanged.connect(self._on_duration_changed)
            self._player.playbackStateChanged.connect(self._on_playback_state_changed)
            self._player.errorOccurred.connect(self._on_player_error)
            self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()
        MediaPlaybackCoordinator.notify_playing(self)

    def toggle_play_pause(self) -> None:
        if self._player is None:
            self._start_playback()
            return
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
        else:
            self._player.play()
            MediaPlaybackCoordinator.notify_playing(self)

    def pause(self) -> None:
        if self._player is not None:
            try:
                self._player.pause()
            except RuntimeError:
                pass

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        if self._player is not None:
            try:
                self._player.stop()
            except RuntimeError:
                pass
        MediaPlaybackCoordinator.notify_stopped(self)

    def release(self) -> None:
        self.stop()

    # -- eventos do player ----------------------------------------------------

    def _on_position_changed(self, position_ms: int) -> None:
        if not self._seeking:
            self._seek_slider.setValue(position_ms)
        self._current_label.setText(format_media_time(position_ms / 1000))

    def _on_duration_changed(self, duration_ms: int) -> None:
        self._seek_slider.setRange(0, max(0, duration_ms))
        self._duration_label.setText(format_media_time(duration_ms / 1000))

    def _on_slider_pressed(self) -> None:
        self._seeking = True

    def _on_slider_moved(self, value: int) -> None:
        self._current_label.setText(format_media_time(value / 1000))

    def _on_slider_released(self) -> None:
        self._seeking = False
        if self._player is not None:
            self._player.setPosition(self._seek_slider.value())

    def _on_playback_state_changed(self, state) -> None:
        if state == QMediaPlayer.PlayingState:
            self._playpause_btn.setIcon(make_icon("pause", self.palette.get("accent", "#0078d4"), 18))
        else:
            self._playpause_btn.setIcon(make_icon("play", self.palette.get("accent", "#0078d4"), 18))
            MediaPlaybackCoordinator.notify_stopped(self)

    def _on_player_error(self, error, error_string) -> None:
        if int(error) == 0:
            return
        self._set_error(error_string or "Nao foi possivel reproduzir este arquivo.")

    # -- estados visuais -------------------------------------------------------

    def _set_status(self, text: str, *, show_retry: bool) -> None:
        self._status_label.setText(text)
        self._status_label.setVisible(bool(text))
        self._retry_button.setVisible(show_retry)

    def _set_error(self, message: str) -> None:
        self._status_label.setToolTip(message)
        self._set_status("Nao foi possivel reproduzir este arquivo.", show_retry=True)


class ChatAttachmentWidget(QFrame):
    download_requested = Signal(dict)
    open_requested = Signal(dict)
    preview_requested = Signal(dict)
    delete_requested = Signal(dict)

    def __init__(self, attachment: dict, palette: dict, compact: bool = False, can_delete: bool = False, parent=None):
        super().__init__(parent)
        self.attachment = dict(attachment)
        self.palette = palette
        self.compact = compact
        self.can_delete = can_delete
        self.category = attachment_display_category(attachment)
        self.setObjectName("ChatAttachment")
        self.setCursor(Qt.PointingHandCursor if self.category == "image" else Qt.ArrowCursor)
        if self.category == "image":
            self.setStyleSheet("QFrame#ChatAttachment { background: transparent; border: none; }")
        else:
            self.setStyleSheet(
                f"QFrame#ChatAttachment {{ background: {palette.get('surface', '#ffffff')}; "
                f"border: 1px solid {palette.get('border', '#cbd5e1')}; border-radius: 8px; }}"
            )
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0 if self.category == "image" else 10, 0 if self.category == "image" else 8, 0 if self.category == "image" else 10, 0 if self.category == "image" else 8)
        layout.setSpacing(6)
        if self.attachment.get("deleted_at"):
            row = QHBoxLayout()
            icon_label = QLabel()
            icon_label.setPixmap(make_icon("remove", self.palette.get("muted", "#64748b"), 18).pixmap(18, 18))
            row.addWidget(icon_label)
            text = QLabel("Anexo removido")
            text.setStyleSheet(f"font-weight: 700; color: {self.palette.get('muted', '#64748b')};")
            row.addWidget(text, 1)
            layout.addLayout(row)
            name = QLabel(attachment_filename(self.attachment))
            name.setWordWrap(True)
            name.setStyleSheet(f"font-size: 11px; color: {self.palette.get('muted', '#64748b')};")
            layout.addWidget(name)
            return

        if self.category == "image":
            preview = QLabel()
            preview.setObjectName("AttachmentPreview")
            preview.setAlignment(Qt.AlignCenter)
            preview.setContextMenuPolicy(Qt.CustomContextMenu)
            preview.customContextMenuRequested.connect(lambda point, widget=preview: self._show_context_menu(widget.mapToGlobal(point)))
            local_image = attachment_local_image_path(self.attachment)
            if local_image is not None:
                pixmap = load_oriented_pixmap(local_image)
                limits = IMAGE_PREVIEW_COMPACT_SIZE if self.compact else IMAGE_PREVIEW_SIZE
                size = calculate_preview_size(pixmap.width(), pixmap.height(), limits.width(), limits.height())
                preview.setFixedSize(size)
                preview.setPixmap(rounded_pixmap(scaled_contained_pixmap(pixmap, size), MEDIA_CORNER_RADIUS))
            elif self.attachment.get("_download_error"):
                preview.setFixedSize(IMAGE_LOADING_SIZE)
                preview.setText("Nao foi possivel\ncarregar o arquivo")
            else:
                preview.setFixedSize(IMAGE_LOADING_SIZE)
                preview.setText("Carregando...")
                preview.setPixmap(make_icon("image", self.palette.get("accent", "#0078d4"), 24).pixmap(24, 24))
            preview.setStyleSheet(
                f"QLabel#AttachmentPreview {{ background: {self.palette.get('surface_alt', '#e2e8f0')}; "
                f"border: none; border-radius: {MEDIA_CORNER_RADIUS}px; color: {self.palette.get('muted', '#64748b')}; }}"
            )
            preview.mousePressEvent = lambda event: self._handle_image_preview_click(event)
            layout.addWidget(preview)
            return

        if self.category == "video":
            preview = QLabel("Carregar visualizacao" if self.category == "image" else "Video")
            preview.setObjectName("AttachmentPreview")
            preview.setAlignment(Qt.AlignCenter)
            preview.setFixedSize(300 if not self.compact else 240, 170 if not self.compact else 136)
            preview.setPixmap(make_icon("play", self.palette.get("accent", "#0078d4"), 36).pixmap(36, 36))
            preview.setStyleSheet(
                f"QLabel#AttachmentPreview {{ background: {self.palette.get('surface_alt', '#e2e8f0')}; "
                f"border: 1px solid {self.palette.get('border', '#cbd5e1')}; border-radius: 8px; color: {self.palette.get('muted', '#64748b')}; }}"
            )
            preview.mousePressEvent = lambda _event: self.preview_requested.emit(self.attachment)
            layout.addWidget(preview)

        row = QHBoxLayout()
        row.setSpacing(8)
        icon_label = QLabel()
        icon_label.setFixedSize(40, 40)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setPixmap(make_icon(icon_for_category(self.category), self.palette.get("accent", "#0078d4"), 26).pixmap(26, 26))
        row.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        name_label = QLabel(attachment_filename(self.attachment))
        name_label.setWordWrap(False)
        name_label.setMinimumWidth(0)
        name_label.setToolTip(attachment_filename(self.attachment))
        name_label.setStyleSheet("font-weight: 700; font-size: 12px;")
        text_col.addWidget(name_label)
        size = attachment_size(self.attachment)
        meta = attachment_type_label(self.attachment)
        if size > 0:
            meta = f"{meta} - {format_file_size(size)}"
        meta_label = QLabel(meta)
        meta_label.setStyleSheet(f"font-size: 10px; color: {self.palette.get('muted', '#64748b')};")
        text_col.addWidget(meta_label)
        row.addLayout(text_col, 1)

        self.menu_btn = QToolButton()
        self.menu_btn.setText("⋮")
        self.menu_btn.setFixedSize(24, 24)
        self.menu_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.menu_btn)
        open_text = "Abrir imagem" if self.category == "image" else ("Reproduzir" if self.category == "video" else "Abrir")
        open_action = menu.addAction(open_text)
        open_action.triggered.connect(lambda: self.open_requested.emit(self.attachment))
        save_action = menu.addAction("Salvar como...")
        save_action.triggered.connect(lambda: self.download_requested.emit(self.attachment))
        if self.category == "image" and QApplicationClipboard.can_copy_image(self.attachment):
            copy_image_action = menu.addAction("Copiar imagem")
            copy_image_action.triggered.connect(lambda: QApplicationClipboard.set_image_from_attachment(self.attachment))
        copy_action = menu.addAction("Copiar nome")
        copy_action.triggered.connect(lambda: QApplicationClipboard.set_text(attachment_filename(self.attachment)))
        if self.can_delete:
            menu.addSeparator()
            delete_action = menu.addAction("Remover...")
            delete_action.triggered.connect(lambda: self.delete_requested.emit(self.attachment))
        self.menu_btn.setMenu(menu)
        row.addWidget(self.menu_btn)
        layout.addLayout(row)

        actions = QHBoxLayout()
        actions.addStretch()
        open_btn = QPushButton(open_text)
        open_btn.clicked.connect(lambda: self.open_requested.emit(self.attachment))
        actions.addWidget(open_btn)
        layout.addLayout(actions)

    def _build_context_menu(self, parent=None) -> QMenu:
        menu = QMenu(parent or self)
        open_text = "Abrir imagem" if self.category == "image" else ("Reproduzir" if self.category == "video" else "Abrir")
        open_action = menu.addAction(open_text)
        open_action.triggered.connect(lambda: self.open_requested.emit(self.attachment))
        save_action = menu.addAction("Salvar como...")
        save_action.triggered.connect(lambda: self.download_requested.emit(self.attachment))
        if self.category == "image" and QApplicationClipboard.can_copy_image(self.attachment):
            copy_image_action = menu.addAction("Copiar imagem")
            copy_image_action.triggered.connect(lambda: QApplicationClipboard.set_image_from_attachment(self.attachment))
        copy_action = menu.addAction("Copiar nome")
        copy_action.triggered.connect(lambda: QApplicationClipboard.set_text(attachment_filename(self.attachment)))
        if self.can_delete:
            menu.addSeparator()
            delete_action = menu.addAction("Remover...")
            delete_action.triggered.connect(lambda: self.delete_requested.emit(self.attachment))
        return menu

    def _show_context_menu(self, global_pos) -> None:
        self._build_context_menu(self).exec(global_pos)

    def _handle_image_preview_click(self, event) -> None:
        if event.button() == Qt.RightButton:
            self._show_context_menu(event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos())
            return
        if event.button() == Qt.LeftButton:
            self.preview_requested.emit(self.attachment)
            return
        super().mousePressEvent(event)

    def mousePressEvent(self, event) -> None:
        if self.category == "image" and event.button() == Qt.LeftButton:
            self.preview_requested.emit(self.attachment)
            return
        super().mousePressEvent(event)


class QApplicationClipboard:
    @staticmethod
    def set_text(text: str) -> None:
        app = QApplication.instance()
        if app is not None:
            app.clipboard().setText(text)

    @staticmethod
    def can_copy_image(attachment: dict) -> bool:
        return attachment_local_image_path(attachment) is not None

    @staticmethod
    def set_image_from_attachment(attachment: dict) -> bool:
        path = attachment_local_image_path(attachment)
        if path is None:
            return False
        pixmap = load_oriented_pixmap(path)
        app = QApplication.instance()
        if app is None or pixmap.isNull():
            return False
        app.clipboard().setPixmap(pixmap)
        return True


class ImageTile(QFrame):
    """Um tile individual dentro de uma ImageGallery: thumbnail, loading, erro ou overlay +N."""

    activated = Signal(dict)
    context_menu_requested = Signal(dict, object)

    def __init__(self, attachment: dict, size: QSize, *, extra_count: int = 0, radius: int = GALLERY_RADIUS, parent=None):
        super().__init__(parent)
        self.attachment = attachment
        self.extra_count = extra_count
        self.radius = radius
        self.setObjectName("AttachmentImageTile")
        self.setFixedSize(size)
        self.setCursor(Qt.PointingHandCursor)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setStyleSheet(
            f"QFrame#AttachmentImageTile {{ background: #e2e8f0; border: none; border-radius: {radius}px; }}"
        )
        self._image_label = QLabel(self)
        self._image_label.setGeometry(0, 0, size.width(), size.height())
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setStyleSheet("background: transparent; color: #64748b; font-size: 11px;")
        self.customContextMenuRequested.connect(
            lambda point: self.context_menu_requested.emit(self.attachment, self.mapToGlobal(point))
        )
        self.refresh()

    def refresh(self) -> None:
        size = self.size()
        if self.attachment.get("deleted_at"):
            self._image_label.setPixmap(QPixmap())
            self._image_label.setText("Anexo removido")
            return
        path = attachment_local_image_path(self.attachment)
        if path is not None:
            pixmap = load_oriented_pixmap(path)
            if not pixmap.isNull():
                covered = scaled_cover_pixmap(pixmap, size)
                if self.extra_count:
                    covered = self._with_overflow_overlay(covered)
                self._image_label.setPixmap(rounded_pixmap(covered, self.radius))
                self._image_label.setText("")
                return
        if self.attachment.get("_download_error"):
            self._image_label.setPixmap(QPixmap())
            self._image_label.setText("!\nFalha ao\ncarregar")
            return
        self._image_label.setPixmap(QPixmap())
        self._image_label.setText("Carregando...")

    def _with_overflow_overlay(self, pixmap: QPixmap) -> QPixmap:
        from PySide6.QtGui import QColor

        result = QPixmap(pixmap)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(result.rect(), QColor(15, 23, 42, 130))
        painter.setPen(Qt.white)
        font = painter.font()
        font.setPointSize(16)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(result.rect(), Qt.AlignCenter, f"+{self.extra_count}")
        painter.end()
        return result

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.RightButton:
            self.context_menu_requested.emit(
                self.attachment,
                event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos(),
            )
            return
        if event.button() == Qt.LeftButton:
            self.activated.emit(self.attachment)
            return
        super().mousePressEvent(event)


class ImageGallery(QWidget):
    """Composicao de miniaturas de uma mesma mensagem: 2 colunas, 3 compacta, grade 2x2 ou grade + N."""

    tile_activated = Signal(dict)
    tile_context_menu_requested = Signal(dict, object)

    def __init__(self, attachments: list[dict], *, compact: bool = False, parent=None):
        super().__init__(parent)
        self.attachments = attachments
        self.compact = compact
        self.setObjectName("ImageGallery")
        self.setStyleSheet("QWidget#ImageGallery { background: transparent; border: none; }")
        self._tiles: list[ImageTile] = []
        self._build()

    def _gallery_width(self) -> int:
        return GALLERY_WIDTH_COMPACT if self.compact else GALLERY_WIDTH

    def _row_height(self) -> int:
        return GALLERY_ROW_HEIGHT_COMPACT if self.compact else GALLERY_ROW_HEIGHT

    def _make_tile(self, attachment: dict, size: QSize, *, extra_count: int = 0) -> ImageTile:
        tile = ImageTile(attachment, size, extra_count=extra_count)
        tile.activated.connect(self.tile_activated)
        tile.context_menu_requested.connect(self.tile_context_menu_requested)
        self._tiles.append(tile)
        return tile

    def _build(self) -> None:
        count = len(self.attachments)
        width = self._gallery_width()
        row_height = self._row_height()
        gap = GALLERY_GAP

        if count == 2:
            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(gap)
            tile_width = (width - gap) // 2
            size = QSize(tile_width, row_height)
            for attachment in self.attachments:
                layout.addWidget(self._make_tile(attachment, size))
            return

        if count == 3:
            layout = QHBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(gap)
            main_width = int(width * 0.58)
            side_width = width - main_width - gap
            main_size = QSize(main_width, row_height)
            layout.addWidget(self._make_tile(self.attachments[0], main_size))

            side_col = QVBoxLayout()
            side_col.setContentsMargins(0, 0, 0, 0)
            side_col.setSpacing(gap)
            side_height = (row_height - gap) // 2
            side_size = QSize(side_width, side_height)
            side_col.addWidget(self._make_tile(self.attachments[1], side_size))
            side_col.addWidget(self._make_tile(self.attachments[2], side_size))
            layout.addLayout(side_col)
            return

        # 4 ou mais: grade 2x2, sobrando +N no ultimo tile visivel
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(gap)
        visible = self.attachments[:GALLERY_MAX_TILES]
        tile_width = (width - gap) // 2
        tile_height = (row_height - gap) // 2
        size = QSize(tile_width, tile_height)
        overflow = max(0, count - GALLERY_MAX_TILES)
        for index, attachment in enumerate(visible):
            extra = overflow if index == GALLERY_MAX_TILES - 1 else 0
            tile = self._make_tile(attachment, size, extra_count=extra)
            grid.addWidget(tile, index // 2, index % 2)

    def refresh(self) -> None:
        for tile in self._tiles:
            tile.refresh()


class AttachmentContainer(QWidget):
    download_requested = Signal(dict)
    open_requested = Signal(dict)
    preview_requested = Signal(dict)
    delete_requested = Signal(dict)

    def __init__(self, attachments: list[dict], palette: dict, compact: bool = False, can_delete=None, service=None, parent=None):
        super().__init__(parent)
        self.attachments = [dict(item) for item in attachments if isinstance(item, dict)]
        self.palette = palette
        self.compact = compact
        self.can_delete = can_delete
        self.service = service
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        image_attachments = [item for item in self.attachments if attachment_display_category(item) == "image" and not item.get("deleted_at")]
        image_ids = {id(item) for item in image_attachments}
        if image_attachments:
            if len(image_attachments) == 1:
                widget = self._build_single_image(image_attachments[0])
                layout.addWidget(widget)
            else:
                layout.addWidget(self._build_image_gallery(image_attachments))
        for attachment in self.attachments:
            if id(attachment) in image_ids:
                continue
            can_delete = bool(self.can_delete(attachment)) if callable(self.can_delete) else False
            media_kind = resolve_media_kind(attachment) if not attachment.get("deleted_at") else None
            if media_kind == "video":
                widget = VideoAttachment(attachment, self.palette, service=self.service, compact=self.compact, can_delete=can_delete)
            elif media_kind == "audio":
                widget = AudioAttachment(attachment, self.palette, service=self.service, compact=self.compact, can_delete=can_delete)
            else:
                widget = FileCard(attachment, self.palette, service=self.service, can_delete=can_delete)
            widget.download_requested.connect(self.download_requested)
            widget.open_requested.connect(self.open_requested)
            widget.preview_requested.connect(self.preview_requested)
            widget.delete_requested.connect(self.delete_requested)
            layout.addWidget(widget)

    def stop_media(self) -> None:
        """Pausa/libera video, audio em reproducao e cancela downloads em andamento (Fase 4/5) --
        troca de conversa, fechamento da janela, remocao do viewport, etc."""
        widgets = list(self.findChildren(VideoAttachment)) + list(self.findChildren(AudioAttachment)) + list(self.findChildren(FileCard))
        for widget in widgets:
            try:
                widget.stop()
            except RuntimeError:
                pass

    def _build_single_image(self, attachment: dict) -> ChatAttachmentWidget:
        can_delete = bool(self.can_delete(attachment)) if callable(self.can_delete) else False
        widget = ChatAttachmentWidget(attachment, self.palette, self.compact, can_delete=can_delete)
        widget.download_requested.connect(self.download_requested)
        widget.open_requested.connect(self.open_requested)
        widget.preview_requested.connect(self.preview_requested)
        widget.delete_requested.connect(self.delete_requested)
        return widget

    def _build_image_gallery(self, attachments: list[dict]) -> QWidget:
        gallery = ImageGallery(attachments, compact=self.compact)
        gallery.tile_activated.connect(self.preview_requested)
        gallery.tile_context_menu_requested.connect(self._show_tile_menu)
        return gallery

    def _show_tile_menu(self, attachment: dict, global_pos) -> None:
        can_delete = bool(self.can_delete(attachment)) if callable(self.can_delete) else False
        widget = ChatAttachmentWidget(attachment, self.palette, self.compact, can_delete=can_delete)
        widget.download_requested.connect(self.download_requested)
        widget.open_requested.connect(self.open_requested)
        widget.preview_requested.connect(self.preview_requested)
        widget.delete_requested.connect(self.delete_requested)
        widget._show_context_menu(global_pos)
        widget.deleteLater()

    def image_cache_items(self) -> list[tuple[dict, str]]:
        items: list[tuple[dict, str]] = []
        cache = AttachmentCacheManager()
        for attachment in self.attachments:
            if attachment_display_category(attachment) != "image":
                continue
            path = attachment_local_image_path(attachment)
            if path is not None and cache.is_valid(attachment, path):
                items.append((attachment, str(path)))
        return items


class ChatAttachmentsView(AttachmentContainer):
    pass
