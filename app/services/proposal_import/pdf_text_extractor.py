from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber


class PdfTextExtractionError(ValueError):
    pass


@dataclass(frozen=True)
class PdfTextExtraction:
    text: str
    lines: list[str]
    tables: list[list[list[str | None]]] = field(default_factory=list)


def _clean_line(value: str) -> str:
    return " ".join((value or "").split()).strip()


def extract_pdf_text(path: str | Path) -> PdfTextExtraction:
    pdf_path = Path(path)
    if not pdf_path.is_file():
        raise PdfTextExtractionError(f"Arquivo PDF nao encontrado: {pdf_path}")
    try:
        with pdfplumber.open(pdf_path) as pdf:
            texts: list[str] = []
            tables: list[list[list[str | None]]] = []
            for page in pdf.pages:
                texts.append(page.extract_text(x_tolerance=2, y_tolerance=3) or "")
                for table in page.extract_tables() or []:
                    tables.append(table)
    except Exception as exc:
        raise PdfTextExtractionError("Nao foi possivel ler o PDF informado.") from exc

    text = "\n".join(texts).strip()
    if len(text) < 40:
        raise PdfTextExtractionError(
            "O PDF nao possui texto pesquisavel. OCR sera tratado em uma etapa futura."
        )
    lines = [_clean_line(line) for line in text.splitlines() if _clean_line(line)]
    return PdfTextExtraction(text=text, lines=lines, tables=tables)
