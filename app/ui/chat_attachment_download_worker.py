from __future__ import annotations

import os
import re
import hashlib
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal


CHAT_ATTACHMENT_CACHE_MB = int(os.getenv("CHAT_ATTACHMENT_CACHE_MB", "500") or "500")


def safe_attachment_filename(filename: str | None, fallback: str = "anexo") -> str:
    name = Path(filename or fallback).name.strip() or fallback
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)


def chat_attachment_cache_dir() -> Path:
    root = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or str(Path.home())
    path = Path(root) / "ControleProducaoIndustel" / "cache" / "chat" / "attachments"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cached_attachment_path(attachment: dict, *, suffix: str | None = None) -> Path:
    attachment_id = attachment.get("id") or attachment.get("attachment_id") or "sem-id"
    digest = str(attachment.get("sha256") or attachment.get("sha256_hex") or "")[:12] or "sem-hash"
    filename = safe_attachment_filename(attachment.get("original_filename") or attachment.get("filename"))
    if suffix:
        stem = Path(filename).stem or "anexo"
        filename = f"{stem}{suffix}"
    return chat_attachment_cache_dir() / f"{attachment_id}_{digest}_{filename}"


def prune_attachment_cache(limit_mb: int = CHAT_ATTACHMENT_CACHE_MB) -> None:
    limit_bytes = max(1, int(limit_mb)) * 1024 * 1024
    files = [path for path in chat_attachment_cache_dir().iterdir() if path.is_file() and not path.name.endswith(".part")]
    total = sum(path.stat().st_size for path in files if path.exists())
    if total <= limit_bytes:
        return
    for path in sorted(files, key=lambda item: item.stat().st_atime if item.exists() else 0):
        if total <= limit_bytes:
            break
        try:
            size = path.stat().st_size
            path.unlink()
            total -= size
        except OSError:
            continue


class AttachmentCacheManager:
    def __init__(self, limit_mb: int = CHAT_ATTACHMENT_CACHE_MB):
        self.limit_mb = limit_mb

    def path_for(self, attachment: dict) -> Path:
        return cached_attachment_path(attachment)

    def is_valid(self, attachment: dict, path: str | Path | None = None) -> bool:
        candidate = Path(path) if path is not None else self.path_for(attachment)
        if not candidate.exists() or not candidate.is_file():
            return False
        expected = str(attachment.get("sha256") or attachment.get("sha256_hex") or "")
        if not expected:
            os.utime(candidate, None)
            return True
        try:
            hasher = hashlib.sha256()
            with candidate.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(chunk)
            digest = hasher.hexdigest()
        except OSError:
            return False
        if digest != expected:
            try:
                candidate.unlink()
            except OSError:
                pass
            return False
        os.utime(candidate, None)
        return True

    def prune(self) -> None:
        prune_attachment_cache(self.limit_mb)


class ChatAttachmentDownloadWorker(QObject):
    progress_changed = Signal(int, int)
    download_succeeded = Signal(dict, str)
    download_failed = Signal(dict, str)
    download_cancelled = Signal(dict)
    finished = Signal()

    def __init__(self, service, attachment: dict, destination: str | Path):
        super().__init__()
        self.service = service
        self.attachment = dict(attachment)
        self.destination = Path(destination)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        part_path = self.destination.with_name(self.destination.name + ".part")
        try:
            self.destination.parent.mkdir(parents=True, exist_ok=True)
            cache = AttachmentCacheManager()
            if cache.is_valid(self.attachment, self.destination):
                self.download_succeeded.emit(self.attachment, str(self.destination))
                return
            if self._cancelled:
                self.download_cancelled.emit(self.attachment)
                return
            attachment_id = int(self.attachment["id"])
            stream_download = getattr(self.service, "chat_download_attachment_to_file", None)
            if callable(stream_download):
                # Fase 5: streaming direto para o .part, sem carregar o arquivo inteiro em RAM,
                # com progresso real e cancelamento capaz de interromper a leitura em andamento.
                found = stream_download(
                    attachment_id,
                    part_path,
                    progress_callback=lambda sent, total: self.progress_changed.emit(sent, total),
                    cancel_checker=lambda: self._cancelled,
                )
                if not found:
                    raise RuntimeError("O servidor nao retornou o arquivo.")
            else:
                self.progress_changed.emit(0, int(self.attachment.get("size") or 0))
                data = self.service.chat_download_attachment(attachment_id)
                if self._cancelled:
                    self.download_cancelled.emit(self.attachment)
                    return
                if data is None:
                    raise RuntimeError("O servidor nao retornou o arquivo.")
                part_path.write_bytes(data)
                self.progress_changed.emit(len(data), len(data))
            if self._cancelled:
                self.download_cancelled.emit(self.attachment)
                return
            part_path.replace(self.destination)
            os.utime(self.destination, (time.time(), time.time()))
            cache.prune()
            self.download_succeeded.emit(self.attachment, str(self.destination))
        except Exception as exc:
            if "download_cancelled" in str(exc):
                self.download_cancelled.emit(self.attachment)
            else:
                self.download_failed.emit(self.attachment, str(exc))
        finally:
            try:
                if part_path.exists():
                    part_path.unlink()
            except OSError:
                pass
            self.finished.emit()
