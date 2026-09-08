from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

try:
    import fitz
except ImportError as exc:  # pragma: no cover - exercised only when dependency is missing.
    fitz = None
    _FITZ_IMPORT_ERROR = exc
else:
    _FITZ_IMPORT_ERROR = None


MIN_TEXT_CHARACTERS = 30
MIN_TEXT_WORDS = 4
MIN_ALPHANUMERIC_RATIO = Decimal("0.35")


class PdfExtractionError(ValueError):
    pass


class PdfOpenError(PdfExtractionError):
    pass


class InvalidPdfError(PdfExtractionError):
    pass


class EncryptedPdfError(PdfExtractionError):
    pass


class PdfTextExtractionError(PdfExtractionError):
    pass


class PdfWithoutExtractableTextError(PdfTextExtractionError):
    pass


@dataclass(frozen=True)
class PdfRegion:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def center_x(self) -> float:
        return self.x0 + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y0 + self.height / 2

    def contains(self, other: PdfRegion) -> bool:
        return self.x0 <= other.x0 and self.y0 <= other.y0 and self.x1 >= other.x1 and self.y1 >= other.y1


@dataclass(frozen=True)
class PdfWord(PdfRegion):
    text: str
    page_number: int
    block_number: int | None = None
    line_number: int | None = None
    word_number: int | None = None


@dataclass(frozen=True)
class PdfTextBlock(PdfRegion):
    text: str
    page_number: int
    block_number: int | None = None
    block_type: int | None = None


@dataclass(frozen=True)
class PdfTextDetectionResult:
    has_text: bool
    character_count: int
    word_count: int
    alphanumeric_ratio: Decimal
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_text": self.has_text,
            "character_count": self.character_count,
            "word_count": self.word_count,
            "alphanumeric_ratio": str(self.alphanumeric_ratio),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PdfExtractionContext:
    file_name: str
    page_count: int
    full_text: str
    words: list[PdfWord]
    blocks: list[PdfTextBlock]
    has_extractable_text: bool
    text_detection: PdfTextDetectionResult
    metadata: dict[str, Any] = field(default_factory=dict)

    def page_size(self, page_number: int) -> tuple[float, float] | None:
        sizes = self.metadata.get("page_sizes") or {}
        size = sizes.get(str(page_number)) or sizes.get(page_number)
        if not size or len(size) != 2:
            return None
        return float(size[0]), float(size[1])


def has_extractable_text(text: str, words: list[PdfWord] | None = None, page_count: int = 0) -> PdfTextDetectionResult:
    cleaned = text or ""
    character_count = len(cleaned.strip())
    word_count = len(words or re.findall(r"\b\w+\b", cleaned, flags=re.UNICODE))
    alphanumeric_count = sum(1 for char in cleaned if char.isalnum())
    non_space_count = sum(1 for char in cleaned if not char.isspace())
    ratio = Decimal(alphanumeric_count) / Decimal(non_space_count) if non_space_count else Decimal("0")
    ratio = ratio.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if page_count <= 0:
        return PdfTextDetectionResult(False, character_count, word_count, ratio, "documento sem paginas")
    if character_count < MIN_TEXT_CHARACTERS:
        return PdfTextDetectionResult(False, character_count, word_count, ratio, "texto insuficiente")
    if word_count < MIN_TEXT_WORDS:
        return PdfTextDetectionResult(False, character_count, word_count, ratio, "palavras insuficientes")
    if ratio < MIN_ALPHANUMERIC_RATIO:
        return PdfTextDetectionResult(False, character_count, word_count, ratio, "baixa proporcao alfanumerica")
    return PdfTextDetectionResult(True, character_count, word_count, ratio, "texto pesquisavel detectado")


def words_in_region(words: list[PdfWord], region: PdfRegion) -> list[PdfWord]:
    return [word for word in words if region.contains(word)]


def horizontally_close(first: PdfRegion, second: PdfRegion, max_distance: float = 8.0) -> bool:
    return abs(second.x0 - first.x1) <= max_distance or abs(first.x0 - second.x1) <= max_distance


def vertically_close(first: PdfRegion, second: PdfRegion, max_distance: float = 4.0) -> bool:
    return abs(second.y0 - first.y0) <= max_distance or abs(second.y1 - first.y1) <= max_distance


def sort_words_reading_order(words: list[PdfWord]) -> list[PdfWord]:
    return sorted(words, key=lambda word: (word.page_number, word.block_number or 0, word.line_number or 0, word.y0, word.x0))


