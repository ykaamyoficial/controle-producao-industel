from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget

from app.ui.icons import make_icon


MAX_ATTACHMENTS_PER_MESSAGE = 10
BLOCKED_EXTENSIONS = {".exe", ".com", ".bat", ".cmd", ".ps1", ".vbs", ".scr", ".msi", ".dll", ".js", ".jar", ".lnk", ".reg", ".hta"}
ALLOWED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".avi", ".pdf", ".doc", ".docx", ".txt",
    ".xls", ".xlsx", ".csv", ".zip", ".7z", ".dwg", ".dxf",
}


class AttachmentState(StrEnum):
    PENDING = "pending"
    UPLOADING = "uploading"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class PendingChatAttachment:
    local_id: str
    local_path: Path
    filename: str
    size: int
    extension: str
    category: str
    state: AttachmentState = AttachmentState.PENDING
    progress: int = 0
    error: str | None = None
    remote_attachment_id: int | None = None
    temporary: bool = False

    @classmethod
    def from_path(cls, path: str | Path, *, temporary: bool = False) -> "PendingChatAttachment":
        local_path = Path(path)
        extension = local_path.suffix.lower()
        return cls(
            local_id=uuid.uuid4().hex,
            local_path=local_path,
            filename=local_path.name,
            size=local_path.stat().st_size,
            extension=extension,
            category=attachment_category(extension),
            temporary=temporary,
        )


def attachment_category(extension: str) -> str:
    ext = (extension or "").lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp"}:
        return "image"
    if ext in {".mp4", ".mov", ".avi"}:
        return "video"
    if ext in {".xls", ".xlsx", ".csv"}:
        return "spreadsheet"
    if ext in {".zip", ".7z"}:
        return "archive"
    if ext in {".dwg", ".dxf"}:
        return "cad"
    if ext in {".pdf", ".doc", ".docx", ".txt"}:
        return "document"
    return "other"


def format_file_size(size: int) -> str:
    value = float(max(0, int(size)))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}".replace(".", ",")
        value /= 1024
    return f"{value:.1f} GB".replace(".", ",")


def validate_local_attachment(path: str | Path) -> str | None:
    local_path = Path(path)
    if not local_path.exists() or not local_path.is_file():
        return "Arquivo nao encontrado no computador."
    extension = local_path.suffix.lower()
    if extension in BLOCKED_EXTENSIONS or extension not in ALLOWED_EXTENSIONS:
        return "Este tipo de arquivo nao e permitido."
    return None


def icon_for_category(category: str) -> str:
    return {
        "image": "image",
        "video": "play",
        "spreadsheet": "excel",
        "archive": "backup",
        "cad": "control",
        "document": "pdf",
    }.get(category, "doc")


