from __future__ import annotations

from decimal import Decimal, InvalidOperation


def parse_decimal(value, default: str = "0") -> Decimal:
    """Parse an API numeric field into Decimal.

    Quantity/weight fields may arrive as decimal strings (e.g. "50.0000",
    from a PostgreSQL Numeric(18, 4) column serialized to JSON) instead of
    plain integers, so callers must not run int(value) on them directly.
    """
    if value is None or value == "":
        return Decimal(default)
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def format_decimal(value) -> str:
    """Format a numeric value for display, trimming trailing zeros without rounding."""
    number = parse_decimal(value)
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def parse_whole_quantity(value, default: int = 0) -> int:
    """Parse a field that must represent a whole unit count (e.g. item quantity).

    Raises ValueError instead of silently truncating when the value has a
    genuine fractional part, so an invalid fractional quantity is never
    misread as a smaller whole number.
    """
    number = parse_decimal(value, default=str(default))
    if number != number.to_integral_value():
        raise ValueError(f"A quantidade deve ser inteira, mas foi recebido: {value!r}")
    return int(number)
