from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

from ..normalizers import NormalizationError, normalize_decimal, normalize_description, normalize_integer, normalize_optional_text
from .models import FINANCIAL_HEADER_TERMS, FINANCIAL_TEXT_TERMS


_MONEY_RE = re.compile(r"R\$\s*\d[\d.]*,\d{2}|\b\d{1,3}(?:\.\d{3})*,\d{2}\b")
_PERCENT_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*%")


def ascii_upper(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in normalized if not unicodedata.combining(char)).upper()


def clean_text(value: object) -> str:
    text = str(value or "").replace("\xa0", " ")
    return " ".join(text.split()).strip(" -|\t")


def header_is_financial(value: object) -> bool:
    upper = ascii_upper(value)
    if "PESO TOTAL" in upper or upper.strip() in {"PESO", "KG"}:
        return False
    return any(term in upper for term in FINANCIAL_HEADER_TERMS)


def contains_financial_text(value: object) -> bool:
    upper = ascii_upper(value)
    return "R$" in upper or any(term in upper for term in FINANCIAL_TEXT_TERMS)


def strip_financial_text(value: object) -> str:
    text = clean_text(value)
    text = _MONEY_RE.sub("", text)
    text = _PERCENT_RE.sub("", text)
    for term in FINANCIAL_TEXT_TERMS:
        text = re.sub(re.escape(term), "", text, flags=re.IGNORECASE)
        text = re.sub(re.escape(ascii_upper(term)), "", text, flags=re.IGNORECASE)
    return clean_text(text)


def join_description_fragments(parts: list[object]) -> str:
    """Join wrapped product description lines without duplicating overlaps."""
    description = ""
    for part in parts:
        fragment = _description_fragment(part)
        if not fragment:
            continue
        if contains_financial_text(fragment):
            fragment = _description_fragment(strip_financial_text(fragment))
            if not fragment:
                continue
        if not description:
            description = fragment
            continue
        description = _append_description_fragment(description, fragment)
    return _clean_description_join(description)


def _description_fragment(value: object) -> str:
    text = str(value or "").replace("\xa0", " ")
    text = " ".join(text.split()).strip(" \t|")
    return text


def _append_description_fragment(current: str, fragment: str) -> str:
    current = current.rstrip()
    fragment = _remove_duplicate_overlap(current, fragment.strip(" \t|"))
    if not fragment:
        return current
    if current.endswith("-") and not current.endswith(" -"):
        return _clean_description_join(f"{current}{fragment.lstrip(' -')}")
    return _clean_description_join(f"{current} {fragment}")


def _clean_description_join(value: object) -> str:
    text = str(value or "").replace("\xa0", " ")
    return " ".join(text.split()).strip(" \t|")


def _remove_duplicate_overlap(current: str, fragment: str) -> str:
    if not current or not fragment:
        return fragment
    current_upper = current.upper()
    fragment_upper = fragment.upper()
    max_size = min(len(current_upper), len(fragment_upper))
    for size in range(max_size, 3, -1):
        if current_upper[-size:] == fragment_upper[:size]:
            return fragment[size:].lstrip(" -")

    current_tokens = current_upper.split()
    fragment_tokens = fragment_upper.split()
    max_tokens = min(len(current_tokens), len(fragment_tokens), 8)
    for size in range(max_tokens, 1, -1):
        if current_tokens[-size:] == fragment_tokens[:size]:
            raw_tokens = fragment.split()
            return " ".join(raw_tokens[size:]).lstrip(" -")
    return fragment


def normalize_item_number(value: object) -> int | None:
    text = clean_text(value)
    if not text:
        return None
    match = re.search(r"\b(\d{1,4})\b", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def normalize_quantity(value: object) -> Decimal | None:
    try:
        quantity = normalize_decimal(clean_text(value))
    except NormalizationError:
        return None
    if quantity is None or quantity <= 0:
        return None
    return quantity


def normalize_weight(value: object) -> Decimal | None:
    text = clean_text(value)
    if not text:
        return None
    text = re.sub(r"\bKG\b", "", text, flags=re.IGNORECASE)
    try:
        weight = normalize_decimal(text)
    except NormalizationError:
        return None
    if weight is None or weight < 0:
        return None
    return weight


def normalize_description_safe(value: object) -> str:
    return strip_financial_text(normalize_description(value))


def safe_optional_text(value: object) -> str | None:
    return normalize_optional_text(strip_financial_text(value))


def decimal_to_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def decimal_to_int_if_integral(value: Decimal | None) -> int | None:
    if value is None:
        return None
    try:
        return normalize_integer(value)
    except NormalizationError:
        return None
