from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal


WEIGHT_QUANTIZE = Decimal("0.0001")


def normalize_known_weight(value: Decimal | None) -> Decimal | None:
    """Return a positive known weight, or ``None`` for unknown/legacy zero.

    Zero remains readable in historical rows, but new writes never use it to
    represent missing information.
    """

    if value is None or value <= Decimal("0"):
        return None
    return value.quantize(WEIGHT_QUANTIZE)


def calculate_known_weight(quantity: Decimal, unit_weight: Decimal | None) -> Decimal | None:
    known = normalize_known_weight(unit_weight)
    if known is None:
        return None
    return (quantity * known).quantize(WEIGHT_QUANTIZE)


@dataclass(frozen=True)
class WeightCoverage:
    known_weight: Decimal
    known_items: int
    total_items: int

    @property
    def complete(self) -> bool:
        return self.known_items == self.total_items


def calculate_weight_coverage(values: Iterable[Decimal | None]) -> WeightCoverage:
    rows = list(values)
    known = [value for value in (normalize_known_weight(row) for row in rows) if value is not None]
    return WeightCoverage(
        known_weight=sum(known, Decimal("0")).quantize(WEIGHT_QUANTIZE),
        known_items=len(known),
        total_items=len(rows),
    )
