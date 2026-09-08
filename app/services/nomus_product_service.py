from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.services.app_logging import get_logger
from app.services.nomus_api_client import NomusApiClient, NomusApiClientError
from app.services.proposal_import.normalizers import NormalizationError, normalize_decimal


log = get_logger("nomus_product_service")

PRODUCT_ENDPOINT = "produtos"

WARNING_PRODUCT_WEIGHT_MISSING = "NOMUS_PRODUCT_WEIGHT_MISSING"
WARNING_PRODUCT_WEIGHT_INVALID = "NOMUS_PRODUCT_WEIGHT_INVALID"
WARNING_PRODUCT_LOOKUP_FAILED = "NOMUS_PRODUCT_LOOKUP_FAILED"
WARNING_PRODUCT_RESPONSE_INVALID = "NOMUS_PRODUCT_RESPONSE_INVALID"
WARNING_PRODUCT_GROSS_WEIGHT_USED = "NOMUS_PRODUCT_GROSS_WEIGHT_USED"


@dataclass(frozen=True)
class NomusProductWeight:
    product_id: int
    net_unit_weight: Decimal | None
    gross_unit_weight: Decimal | None
    selected_unit_weight: Decimal | None
    source: str
    warning: str | None = None


class NomusProductService:
    """Read-only service for operational product weights from Nomus.

    Only the allowlisted product id and unit-weight fields are read. The
    response is not stored and commercial fields are intentionally ignored.
    """

    def __init__(self, client: NomusApiClient):
        self.client = client

    def fetch_product_weight(self, product_id: Any) -> NomusProductWeight:
        safe_id = _safe_product_id(product_id)
        if safe_id is None:
            return NomusProductWeight(
                0,
                None,
                None,
                None,
                "missing",
                WARNING_PRODUCT_LOOKUP_FAILED,
            )
        try:
            payload = self.client.get(f"{PRODUCT_ENDPOINT}/{safe_id}")
        except NomusApiClientError as exc:
            log.warning(
                "Peso do produto Nomus nao consultado | produto_id=%s | categoria=%s | status=%s",
                safe_id,
                exc.category,
                exc.status_code,
            )
            return NomusProductWeight(
                safe_id,
                None,
                None,
                None,
                "missing",
                WARNING_PRODUCT_LOOKUP_FAILED,
            )
        if not isinstance(payload, dict):
            log.warning("Resposta de produto Nomus invalida | produto_id=%s | raiz=%s", safe_id, type(payload).__name__)
            return NomusProductWeight(
                safe_id,
                None,
                None,
                None,
                "missing",
                WARNING_PRODUCT_RESPONSE_INVALID,
            )
        return product_weight_from_payload(safe_id, payload)


def product_weight_from_payload(product_id: int, payload: dict[str, Any]) -> NomusProductWeight:
    net = _safe_positive_decimal(payload.get("pesoLiquidoUnitario"))
    gross = _safe_positive_decimal(payload.get("pesoBrutoUnitario"))
    if _has_invalid_negative(payload.get("pesoLiquidoUnitario")) or _has_invalid_negative(payload.get("pesoBrutoUnitario")):
        return NomusProductWeight(
            product_id,
            net,
            gross,
            None,
            "missing",
            WARNING_PRODUCT_WEIGHT_INVALID,
        )
    if net is not None:
        return NomusProductWeight(product_id, net, gross, net, "nomus_product_net_weight", None)
    if gross is not None:
        return NomusProductWeight(product_id, net, gross, gross, "nomus_product_gross_weight", WARNING_PRODUCT_GROSS_WEIGHT_USED)
    return NomusProductWeight(product_id, None, None, None, "missing", WARNING_PRODUCT_WEIGHT_MISSING)


def _safe_positive_decimal(value: Any) -> Decimal | None:
    try:
        number = normalize_decimal(value)
    except NormalizationError:
        return None
    if number is None:
        return None
    if number < 0:
        return None
    return number


def _has_invalid_negative(value: Any) -> bool:
    try:
        number = normalize_decimal(value)
    except NormalizationError:
        return value not in (None, "")
    return number is not None and number < 0


def _safe_product_id(value: Any) -> int | None:
    try:
        number = normalize_decimal(value)
    except NormalizationError:
        return None
    if number is None or number <= 0 or number != number.to_integral_value():
        return None
    return int(number)