class PendingAttachmentWidget(QFrame):
    remove_requested = Signal(str)
    retry_requested = Signal(str)
    cancel_requested = Signal(str)

    WIDTH_IMAGE = 96
    WIDTH_OTHER = 176

    def __init__(self, attachment: PendingChatAttachment, palette: dict, parent=None):
        super().__init__(parent)
        self.attachment = attachment
        self.palette = palette
        self.setObjectName("PendingAttachment")
        self.setStyleSheet(
            f"QFrame#PendingAttachment {{ background: {palette.get('surface_alt', '#e2e8f0')}; "
            f"border: 1px solid {palette.get('border', '#cbd5e1')}; border-radius: 6px; }}"
        )
        self.setFixedWidth(self.WIDTH_IMAGE if attachment.category == "image" else self.WIDTH_OTHER)
        self._build()
        self.refresh()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(3)

        self.preview_label = QLabel()
        self.preview_label.setObjectName("PendingAttachmentPreview")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setFixedSize(74, 58)
        self.preview_label.setStyleSheet(
            f"QLabel#PendingAttachmentPreview {{ background: {self.palette.get('surface', '#ffffff')}; "
            f"border: 1px solid {self.palette.get('border', '#cbd5e1')}; border-radius: 8px; }}"
        )

        self.image_remove_btn = QPushButton("x")
        self.image_remove_btn.setObjectName("GhostButton")
        self.image_remove_btn.setFixedSize(22, 22)
        self.image_remove_btn.setToolTip("Remover imagem")
        self.image_remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.attachment.local_id))

        image_row = QHBoxLayout()
        image_row.setSpacing(4)
        image_row.addWidget(self.preview_label)
        image_row.addWidget(self.image_remove_btn, alignment=Qt.AlignTop)
        image_row.addStretch()
        layout.addLayout(image_row)

        row = QHBoxLayout()
        row.setSpacing(7)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(18, 18)
        row.addWidget(self.icon_label)

        self.name_label = QLabel()
        self.name_label.setMinimumWidth(0)
        row.addWidget(self.name_label, 1)

        self.size_label = QLabel()
        self.size_label.setObjectName("Caption")
        row.addWidget(self.size_label)

        self.retry_btn = QPushButton()
        self.retry_btn.setObjectName("GhostButton")
        self.retry_btn.setIcon(make_icon("refresh", self.palette.get("accent", "#0078d4"), 14))
        self.retry_btn.setFixedSize(22, 22)
        self.retry_btn.setToolTip("Tentar novamente")
        self.retry_btn.clicked.connect(lambda: self.retry_requested.emit(self.attachment.local_id))
        row.addWidget(self.retry_btn)

        self.cancel_btn = QPushButton()
        self.cancel_btn.setObjectName("GhostButton")
        self.cancel_btn.setIcon(make_icon("close", self.palette.get("warning", "#d97706"), 14))
        self.cancel_btn.setFixedSize(22, 22)
        self.cancel_btn.setToolTip("Cancelar envio")
        self.cancel_btn.clicked.connect(lambda: self.cancel_requested.emit(self.attachment.local_id))
        row.addWidget(self.cancel_btn)

        self.remove_btn = QPushButton()
        self.remove_btn.setObjectName("GhostButton")
        self.remove_btn.setIcon(make_icon("close", self.palette.get("danger", "#dc2626"), 14))
        self.remove_btn.setFixedSize(22, 22)
        self.remove_btn.setToolTip("Remover anexo")
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.attachment.local_id))
        row.addWidget(self.remove_btn)
        layout.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        layout.addWidget(self.progress)

        self.status_label = QLabel()
        self.status_label.setObjectName("Caption")
        layout.addWidget(self.status_label)

    def refresh(self):
        attachment = self.attachment
        if attachment.category == "image":
            pixmap = QPixmap(str(attachment.local_path))
            if not pixmap.isNull():
                self.preview_label.setPixmap(pixmap.scaled(self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.preview_label.setPixmap(make_icon("image", self.palette.get("accent", "#0078d4"), 22).pixmap(22, 22))
            self.preview_label.setVisible(True)
            self.image_remove_btn.setVisible(attachment.state in {AttachmentState.PENDING, AttachmentState.FAILED, AttachmentState.CANCELLED})
            self.icon_label.setVisible(False)
            self.name_label.setVisible(False)
            self.size_label.setVisible(False)
            self.remove_btn.setVisible(False)
        else:
            self.preview_label.setVisible(False)
            self.image_remove_btn.setVisible(False)
            self.icon_label.setVisible(True)
            self.name_label.setVisible(True)
            self.size_label.setVisible(True)
        self.icon_label.setPixmap(make_icon(icon_for_category(attachment.category), self.palette.get("accent", "#0078d4"), 16).pixmap(16, 16))
        elided = self.name_label.fontMetrics().elidedText(attachment.filename, Qt.ElideMiddle, 70)
        self.name_label.setText(elided)
        self.name_label.setToolTip(str(attachment.local_path))
        self.size_label.setText(format_file_size(attachment.size))
        state_text = {
            AttachmentState.PENDING: "Aguardando",
            AttachmentState.UPLOADING: f"Enviando... {attachment.progress}%",
            AttachmentState.SUCCESS: "Enviado",
            AttachmentState.FAILED: attachment.error or "Falha ao enviar",
            AttachmentState.CANCELLED: "Cancelado",
        }[attachment.state]
        self.status_label.setText(state_text)
        self.status_label.setVisible(attachment.category != "image" or attachment.state in {AttachmentState.FAILED, AttachmentState.CANCELLED})
        self.progress.setValue(max(0, min(100, int(attachment.progress))))
        self.progress.setVisible(attachment.state == AttachmentState.UPLOADING)
        self.retry_btn.setVisible(attachment.state in {AttachmentState.FAILED, AttachmentState.CANCELLED})
        self.cancel_btn.setVisible(attachment.state == AttachmentState.UPLOADING)
        self.remove_btn.setVisible(attachment.category != "image" and attachment.state in {AttachmentState.PENDING, AttachmentState.FAILED, AttachmentState.CANCELLED})


class AttachmentsQueueWidget(QFrame):
    changed = Signal()
    remove_requested = Signal(str)
    retry_requested = Signal(str)
    cancel_requested = Signal(str)

    def __init__(self, palette: dict, parent=None):
        super().__init__(parent)
        self.palette = palette
        self._attachments: list[PendingChatAttachment] = []
        self._widgets: dict[str, PendingAttachmentWidget] = {}
        self.setObjectName("AttachmentsQueue")
        self.setVisible(False)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 4)
        root.setSpacing(4)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("Caption")
        root.addWidget(self.summary_label)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setFixedHeight(150)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.container = QWidget()
        self.layout_ = QHBoxLayout(self.container)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(6)
        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll)

    def set_attachments(self, attachments: list[PendingChatAttachment]):
        self._attachments = attachments
        self.render()

    def render(self):
        while self.layout_.count():
            item = self.layout_.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._widgets.clear()
        for attachment in self._attachments:
            widget = PendingAttachmentWidget(attachment, self.palette)
            widget.remove_requested.connect(self.remove_requested.emit)
            widget.retry_requested.connect(self.retry_requested.emit)
            widget.cancel_requested.connect(self.cancel_requested.emit)
            self._widgets[attachment.local_id] = widget
            self.layout_.addWidget(widget)
        self.layout_.addStretch(1)
        total = sum(item.size for item in self._attachments)
        self.summary_label.setText(f"{len(self._attachments)} arquivo(s) - {format_file_size(total)}")
        self.summary_label.setVisible(not self._attachments or any(item.category != "image" for item in self._attachments))
        self.setVisible(bool(self._attachments))
        self.changed.emit()

    def refresh_attachment(self, local_id: str):
        widget = self._widgets.get(local_id)
        if widget:
            widget.refresh()
            self.changed.emit()
