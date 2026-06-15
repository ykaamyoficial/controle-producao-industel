from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pdfplumber


class NomusPdfParserError(ValueError):
    """Raised when a PDF cannot be safely recognized as a Nomus proposal."""


class NomusPdfTextRequiredError(NomusPdfParserError):
    """Raised for scanned PDFs because OCR is intentionally not enabled yet."""


@dataclass(frozen=True)
class NomusItem:
    item_number: int
    description: str
    quantity: int
    weight_kg: float | None
    weight_needs_confirmation: bool


@dataclass(frozen=True)
class NomusProposal:
    source: str
    proposal_number: str | None
    raw_budget_number: str | None
    client: str | None
    site: str | None
    proposal_date: str | None
    delivery_deadline_raw: str | None
    delivery_deadline_needs_confirmation: bool
    purchase_order: str | None
    lot: str | None
    items: list[NomusItem] = field(default_factory=list)
    operational_notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        # Explicit allowlist: commercial fields cannot leak into the result if
        # the internal parser evolves in future versions.
        return {
            "source": self.source,
            "proposal_number": self.proposal_number,
            "raw_budget_number": self.raw_budget_number,
            "client": self.client,
            "site": self.site,
            "proposal_date": self.proposal_date,
            "delivery_deadline_raw": self.delivery_deadline_raw,
            "delivery_deadline_needs_confirmation": self.delivery_deadline_needs_confirmation,
            "purchase_order": self.purchase_order,
            "lot": self.lot,
            "items": [
                {
                    "item_number": item.item_number,
                    "description": item.description,
                    "quantity": item.quantity,
                    "weight_kg": item.weight_kg,
                    "weight_needs_confirmation": item.weight_needs_confirmation,
                }
                for item in self.items
            ],
            "operational_notes": list(self.operational_notes),
            "warnings": list(self.warnings),
        }


_BUDGET_RE = re.compile(r"\bOR[ÇC]AMENTO\s*:\s*(ETCP\s*\d+)\b", re.IGNORECASE)
_DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
_SITE_RE = re.compile(r"DADOS\s+DA\s+OBRA\s*:\s*(?:SITE\s*-\s*)?(.+)", re.IGNORECASE)
_DEADLINE_RE = re.compile(r"\b\d+\s+DIAS?\b", re.IGNORECASE)
_PRODUCT_CODE_RE = re.compile(r"^\d{3}\.\d{3}\s*-\s*", re.IGNORECASE)
_ITEM_ROW_RE = re.compile(
    r"^(?P<number>\d{3})\s+\S+\s+(?P<description>.*?)\s+"
    r"(?P<ncm>\d{8})\s+(?P<quantity>\d+)\s+.*$",
    re.IGNORECASE,
)
_WEIGHT_RE = re.compile(
    r"\bPESO\s*(?:TOTAL\s*)?[:=\-]?\s*(\d+(?:[.,]\d+)?)\s*KG\b",
    re.IGNORECASE,
)
_PO_RE = re.compile(
    r"\b(?:PEDIDO(?:\s+DE\s+COMPRA)?|ORDEM\s+DE\s+COMPRA|OC)\s*[:#-]\s*([A-Z0-9./-]+)",
    re.IGNORECASE,
)
_LOT_RE = re.compile(r"\bLOTE\s*[:#-]\s*([A-Z0-9./-]+)", re.IGNORECASE)


def _clean_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" -|\t")


def _ascii_upper(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char)).upper()


def _proposal_number(raw_budget_number: str | None) -> str | None:
    if not raw_budget_number:
        return None
    digits = re.sub(r"\D", "", raw_budget_number)
    return f"CP{int(digits):05d}" if digits else None


