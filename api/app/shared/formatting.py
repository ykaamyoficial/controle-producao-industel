from __future__ import annotations

from decimal import Decimal, InvalidOperation


def parse_decimal(value, default: str = "0") -> Decimal:
    """Analisa um valor numerico vindo de metadata/coluna. Nunca levanta —
    retorna `default` para entradas invalidas, espelhando
    app/ui/numeric_utils.py::parse_decimal do lado desktop."""
    if value is None or value == "":
        return Decimal(default)
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def format_quantity(value, *, unit: str | None = None) -> str:
    """Formata um valor numerico para exibicao, cortando zeros a direita sem
    arredondar (100.0000 -> "100", 50.5000 -> "50,5"). Usado pelos textos
    semanticos de atividade da proposta — nunca exibir o Decimal cru."""
    number = parse_decimal(value)
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    text = (text or "0").replace(".", ",")
    return f"{text} {unit}" if unit else text
