from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


_INVISIBLE_CHARS_RE = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_DESCRIPTION_PREFIX_NOISE_RE = re.compile(
    r"^\s*(?:(?:PEDIDO\s+DE\s+)?COMPRA\s*(?:[-–—:]|\s+)\s*CLIENTE|PROD\.?\s+CLIENTE)\b\s*(?:\(\s*\))?\s*[-–—:]?\s*(?:0\s+)?",
    re.IGNORECASE,
)


class NormalizationError(ValueError):
    pass


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ")
    text = _INVISIBLE_CHARS_RE.sub("", text)
    return " ".join(text.split())


def normalize_optional_text(value: Any) -> str | None:
    text = normalize_text(value)
    return text or None


def normalize_identifier(value: Any) -> str | None:
    text = normalize_optional_text(value)
    return text.upper() if text else None


def normalize_description(value: Any) -> str:
    text = normalize_text(value)
    cleaned = _DESCRIPTION_PREFIX_NOISE_RE.sub("", text)
    return cleaned.lstrip(" -:\t|").rstrip(" \t|")


def normalize_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    raw = normalize_text(value)
    if not raw:
        return None
    raw = raw.replace(" ", "")
    if "," in raw and "." in raw:
        decimal_separator = "," if raw.rfind(",") > raw.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        raw = raw.replace(thousands_separator, "")
        if decimal_separator == ",":
            raw = raw.replace(",", ".")
    elif "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise NormalizationError(f"Numero decimal invalido: {value!r}") from exc


def normalize_integer(value: Any) -> int | None:
    number = normalize_decimal(value)
    if number is None:
        return None
    if number != number.to_integral_value():
        raise NormalizationError(f"Numero inteiro invalido: {value!r}")
    return int(number)


def normalize_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = normalize_text(value)
    if not text:
        return None
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise NormalizationError(f"Data invalida: {value!r}")