def _iso_date(raw_date: str | None) -> str | None:
    if not raw_date:
        return None
    try:
        return datetime.strptime(raw_date, "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def _extract_client(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        if "DADOS DO CLIENTE" not in _ascii_upper(line):
            continue
        for candidate in lines[index + 1 : index + 4]:
            match = re.match(r"(.+?)\s+CNPJ\s*:", candidate, re.IGNORECASE)
            if match:
                return _clean_space(match.group(1))
    return None


def _extract_deadline(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        if "PRAZO DE ENTREGA" not in _ascii_upper(line):
            continue
        match = _DEADLINE_RE.search(line)
        if match:
            return _clean_space(match.group(0)).upper()
        for candidate in lines[index + 1 : index + 3]:
            match = _DEADLINE_RE.search(candidate)
            if match:
                return _clean_space(match.group(0)).upper()
    return None


def _extract_optional_identifier(pattern: re.Pattern[str], lines: list[str]) -> str | None:
    for line in lines:
        # Item descriptions may mention pedido/lote as ordinary words. Restrict
        # optional identifiers to the document header, before the item table.
        if "DESCRICAO DO PRODUTO" in _ascii_upper(line):
            break
        match = pattern.search(line)
        if match:
            return _clean_space(match.group(1)).upper()
    return None


def _extract_operational_notes(lines: list[str]) -> list[str]:
    notes: list[str] = []
    collecting = False
    for line in lines:
        normalized = _ascii_upper(line)
        if re.match(r"^OBSERVACOES?\s+(?:TECNICAS?|OPERACIONAIS?)\s*:", normalized):
            collecting = True
            remainder = line.split(":", 1)[1].strip() if ":" in line else ""
            if remainder:
                notes.append(_clean_space(remainder))
            continue
        if collecting and re.match(r"^[A-ZÁÉÍÓÚÂÊÔÃÕÇ ]{4,}:$", line):
            break
        if collecting:
            notes.append(_clean_space(line))
    return [note for note in notes if note]


def _item_section(lines: list[str]) -> list[str]:
    start = None
    end = None
    for index, line in enumerate(lines):
        normalized = _ascii_upper(line)
        if start is None and "DESCRICAO DO PRODUTO" in normalized and "QTD" in normalized:
            start = index + 1
            continue
        if start is not None and re.match(r"^TOTAL\b", normalized):
            end = index
            break
    if start is None:
        return []
    return lines[start:end]


def _remove_explicit_weight(description: str) -> str:
    cleaned = _WEIGHT_RE.sub("", description)
    return _clean_space(re.sub(r"\s+-\s*(?:-|$)", " ", cleaned))


def _extract_items(lines: list[str]) -> list[NomusItem]:
    section = _item_section(lines)
    starts = [index for index, line in enumerate(section) if _PRODUCT_CODE_RE.match(line)]
    items: list[NomusItem] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(section)
        block = section[start:end]
        item_match = None
        item_line_index = None
        for index, line in enumerate(block):
            match = _ITEM_ROW_RE.match(line)
            if match:
                item_match = match
                item_line_index = index
                break
        if not item_match or item_line_index is None:
            continue

        description_parts = [block[0]]
        description_parts.extend(block[1:item_line_index])
        description_parts.append(item_match.group("description"))
        description_parts.extend(block[item_line_index + 1 :])
        full_description = _clean_space(" ".join(description_parts))
        weight_match = _WEIGHT_RE.search(full_description)
        weight = (
            float(weight_match.group(1).replace(".", "").replace(",", "."))
            if weight_match
            else None
        )
        items.append(
            NomusItem(
                item_number=int(item_match.group("number")),
                description=_remove_explicit_weight(full_description),
                quantity=int(item_match.group("quantity")),
                weight_kg=weight,
                weight_needs_confirmation=weight is None,
            )
        )
    return items


def parse_nomus_pdf(path: str | Path) -> NomusProposal:
    """Read a text-based Nomus proposal without returning commercial data."""
    pdf_path = Path(path)
    if not pdf_path.is_file():
        raise NomusPdfParserError(f"Arquivo PDF nao encontrado: {pdf_path}")
    try:
        with pdfplumber.open(pdf_path) as pdf:
            page_texts = [
                page.extract_text(x_tolerance=2, y_tolerance=3) or ""
                for page in pdf.pages
            ]
    except Exception as exc:
        raise NomusPdfParserError("Nao foi possivel ler o PDF informado.") from exc

    text = "\n".join(page_texts).strip()
    if len(text) < 40:
        raise NomusPdfTextRequiredError(
            "O PDF nao possui texto pesquisavel. OCR sera tratado em uma etapa futura."
        )
    lines = [_clean_space(line) for line in text.splitlines() if _clean_space(line)]
    budget_match = _BUDGET_RE.search(text)
    if not budget_match:
        raise NomusPdfParserError("O documento nao foi reconhecido como proposta Nomus.")

    raw_budget = _clean_space(budget_match.group(1)).upper()
    site = None
    for line in lines:
        match = _SITE_RE.search(line)
        if match:
            site = _clean_space(match.group(1)).upper()
            break
    raw_date = None
    for line in lines[:8]:
        match = _DATE_RE.search(line)
        if match:
            raw_date = match.group(1)
            break
    deadline = _extract_deadline(lines)
    items = _extract_items(lines)
    warnings: list[str] = []
    client = _extract_client(lines)
    if not client:
        warnings.append("Cliente nao identificado; precisa confirmacao.")
    if not site:
        warnings.append("Obra/Site nao identificado; precisa confirmacao.")
    if not items:
        warnings.append("Nenhum item operacional foi identificado; precisa confirmacao.")
    if any(item.weight_needs_confirmation for item in items):
        warnings.append("Existem itens sem peso explicitamente informado em kg.")
    if deadline:
        warnings.append("Prazo relativo precisa de confirmacao humana.")

    return NomusProposal(
        source="nomus_pdf",
        proposal_number=_proposal_number(raw_budget),
        raw_budget_number=raw_budget,
        client=client,
        site=site,
        proposal_date=_iso_date(raw_date),
        delivery_deadline_raw=deadline,
        delivery_deadline_needs_confirmation=bool(deadline),
        purchase_order=_extract_optional_identifier(_PO_RE, lines),
        lot=_extract_optional_identifier(_LOT_RE, lines),
        items=items,
        operational_notes=_extract_operational_notes(lines),
        warnings=warnings,
    )
