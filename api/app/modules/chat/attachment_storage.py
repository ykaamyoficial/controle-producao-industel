from __future__ import annotations

import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path, PurePosixPath

from api.app.core.config import Settings, get_settings


class ChatAttachmentCategory(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    ARCHIVE = "archive"
    CAD = "cad"
    OTHER = "other"


ALLOWED_EXTENSIONS_BY_CATEGORY: dict[ChatAttachmentCategory, set[str]] = {
    ChatAttachmentCategory.IMAGE: {".jpg", ".jpeg", ".png", ".webp"},
    ChatAttachmentCategory.VIDEO: {".mp4", ".mov", ".avi"},
    ChatAttachmentCategory.DOCUMENT: {".pdf", ".doc", ".docx", ".txt"},
    ChatAttachmentCategory.SPREADSHEET: {".xls", ".xlsx", ".csv"},
    ChatAttachmentCategory.ARCHIVE: {".zip", ".7z"},
    ChatAttachmentCategory.CAD: {".dwg", ".dxf"},
    ChatAttachmentCategory.OTHER: set(),
}

BLOCKED_EXECUTABLE_EXTENSIONS = {
    ".exe", ".com", ".bat", ".cmd", ".ps1", ".vbs", ".scr", ".msi", ".dll",
    ".js", ".jar", ".lnk", ".reg", ".hta",
}

MIME_BY_EXTENSION: dict[str, set[str]] = {
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".png": {"image/png"},
    ".webp": {"image/webp"},
    ".mp4": {"video/mp4"},
    ".mov": {"video/quicktime", "video/mp4"},
    ".avi": {"video/x-msvideo", "video/avi", "application/octet-stream"},
    ".pdf": {"application/pdf"},
    ".doc": {"application/msword", "application/octet-stream"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip"},
    ".txt": {"text/plain"},
    ".xls": {"application/vnd.ms-excel", "application/octet-stream"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/zip"},
    ".csv": {"text/csv", "text/plain"},
    ".zip": {"application/zip"},
    ".7z": {"application/x-7z-compressed", "application/octet-stream"},
    ".dwg": {"image/vnd.dwg", "application/acad", "application/octet-stream"},
    ".dxf": {"image/vnd.dxf", "application/dxf", "text/plain", "application/octet-stream"},
}

MAGIC_REQUIRED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".avi", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".7z",
}

_ALL_KNOWN_EXTENSIONS = {
    extension
    for extensions in ALLOWED_EXTENSIONS_BY_CATEGORY.values()
    for extension in extensions
}

_UNSAFE_FILENAME_CHARS = re.compile(r"[\x00-\x1f<>:\"/\\|?*]+")
CHUNK_SIZE = 1024 * 1024


class AttachmentValidationError(ValueError):
    pass


@dataclass(frozen=True)
class AttachmentTypeInfo:
    extension: str
    category: ChatAttachmentCategory
    mime_type: str


def normalize_extension(filename_or_extension: str) -> str:
    value = str(filename_or_extension or "").strip()
    if value.startswith(".") and "/" not in value and "\\" not in value and value.count(".") == 1:
        extension = value
    else:
        extension = Path(value).suffix if "." in value else value
    extension = str(extension or "").strip().lower()
    if not extension:
        return ""
    if not extension.startswith("."):
        extension = f".{extension}"
    return extension[:20]


def classify_extension(extension: str) -> ChatAttachmentCategory:
    normalized = normalize_extension(extension)
    for category, extensions in ALLOWED_EXTENSIONS_BY_CATEGORY.items():
        if normalized in extensions:
            return category
    return ChatAttachmentCategory.OTHER


def is_blocked_extension(extension: str) -> bool:
    return normalize_extension(extension) in BLOCKED_EXECUTABLE_EXTENSIONS


def sanitize_original_filename(original_filename: str) -> str:
    raw_name = str(original_filename or "").replace("\\", "/").split("/")[-1].strip()
    safe_name = _UNSAFE_FILENAME_CHARS.sub("_", raw_name).strip(" .")
    if not safe_name:
        safe_name = "arquivo"
    if len(safe_name) > 255:
        suffix = Path(safe_name).suffix[:20]
        safe_name = safe_name[: 255 - len(suffix)] + suffix
    return safe_name


@dataclass(frozen=True)
class ChatAttachmentLimits:
    max_image_bytes: int
    max_document_bytes: int
    max_video_bytes: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "ChatAttachmentLimits":
        return cls(
            max_image_bytes=settings.chat_max_image_mb * 1024 * 1024,
            max_document_bytes=settings.chat_max_document_mb * 1024 * 1024,
            max_video_bytes=settings.chat_max_video_mb * 1024 * 1024,
        )


class ChatAttachmentStorage:
    def __init__(self, root: str | Path | None = None, *, settings: Settings | None = None):
        settings = settings or get_settings()
        self.root = Path(root or settings.chat_storage_root).expanduser()
        self.limits = ChatAttachmentLimits.from_settings(settings)
        self.min_free_bytes = settings.chat_storage_min_free_mb * 1024 * 1024

    def generate_storage_name(self, original_filename: str) -> str:
        extension = normalize_extension(sanitize_original_filename(original_filename))
        if extension not in _ALL_KNOWN_EXTENSIONS:
            extension = ""
        return f"{uuid.uuid4().hex}{extension}"

    def validate_type(self, original_filename: str, content_type: str | None, first_chunk: bytes) -> AttachmentTypeInfo:
        extension = normalize_extension(sanitize_original_filename(original_filename))
        if is_blocked_extension(extension):
            raise AttachmentValidationError("Tipo de arquivo executavel nao permitido.")
        category = classify_extension(extension)
        if not extension or category == ChatAttachmentCategory.OTHER:
            raise AttachmentValidationError("Tipo de arquivo nao permitido.")
        detected_mime = detect_mime_type(first_chunk, extension, content_type)
        allowed_mimes = MIME_BY_EXTENSION.get(extension, set())
        if allowed_mimes and detected_mime not in allowed_mimes:
            raise AttachmentValidationError("Extensao e conteudo do arquivo nao conferem.")
        return AttachmentTypeInfo(extension=extension, category=category, mime_type=detected_mime)

    def max_bytes_for_category(self, category: ChatAttachmentCategory) -> int:
        if category == ChatAttachmentCategory.IMAGE:
            return self.limits.max_image_bytes
        if category == ChatAttachmentCategory.VIDEO:
            return self.limits.max_video_bytes
        return self.limits.max_document_bytes

    def temp_path(self) -> Path:
        tmp_dir = self.root / "chat" / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return tmp_dir / f"{uuid.uuid4().hex}.tmp"

    def ensure_min_free_space(self) -> None:
        if self.min_free_bytes <= 0:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(self.root).free
        if free < self.min_free_bytes:
            raise OSError("Espaco livre insuficiente no storage de anexos.")

    @staticmethod
    def sha256_file(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def build_relative_path(self, stored_filename: str, *, when: date | datetime | None = None) -> str:
        safe_name = sanitize_original_filename(stored_filename)
        if safe_name != stored_filename or "/" in stored_filename or "\\" in stored_filename:
            raise ValueError("stored_filename deve ser um nome de arquivo simples.")
        current = when or datetime.now().date()
        if isinstance(current, datetime):
            current = current.date()
        return PurePosixPath("chat", f"{current:%Y}", f"{current:%m}", f"{current:%d}", safe_name).as_posix()

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


def detect_mime_type(first_chunk: bytes, extension: str, content_type: str | None = None) -> str:
    header = first_chunk[:512]
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp"
    if header.startswith(b"%PDF-"):
        return "application/pdf"
    if header.startswith(b"PK\x03\x04") or header.startswith(b"PK\x05\x06") or header.startswith(b"PK\x07\x08"):
        if extension == ".docx":
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if extension == ".xlsx":
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return "application/zip"
    if header.startswith(b"7z\xbc\xaf'\x1c"):
        return "application/x-7z-compressed"
    if b"ftyp" in header[:32]:
        return "video/quicktime" if extension == ".mov" else "video/mp4"
    if header.startswith(b"RIFF") and header[8:12] == b"AVI ":
        return "video/x-msvideo"
    if header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "application/msword" if extension == ".doc" else "application/vnd.ms-excel"
    if extension in {".txt", ".csv", ".dxf"} and _looks_textual(header):
        return "text/csv" if extension == ".csv" else "text/plain"
    supplied = (content_type or "").split(";", 1)[0].strip().lower()
    if supplied and extension not in MAGIC_REQUIRED_EXTENSIONS:
        return supplied
    return "application/octet-stream"


def _looks_textual(sample: bytes) -> bool:
    if not sample:
        return True
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


async def write_upload_to_temp(upload_file, storage: ChatAttachmentStorage, type_info: AttachmentTypeInfo, first_chunk: bytes) -> tuple[Path, int, str]:
    temp_path = storage.temp_path()
    digest = sha256()
    total = 0
    max_bytes = storage.max_bytes_for_category(type_info.category)
    try:
        with temp_path.open("wb") as output:
            if first_chunk:
                total += len(first_chunk)
                if total > max_bytes:
                    raise AttachmentValidationError("Arquivo acima do limite permitido.")
                digest.update(first_chunk)
                output.write(first_chunk)
            while True:
                chunk = await upload_file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise AttachmentValidationError("Arquivo acima do limite permitido.")
                digest.update(chunk)
                output.write(chunk)
    except Exception:
        ChatAttachmentStorage.remove_file(temp_path)
        raise
    return temp_path, total, digest.hexdigest()


def content_disposition_attachment(filename: str) -> str:
    safe = sanitize_original_filename(filename)
    ascii_name = safe.encode("ascii", "ignore").decode("ascii") or "arquivo"
    ascii_name = ascii_name.replace("\\", "_").replace("/", "_").replace('"', "_").replace("\r", "_").replace("\n", "_")
    from urllib.parse import quote

    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(safe)}'