class PdfDocumentContext:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.file_name = self.path.name
        self._document: Any | None = None
        self._closed = True
        self._open_seconds = 0.0

    def __enter__(self) -> PdfDocumentContext:
        self.open()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    @property
    def page_count(self) -> int:
        self._ensure_open()
        return int(self._document.page_count)

    @property
    def metadata(self) -> dict[str, Any]:
        self._ensure_open()
        return dict(self._document.metadata or {})

    @property
    def is_closed(self) -> bool:
        return self._closed

    def open(self) -> None:
        if fitz is None:
            raise PdfOpenError("PyMuPDF nao esta instalado.") from _FITZ_IMPORT_ERROR
        if not self.path.is_file():
            raise PdfOpenError(f"Arquivo PDF nao encontrado: {self.path.name}")
        start = time.perf_counter()
        try:
            self._document = fitz.open(self.path)
        except RuntimeError as exc:
            raise InvalidPdfError("Arquivo PDF invalido ou corrompido.") from exc
        except Exception as exc:
            raise PdfOpenError("Nao foi possivel abrir o PDF.") from exc
        self._open_seconds = time.perf_counter() - start
        self._closed = False
        if bool(getattr(self._document, "is_encrypted", False)):
            self.close()
            raise EncryptedPdfError("PDF criptografado nao pode ser lido nesta etapa.")

    def close(self) -> None:
        if self._document is not None:
            self._document.close()
        self._document = None
        self._closed = True

    def get_full_text(self) -> str:
        self._ensure_open()
        page_texts: list[str] = []
        for page_index in range(self.page_count):
            page = self._document.load_page(page_index)
            page_texts.append(f"--- PAGE {page_index + 1} ---\n{page.get_text('text') or ''}".rstrip())
        return "\n\n".join(page_texts).strip()

    def get_blocks(self) -> list[PdfTextBlock]:
        self._ensure_open()
        blocks: list[PdfTextBlock] = []
        for page_index in range(self.page_count):
            page = self._document.load_page(page_index)
            for block in page.get_text("blocks") or []:
                if len(block) < 5:
                    continue
                text = str(block[4] or "").strip()
                block_type = int(block[6]) if len(block) > 6 and block[6] is not None else None
                if not text:
                    continue
                blocks.append(
                    PdfTextBlock(
                        x0=float(block[0]),
                        y0=float(block[1]),
                        x1=float(block[2]),
                        y1=float(block[3]),
                        text=text,
                        page_number=page_index + 1,
                        block_number=int(block[5]) if len(block) > 5 and block[5] is not None else None,
                        block_type=block_type,
                    )
                )
        return blocks

    def get_words(self) -> list[PdfWord]:
        self._ensure_open()
        words: list[PdfWord] = []
        for page_index in range(self.page_count):
            page = self._document.load_page(page_index)
            for word in page.get_text("words") or []:
                if len(word) < 5:
                    continue
                words.append(
                    PdfWord(
                        x0=float(word[0]),
                        y0=float(word[1]),
                        x1=float(word[2]),
                        y1=float(word[3]),
                        text=str(word[4]),
                        page_number=page_index + 1,
                        block_number=int(word[5]) if len(word) > 5 and word[5] is not None else None,
                        line_number=int(word[6]) if len(word) > 6 and word[6] is not None else None,
                        word_number=int(word[7]) if len(word) > 7 and word[7] is not None else None,
                    )
                )
        return words

    def get_page_dicts(self) -> list[dict[str, Any]]:
        self._ensure_open()
        return [self._document.load_page(page_index).get_text("dict") for page_index in range(self.page_count)]

    def extract(self, *, require_text: bool = True) -> PdfExtractionContext:
        self._ensure_open()
        total_start = time.perf_counter()
        text_start = time.perf_counter()
        full_text = self.get_full_text()
        text_seconds = time.perf_counter() - text_start
        structure_start = time.perf_counter()
        words = sort_words_reading_order(self.get_words())
        blocks = self.get_blocks()
        structure_seconds = time.perf_counter() - structure_start
        detection = has_extractable_text(full_text, words, self.page_count)
        page_sizes = {
            str(page_index + 1): (
                float(self._document.load_page(page_index).rect.width),
                float(self._document.load_page(page_index).rect.height),
            )
            for page_index in range(self.page_count)
        }
        metadata = {
            "file_name": self.file_name,
            "page_count": self.page_count,
            "engine": "PyMuPDF",
            "pymupdf_version": _pymupdf_version(),
            "page_sizes": page_sizes,
            "character_count": detection.character_count,
            "word_count": detection.word_count,
            "block_count": len(blocks),
            "open_seconds": round(self._open_seconds, 6),
            "text_seconds": round(text_seconds, 6),
            "structure_seconds": round(structure_seconds, 6),
            "total_seconds": round(time.perf_counter() - total_start + self._open_seconds, 6),
            "has_extractable_text": detection.has_text,
            "text_detection_reason": detection.reason,
        }
        if require_text and not detection.has_text:
            raise PdfWithoutExtractableTextError(f"PDF sem texto pesquisavel: {detection.reason}")
        return PdfExtractionContext(
            file_name=self.file_name,
            page_count=self.page_count,
            full_text=full_text,
            words=words,
            blocks=blocks,
            has_extractable_text=detection.has_text,
            text_detection=detection,
            metadata=metadata,
        )

    def _ensure_open(self) -> None:
        if self._closed or self._document is None:
            raise PdfTextExtractionError("O contexto do PDF ja foi fechado.")


def extract_pdf_context(path: str | Path, *, require_text: bool = True) -> PdfExtractionContext:
    with PdfDocumentContext(path) as context:
        return context.extract(require_text=require_text)


def _pymupdf_version() -> str:
    if fitz is None:
        return "unavailable"
    version = getattr(fitz, "version", None)
    if isinstance(version, tuple) and version:
        return str(version[0])
    return str(version or "unknown")
