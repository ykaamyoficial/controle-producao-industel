from __future__ import annotations

from datetime import date, datetime
from pathlib import Path, PurePosixPath

from api.app.core.config import Settings, get_settings
from api.app.modules.chat.attachment_storage import (
    AttachmentTypeInfo,
    AttachmentValidationError,
    ChatAttachmentCategory,
    classify_extension,
    is_blocked_extension,
    normalize_extension,
    sanitize_original_filename,
)
from api.app.modules.chat.attachment_storage import detect_mime_type as _detect_mime_type

NAMESPACE = "proposals"

# Evidencia de acao: foto ou video tirados na hora, nada de documento/executavel.
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov"}
ALLOWED_CATEGORIES = {ChatAttachmentCategory.IMAGE, ChatAttachmentCategory.VIDEO}


class ProposalAttachmentStorage:
    """Espelha ChatAttachmentStorage (api/app/modules/chat/attachment_storage.py)
    restrito a foto/video e gravado sob o namespace 'proposals/' em vez de 'chat/',
    dentro da mesma raiz de storage (CHAT_STORAGE_ROOT)."""

    def __init__(self, root: str | Path | None = None, *, settings: Settings | None = None):
        settings = settings or get_settings()
        self.root = Path(root or settings.chat_storage_root).expanduser()
        self.max_image_bytes = settings.proposal_attachment_max_image_mb * 1024 * 1024
        self.max_video_bytes = settings.proposal_attachment_max_video_mb * 1024 * 1024

    def generate_storage_name(self, original_filename: str) -> str:
        import uuid

        extension = normalize_extension(sanitize_original_filename(original_filename))
        if extension not in ALLOWED_EXTENSIONS:
            extension = ""
        return f"{uuid.uuid4().hex}{extension}"

    def validate_type(self, original_filename: str, content_type: str | None, first_chunk: bytes) -> AttachmentTypeInfo:
        extension = normalize_extension(sanitize_original_filename(original_filename))
        if is_blocked_extension(extension):
            raise AttachmentValidationError("Tipo de arquivo executavel nao permitido.")
        if extension not in ALLOWED_EXTENSIONS:
            raise AttachmentValidationError("Somente foto ou video (jpg, jpeg, png, webp, mp4, mov) sao permitidos.")
        category = classify_extension(extension)
        if category not in ALLOWED_CATEGORIES:
            raise AttachmentValidationError("Somente foto ou video (jpg, jpeg, png, webp, mp4, mov) sao permitidos.")
        detected_mime = _detect_mime_type(first_chunk, extension, content_type)
        if not (detected_mime.startswith("image/") or detected_mime.startswith("video/")):
            raise AttachmentValidationError("Extensao e conteudo do arquivo nao conferem.")
        return AttachmentTypeInfo(extension=extension, category=category, mime_type=detected_mime)

    def max_bytes_for_category(self, category: ChatAttachmentCategory) -> int:
        if category == ChatAttachmentCategory.VIDEO:
            return self.max_video_bytes
        return self.max_image_bytes

    def temp_path(self) -> Path:
        import uuid

        tmp_dir = self.root / NAMESPACE / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return tmp_dir / f"{uuid.uuid4().hex}.tmp"

    def build_relative_path(self, stored_filename: str, *, when: date | datetime | None = None) -> str:
        safe_name = sanitize_original_filename(stored_filename)
        if safe_name != stored_filename or "/" in stored_filename or "\\" in stored_filename:
            raise ValueError("stored_filename deve ser um nome de arquivo simples.")
        current = when or datetime.now().date()
        if isinstance(current, datetime):
            current = current.date()
        return PurePosixPath(NAMESPACE, f"{current:%Y}", f"{current:%m}", f"{current:%d}", safe_name).as_posix()

    def resolve_path(self, relative_path: str) -> Path:
        normalized = self.validate_relative_path(relative_path)
        root = self.root.resolve()
        resolved = (root / Path(*PurePosixPath(normalized).parts)).resolve()
        if root != resolved and root not in resolved.parents:
            raise ValueError("Caminho fora da raiz de storage.")
        return resolved

    def prepare_final_path(self, stored_filename: str, *, when: date | datetime | None = None) -> tuple[str, Path]:
        relative_path = self.build_relative_path(stored_filename, when=when)
        final_path = self.resolve_path(relative_path)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        return relative_path, final_path

    @staticmethod
    def move_temp_to_final(temp_path: Path, final_path: Path) -> None:
        temp_path.replace(final_path)

    @staticmethod
    def remove_file(path: Path | None) -> None:
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def validate_relative_path(relative_path: str) -> str:
        value = str(relative_path or "").replace("\\", "/").strip()
        path = PurePosixPath(value)
        if (
            not value
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or any(":" in part for part in path.parts)
        ):
            raise ValueError("storage_path deve ser relativo e controlado pela aplicacao.")
        return path.as_posix()
