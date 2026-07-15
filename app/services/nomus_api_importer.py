from __future__ import annotations

import re
import time
from dataclasses import dataclass
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.services.app_logging import get_logger
from app.services.nomus_api_client import NomusApiClient, NomusApiClientError
from app.services.nomus_product_service import (
    NomusProductService,
    NomusProductWeight,
    WARNING_PRODUCT_GROSS_WEIGHT_USED,
    WARNING_PRODUCT_LOOKUP_FAILED,
    WARNING_PRODUCT_RESPONSE_INVALID,
    WARNING_PRODUCT_WEIGHT_INVALID,
    WARNING_PRODUCT_WEIGHT_MISSING,
)
from app.services.proposal_import.confidence import calculate_overall_confidence
from app.services.proposal_import.normalizers import (
    NormalizationError,
    normalize_date,
    normalize_decimal,
    normalize_description,
    normalize_identifier,
    normalize_optional_text,
)
from app.services.proposal_import.schemas import (
    FieldConfidence,
    ImportedProposalData,
    ImportedProposalItem,
    ProposalImportIssue,
    ProposalImportMetadata,
    StandardProposalImportResult,
)
from app.services.proposal_import.validators import validate_standard_result


log = get_logger("nomus_api_importer")

NOMUS_PEDIDOS_DOC_SOURCE = "https://atendimento.nomus.com.br/hc/pt-br/articles/35195264156187-Pedido"
ORDER_ENDPOINT = "pedidos"
PROPOSAL_ENDPOINT = "propostas"
MAX_DEFAULT_SEARCH_PAGES = 50

WARNING_ORDER_NOT_FOUND = "NOMUS_API_ORDER_NOT_FOUND"
WARNING_MULTIPLE_ORDERS_FOUND = "NOMUS_API_MULTIPLE_ORDERS_FOUND"
WARNING_ITEMS_MISSING = "NOMUS_API_ITEMS_MISSING"
WARNING_ITEM_DESCRIPTION_MISSING = "NOMUS_API_ITEM_DESCRIPTION_MISSING"
WARNING_ITEM_QUANTITY_INVALID = "NOMUS_API_ITEM_QUANTITY_INVALID"
WARNING_WEIGHT_MISSING = "NOMUS_API_WEIGHT_MISSING"
WARNING_PRODUCT_ID_MISSING = "NOMUS_API_PRODUCT_ID_MISSING"
WARNING_PRODUCT_QUANTITY_INVALID = "NOMUS_API_PRODUCT_QUANTITY_INVALID"
WARNING_FIELD_IGNORED = "NOMUS_API_FIELD_IGNORED"
WARNING_RESPONSE_INCOMPATIBLE = "NOMUS_API_RESPONSE_INCOMPATIBLE"


class NomusApiImportError(RuntimeError):
    """Base error for safe, read-only Nomus proposal import."""


class NomusApiOrderNotFoundError(NomusApiImportError):
    pass


class NomusApiAmbiguousOrderError(NomusApiImportError):
    pass


class NomusApiInvalidResponseError(NomusApiImportError):
    pass


class NomusApiItemsNotFoundError(NomusApiImportError):
    pass


@dataclass(frozen=True)
class NomusApiOrder:
    """Allowlisted operational order fields extracted from Nomus."""

    raw_id: str | None
    codigo_pedido: str | None
    id_externo: str | None
    data_emissao: date | None
    data_entrega: date | None
    cliente: str | None
    obra_site: str | None
    pedido_compra: str | None
    lote: str | None
    observacoes_operacionais: str | None
    items: list["NomusApiOrderItem"]
    ignored_non_operational_fields: bool = False


@dataclass(frozen=True)
class NomusApiOrderItem:
    """Allowlisted operational item fields extracted from Nomus."""

    item_number: int | None
    product_code: str | None
    product_id: str | None
    description: str
    unit: str | None
    quantity: Decimal | None
    unit_weight: Decimal | None
    total_weight: Decimal | None
    weight_source: str
    weight_warning: str | None = None
    ignored_non_operational_fields: bool = False


class NomusApiImporter:
    """Read-only importer for Nomus orders/proposals.

    The official Nomus "Pedido" documentation confirms:
    - GET /rest/pedidos/{id_do_pedido_de_venda}
    - GET /rest/pedidos with pagination through the "pagina" parameter
    - items are returned in the "itensPedido" array.

    No write operation exists in this importer.
    """

    def __init__(self, client: NomusApiClient, *, max_search_pages: int = MAX_DEFAULT_SEARCH_PAGES):
        self.client = client
        self.max_search_pages = max(1, int(max_search_pages or 1))
        self.product_service = NomusProductService(client)

    def fetch_proposal(self, proposal_number: str) -> StandardProposalImportResult:
        requested = normalize_optional_text(proposal_number)
        if not requested:
            raise NomusApiInvalidResponseError("Informe o numero da proposta ou o ID do pedido Nomus.")

        started = time.monotonic()
        normalized = normalize_requested_identifier(requested)
        try:
            if requested.isdigit() and not requested.startswith("0"):
                result = self._fetch_by_internal_id(requested)
            else:
                log.info("Importacao Nomus iniciada | endpoint=%s,%s | identificador=%s", PROPOSAL_ENDPOINT, ORDER_ENDPOINT, normalized.safe_log)
                matches, pages_read, pagination_exhausted, endpoint = self._find_order_in_pages(requested)
                if not matches:
                    suffix = "paginacao esgotada" if pagination_exhausted else "limite de paginas atingido"
                    raise NomusApiOrderNotFoundError(
                        f"Nenhuma proposta Nomus encontrada para {normalized.safe_log} nas {pages_read} paginas consultadas ({suffix})."
                    )
                if len(matches) > 1:
                    raise NomusApiAmbiguousOrderError(
                        f"Mais de um pedido Nomus foi encontrado para {normalized.safe_log}. Informe o ID interno do pedido."
                    )
                result = self.convert_order_payload(
                    matches[0],
                    requested_identifier=requested,
                    endpoint=endpoint,
                    search_pages=pages_read,
                )
        except NomusApiImportError:
            raise
        except NomusApiClientError as exc:
            raise NomusApiImportError(exc.user_message) from exc
        finally:
            log.info(
                "Importacao Nomus finalizada | identificador=%s | tempo_ms=%s",
                normalized.safe_log,
                int((time.monotonic() - started) * 1000),
            )
        return result

    def _fetch_by_internal_id(self, requested: str) -> StandardProposalImportResult:
        normalized = normalize_requested_identifier(requested)
        last_error: Exception | None = None
        for base_endpoint in (PROPOSAL_ENDPOINT, ORDER_ENDPOINT):
            endpoint = f"{base_endpoint}/{requested}"
            log.info("Importacao Nomus iniciada | endpoint=%s | identificador=%s", endpoint, normalized.safe_log)
            try:
                payload = self._client_get(endpoint)
                order_payload = _coerce_order_payload(payload)
                return self.convert_order_payload(order_payload, requested_identifier=requested, endpoint=endpoint)
            except NomusApiOrderNotFoundError as exc:
                last_error = exc
                continue
            except NomusApiClientError as exc:
                if exc.category == "not_found":
                    last_error = exc
                    continue
                raise
        raise NomusApiOrderNotFoundError(f"Nenhuma proposta Nomus encontrada para ID {normalized.safe_log}.") from last_error

    def convert_order_payload(
        self,
        payload: dict[str, Any],
        *,
        requested_identifier: str | None = None,
        endpoint: str = ORDER_ENDPOINT,
        search_pages: int | None = None,
    ) -> StandardProposalImportResult:
        order = self._enrich_order_weights_from_products(parse_order_payload(payload))
        if requested_identifier and not _identifier_matches_any(requested_identifier, order):
            normalized = normalize_requested_identifier(requested_identifier)
            raise NomusApiOrderNotFoundError(f"O pedido retornado nao corresponde a {normalized.safe_log}.")
        if not order.items:
            raise NomusApiItemsNotFoundError("O pedido Nomus nao retornou itens operacionais.")
        result = build_standard_result(order, endpoint=endpoint, search_pages=search_pages)
        log.info(
            "Pedido Nomus convertido | endpoint=%s | proposta=%s | itens=%s | avisos=%s | erros=%s",
            endpoint,
            normalize_requested_identifier(order.codigo_pedido or order.raw_id or "").safe_log,
            len(result.items),
            len(result.warnings),
            len(result.errors),
        )
        return result

    def _find_order_in_pages(self, requested_identifier: str) -> tuple[list[dict[str, Any]], int, bool, str]:
        matches: list[dict[str, Any]] = []
        total_pages_read = 0
        last_endpoint = PROPOSAL_ENDPOINT
        for endpoint in (PROPOSAL_ENDPOINT, ORDER_ENDPOINT):
            endpoint_matches: list[dict[str, Any]] = []
            pagination_exhausted = False
            pages_read = 0
            for page in range(1, self.max_search_pages + 1):
                payload = self._client_get(endpoint, params={"pagina": page})
                pages_read = page
                total_pages_read += 1
                records = _extract_order_list(payload)
                log.info(
                    "Pagina Nomus consultada | endpoint=%s | pagina=%s | registros=%s | raiz=%s | chaves=%s",
                    endpoint,
                    page,
                    len(records),
                    type(payload).__name__,
                    _safe_payload_keys(payload),
                )
                endpoint_matches.extend(record for record in records if _record_matches_identifier(requested_identifier, record))
                if endpoint_matches:
                    break
                if len(records) < 50:
                    pagination_exhausted = True
                    break
            if endpoint_matches:
                return endpoint_matches, pages_read, pagination_exhausted, endpoint
            matches = endpoint_matches
            last_endpoint = endpoint
        return matches, total_pages_read, False, last_endpoint

    def _client_get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any] | list[Any]:
        return self.client.get(endpoint, params=params)

    def _enrich_order_weights_from_products(self, order: NomusApiOrder) -> NomusApiOrder:
        """Fill missing item weight from the product register when Nomus exposes it.

        Some proposal responses return item quantity and product id but omit weight.
        The product endpoint may expose unit-weight fields such as
        pesoLiquidoUnitario/pesoBrutoUnitario. We only read those allowlisted
        operational fields and never import commercial values.
        """

        if not any(item.product_id for item in order.items):
            return order
        cache: dict[str, NomusProductWeight] = {}
        enriched: list[NomusApiOrderItem] = []
        changed = 0
        avoided_calls = 0
        for item in order.items:
            if not item.product_id:
                enriched.append(item)
                continue
            product_id = str(item.product_id).strip()
            if product_id not in cache:
                cache[product_id] = self.product_service.fetch_product_weight(product_id)
            else:
                avoided_calls += 1
            product_weight = cache[product_id].selected_unit_weight
            if product_weight is None:
                enriched.append(replace(item, weight_warning=cache[product_id].warning))
                continue
            if item.quantity is None or item.quantity <= 0:
                enriched.append(replace(item, weight_warning=WARNING_PRODUCT_QUANTITY_INVALID))
                continue
            total_weight = item.quantity * product_weight
            changed += 1
            enriched.append(
                replace(
                    item,
                    unit_weight=product_weight,
                    total_weight=total_weight,
                    weight_source=cache[product_id].source,
                    weight_warning=cache[product_id].warning,
                )
            )
        if changed:
            log.info(
                "Pesos de produto Nomus aplicados | itens=%s | produtos_unicos=%s | consultas_evitadas=%s",
                changed,
                len(cache),
                avoided_calls,
            )
        return replace(order, items=enriched)


@dataclass(frozen=True)
class _NormalizedIdentifier:
    prefix: str | None
    number: str | None
    compact: str
    safe_log: str


def parse_order_payload(payload: dict[str, Any]) -> NomusApiOrder:
    if not isinstance(payload, dict):
        raise NomusApiInvalidResponseError("Resposta Nomus incompativel: pedido deve ser um objeto JSON.")
    ignored = _has_non_operational_fields(payload)
    items_payload = payload.get("itensPedido") or payload.get("itensProposta") or payload.get("items") or payload.get("itens") or []
    if not isinstance(items_payload, list):
        raise NomusApiInvalidResponseError("Resposta Nomus incompativel: lista de itens deve ser uma lista.")

    items = [parse_order_item(item, index + 1) for index, item in enumerate(items_payload) if isinstance(item, dict)]
    proposal_date = _safe_date(_first_present(payload, ("dataEmissao", "dataPedido", "dataProposta", "dataHoraAbertura", "dataCadastro", "dataCriacao")))
    delivery_date = _safe_date(_first_present(payload, ("dataEntregaPadrao", "prazoEntrega", "dataEntrega", "dataPrazoEntrega")))
    if delivery_date is None:
        delivery_date = _delivery_date_from_item_deadline_days(items_payload, proposal_date)
    client_value = _first_present_nested(payload, (
        ("pessoaCliente", "nome"),
        ("pessoaCliente", "razaoSocial"),
        ("cliente", "nome"),
        ("cliente", "razaoSocial"),
        ("nomeCliente",),
        ("nomeCliente",),
    ))
    if client_value is None and not isinstance(payload.get("cliente"), dict):
        client_value = payload.get("cliente")
    return NomusApiOrder(
        raw_id=_safe_text(_first_present(payload, ("id", "idPedido", "idExterno"))),
        codigo_pedido=_safe_text(_first_present(payload, ("codigoPedido", "pedido", "proposta", "numeroPedido", "codigoProposta", "numeroProposta"))),
        id_externo=_safe_text(payload.get("idExterno")),
        data_emissao=proposal_date,
        data_entrega=delivery_date,
        cliente=_safe_text(client_value),
        obra_site=_safe_text(
            _first_present(payload, ("obraSite", "obra_site", "obra", "site", "localObra", "dadosObra", "nomeObra"))
            or _proposal_attribute_value(payload, ("OBRA/SITE", "OBRA", "SITE", "DADOS DA OBRA"))
        ),
        pedido_compra=_safe_text(_first_present(payload, ("pedidoCompraCliente", "ordemCompra", "ocCliente"))),
        lote=_safe_text(_first_present(payload, ("lote", "numeroLote"))),
        observacoes_operacionais=None,
        items=items,
        ignored_non_operational_fields=ignored,
    )


def parse_order_item(payload: dict[str, Any], fallback_number: int) -> NomusApiOrderItem:
    ignored = _has_non_operational_fields(payload)
    item_number = _safe_int(_first_present(payload, ("numeroItem", "sequencia", "ordem")))
    if item_number is None:
        item_number = _safe_int(payload.get("item")) or fallback_number
    product_code = _safe_text(_first_present_nested(payload, (
        ("codigoProduto",),
        ("codProduto",),
        ("codigo",),
        ("produto", "codigo"),
        ("produto", "codigoProduto"),
        ("idProduto",),
        ("idExterno",),
    )))
    product_id = _safe_text(_first_present(payload, ("idProduto",)))
    description = _pick_item_description(payload)
    quantity = _safe_decimal(_first_present(payload, ("quantidade", "qtde", "quantity")))
    unit = _safe_text(_first_present_nested(payload, (
        ("unidade",),
        ("unidadeMedida",),
        ("nomeUnidadeMedida",),
        ("unit",),
        ("produto", "unidade"),
        ("produto", "unidadeMedida"),
    )))
    total_weight = _safe_decimal(_first_present_nested(payload, (
        ("pesoTotal",),
        ("peso_total",),
        ("pesoKg",),
        ("peso_kg",),
        ("weightKg",),
        ("produto", "pesoTotal"),
        ("produto", "pesoKg"),
    )))
    return NomusApiOrderItem(
        item_number=item_number,
        product_code=product_code,
        product_id=product_id,
        description=description,
        unit=unit,
        quantity=quantity,
        unit_weight=None,
        total_weight=total_weight,
        weight_source="nomus_order_item_weight" if total_weight is not None else "missing",
        ignored_non_operational_fields=ignored,
    )


def build_standard_result(order: NomusApiOrder, *, endpoint: str, search_pages: int | None = None) -> StandardProposalImportResult:
    proposal_number = normalize_identifier(order.codigo_pedido or order.raw_id)
    proposal = ImportedProposalData(
        proposal_number=proposal_number,
        raw_budget_number=normalize_identifier(order.id_externo),
        proposal_date=order.data_emissao,
        client=order.cliente,
        site=order.obra_site,
        deadline_days=None,
        deadline_raw=order.data_entrega.isoformat() if order.data_entrega else None,
        purchase_order=order.pedido_compra,
        lot=order.lote,
        operational_notes=None,
    )
    items = [
        ImportedProposalItem(
            item_number=item.item_number,
            product_code=item.product_code,
            description=item.description,
            quantity=item.quantity,
            unit=item.unit,
            total_weight=item.total_weight,
            unit_weight=item.unit_weight,
            weight_needs_confirmation=item.total_weight is None,
            source_method=item.weight_source if item.total_weight is not None else "nomus_api",
        )
        for item in order.items
    ]
    metadata = ProposalImportMetadata(
        source="nomus_api",
        extraction_method="nomus_api_rest",
        requires_human_review=True,
        parser_version="nomus-api-phase3",
        technical_metadata={
            "endpoint": endpoint,
            "search_pages": search_pages,
            "order_items_count": len(items),
            "ignored_non_operational_fields": order.ignored_non_operational_fields or any(i.ignored_non_operational_fields for i in order.items),
            "weight_sources": _weight_source_summary(order.items),
            "docs_source": NOMUS_PEDIDOS_DOC_SOURCE,
        },
    )
    placeholder = StandardProposalImportResult(
        proposal=proposal,
        items=items,
        field_confidences={},
        overall_confidence=Decimal("0.00"),
        warnings=[],
        errors=[],
        metadata=metadata,
    )
    validation_warnings, validation_errors = validate_standard_result(placeholder)
    importer_warnings = _importer_warnings(order, items)
    if metadata.technical_metadata.get("ignored_non_operational_fields"):
        importer_warnings.append(
            ProposalImportIssue(
                "import",
                WARNING_FIELD_IGNORED,
                "Campos nao operacionais foram ignorados pela allowlist.",
                "info",
            )
        )
    warnings = importer_warnings + validation_warnings
    errors = validation_errors
    with_issues = StandardProposalImportResult(
        proposal=proposal,
        items=items,
        field_confidences={},
        overall_confidence=Decimal("0.00"),
        warnings=warnings,
        errors=errors,
        metadata=metadata,
    )
    confidences = _build_confidences(with_issues)
    with_confidence = StandardProposalImportResult(
        proposal=proposal,
        items=items,
        field_confidences=confidences,
        overall_confidence=Decimal("0.00"),
        warnings=warnings,
        errors=errors,
        metadata=metadata,
    )
    overall = calculate_overall_confidence(with_confidence, warnings + errors)
    return StandardProposalImportResult(
        proposal=proposal,
        items=items,
        field_confidences=confidences,
        overall_confidence=overall,
        warnings=warnings,
        errors=errors,
        metadata=metadata,
    )


def normalize_requested_identifier(value: str) -> _NormalizedIdentifier:
    text = normalize_identifier(value) or ""
    compact = re.sub(r"[\s._/-]+", "", text)
    match = re.match(r"^([A-Z]+)0*([0-9]+)$", compact)
    if match:
        prefix, number = match.groups()
        safe = f"{prefix}{number.zfill(5)}"
        return _NormalizedIdentifier(prefix, str(int(number)), compact, safe)
    if compact.isdigit():
        return _NormalizedIdentifier(None, str(int(compact)), compact, f"ID:{int(compact)}")
    return _NormalizedIdentifier(None, None, compact, compact[:24])


def _identifier_matches_any(requested: str, order: NomusApiOrder) -> bool:
    if requested.isdigit() and order.raw_id and str(order.raw_id).strip() == requested.strip():
        return True
    return any(
        _identifiers_match(requested, candidate)
        for candidate in (order.codigo_pedido, order.id_externo, order.raw_id)
        if candidate
    )


def _record_matches_identifier(requested: str, record: dict[str, Any]) -> bool:
    candidates = (
        record.get("codigoPedido"),
        record.get("proposta"),
        record.get("codigoProposta"),
        record.get("numeroProposta"),
        record.get("idExterno"),
        record.get("numeroPedido"),
        record.get("pedido"),
        record.get("proposta"),
        record.get("id"),
    )
    return any(_identifiers_match(requested, candidate) for candidate in candidates if candidate is not None)


def _identifiers_match(left: Any, right: Any) -> bool:
    a = normalize_requested_identifier(str(left))
    b = normalize_requested_identifier(str(right))
    if a.prefix or b.prefix:
        return a.prefix == b.prefix and a.number == b.number
    if a.number is not None and b.number is not None:
        return a.number == b.number
    return a.compact == b.compact


def _coerce_order_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return {key: value for key, value in payload.items() if not str(key).startswith("_nomus_")}
    raise NomusApiInvalidResponseError("Resposta Nomus incompativel: pedido deve ser um objeto JSON.")


def _extract_order_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        raise NomusApiInvalidResponseError("Resposta Nomus incompativel: lista de pedidos invalida.")
    for key in ("pedidos", "propostas", "dados", "data", "resultados", "items", "content"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if "codigoPedido" in payload or "proposta" in payload:
        return [_coerce_order_payload(payload)]
    log.warning(
        "Envelope Nomus incompativel | raiz=%s | chaves=%s | listas=%s",
        type(payload).__name__,
        _safe_payload_keys(payload),
        _safe_list_paths(payload),
    )
    raise NomusApiInvalidResponseError("Resposta Nomus incompativel: lista de pedidos nao encontrada.")


def _safe_payload_keys(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        return [str(key) for key in payload.keys() if not str(key).startswith("_nomus_")][:40]
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return [str(key) for key in payload[0].keys() if not str(key).startswith("_nomus_")][:40]
    return []


def _safe_list_paths(payload: Any, path: str = "$", depth: int = 0) -> list[str]:
    if depth > 3:
        return []
    if isinstance(payload, list):
        paths = [f"{path}[len={len(payload)}]"]
        if payload:
            paths.extend(_safe_list_paths(payload[0], f"{path}[0]", depth + 1))
        return paths[:20]
    if isinstance(payload, dict):
        paths: list[str] = []
        for key, value in payload.items():
            if str(key).startswith("_nomus_"):
                continue
            if isinstance(value, list):
                paths.append(f"{path}.{key}[len={len(value)}]")
                if value:
                    paths.extend(_safe_list_paths(value[0], f"{path}.{key}[0]", depth + 1))
            elif isinstance(value, dict):
                paths.extend(_safe_list_paths(value, f"{path}.{key}", depth + 1))
        return paths[:20]
    return []


def _pick_item_description(payload: dict[str, Any]) -> str:
    value = _first_present_nested(payload, (
        ("descricaoCompleta",),
        ("produto", "descricaoCompleta"),
        ("descricaoProduto",),
        ("descricao",),
        ("produto", "descricao"),
        ("descricaoProduto",),
        ("infoAdProd",),
        ("informacoesAdicionaisProduto",),
        ("produto", "descricaoProduto"),
        ("observacoes",),
    ))
    text = normalize_description(value)
    if text:
        return text
    item_name = _safe_text(payload.get("item"))
    if item_name and not item_name.isdigit():
        return normalize_description(item_name)
    return ""


def _importer_warnings(order: NomusApiOrder, items: list[ImportedProposalItem]) -> list[ProposalImportIssue]:
    warnings: list[ProposalImportIssue] = []
    if not items:
        warnings.append(ProposalImportIssue("items", WARNING_ITEMS_MISSING, "Pedido Nomus sem itens operacionais.", "error"))
    for index, item in enumerate(items):
        if not item.description:
            warnings.append(ProposalImportIssue("description", WARNING_ITEM_DESCRIPTION_MISSING, "Item sem descricao operacional.", "error", index))
        if item.quantity is None or item.quantity <= 0:
            warnings.append(ProposalImportIssue("quantity", WARNING_ITEM_QUANTITY_INVALID, "Quantidade do item ausente ou invalida.", "error", index))
        if item.total_weight is None and item.unit_weight is None:
            warnings.append(ProposalImportIssue("weight", WARNING_WEIGHT_MISSING, "Peso do item ausente no Nomus.", "warning", index))
    seen_weight_warnings: set[tuple[str, str | None]] = set()
    for index, item in enumerate(order.items):
        if not item.product_id:
            key = (WARNING_PRODUCT_ID_MISSING, None)
            if key not in seen_weight_warnings and item.total_weight is None:
                warnings.append(
                    ProposalImportIssue(
                        "weight",
                        WARNING_PRODUCT_ID_MISSING,
                        "O item nao possui identificacao de produto para consultar o peso.",
                        "warning",
                        index,
                    )
                )
                seen_weight_warnings.add(key)
        if item.weight_warning:
            key = (item.weight_warning, item.product_id)
            if key in seen_weight_warnings:
                continue
            warnings.append(
                ProposalImportIssue(
                    "weight",
                    item.weight_warning,
                    _product_weight_warning_message(item.weight_warning),
                    "warning",
                    index,
                )
            )
            seen_weight_warnings.add(key)
    return warnings


def _build_confidences(result: StandardProposalImportResult) -> dict[str, FieldConfidence]:
    def confidence(field_name: str, present: bool, score: str, reason: str) -> FieldConfidence:
        return FieldConfidence(field_name, Decimal(score if present else "0.00"), reason if present else "campo ausente", "nomus_api", False)

    proposal = result.proposal
    item_score = "1.00" if result.items and not any(error.field_name in {"description", "quantity"} for error in result.errors) else "0.70"
    weight_score = "1.00" if result.items and all(item.total_weight is not None or item.unit_weight is not None for item in result.items) else "0.55"
    return {
        "proposal_number": confidence("proposal_number", bool(proposal.proposal_number), "1.00", "campo direto da API"),
        "client": confidence("client", bool(proposal.client), "0.95", "campo operacional da API"),
        "site": confidence("site", bool(proposal.site), "0.95", "campo operacional da API"),
        "proposal_date": confidence("proposal_date", bool(proposal.proposal_date), "1.00", "campo direto da API"),
        "deadline": confidence("deadline", bool(proposal.deadline_raw), "0.95", "data de entrega da API"),
        "items": FieldConfidence("items", Decimal(item_score), "itens retornados em itensPedido", "nomus_api", False),
        "weights": FieldConfidence("weights", Decimal(weight_score), "pesos operacionais da API", "nomus_api", False),
    }


def _safe_text(value: Any) -> str | None:
    return normalize_optional_text(value)


def _safe_decimal(value: Any) -> Decimal | None:
    try:
        return normalize_decimal(value)
    except NormalizationError:
        return None


def _safe_int(value: Any) -> int | None:
    number = _safe_decimal(value)
    if number is None or number != number.to_integral_value():
        return None
    return int(number)


def _safe_identifier(value: Any) -> str:
    text = str(value or "").strip()
    return re.sub(r"[^A-Za-z0-9_.-]", "", text)[:32]


def _safe_date(value: Any) -> date | None:
    if isinstance(value, str):
        value = value.strip()
        if " " in value:
            value = value.split(" ", 1)[0]
    try:
        return normalize_date(value)
    except NormalizationError:
        return None


def _delivery_date_from_item_deadline_days(items_payload: Any, proposal_date: date | None) -> date | None:
    if not proposal_date or not isinstance(items_payload, list):
        return None
    deadlines: list[int] = []
    for item in items_payload:
        if not isinstance(item, dict):
            continue
        days = _safe_int(_first_present(item, ("prazoEntregaDias", "prazoEntrega", "diasPrazoEntrega")))
        if days is not None and days >= 0:
            deadlines.append(days)
    if not deadlines:
        return None
    return proposal_date + timedelta(days=max(deadlines))


def _proposal_attribute_value(payload: dict[str, Any], names: tuple[str, ...]) -> Any:
    attributes = payload.get("atributosProposta") or payload.get("atributos") or payload.get("camposPersonalizados")
    if not isinstance(attributes, list):
        return None
    normalized_names = {_normalize_attribute_name(name) for name in names}
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        name = _normalize_attribute_name(
            _first_present(attribute, ("nomeAtributo", "nome", "label", "campo", "descricao"))
        )
        if name in normalized_names:
            return _first_present(attribute, ("valorAtributo", "valor", "value", "conteudo"))
    return None


def _normalize_attribute_name(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = text.replace(":", "")
    text = re.sub(r"\s+", " ", text)
    return text


def _first_present(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def _first_present_nested(payload: dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> Any:
    for path in paths:
        current: Any = payload
        for part in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(part)
        if current not in (None, ""):
            return current
    return None


def _has_non_operational_fields(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_non_operational_key(str(key)):
                return True
            if _has_non_operational_fields(item):
                return True
    if isinstance(value, list):
        return any(_has_non_operational_fields(item) for item in value)
    return False


def _is_non_operational_key(key: str) -> bool:
    normalized = key.lower()
    normalized = normalized.replace("ç", "c").replace("á", "a").replace("ã", "a").replace("é", "e").replace("í", "i")
    blocked = (
        "valor",
        "preco",
        "price",
        "amount",
        "subtotal",
        "desconto",
        "discount",
        "acrescimo",
        "frete",
        "seguro",
        "pagamento",
        "parcela",
        "contabancaria",
        "nfes",
        "nfe",
        "imposto",
        "icms",
        "ipi",
        "difal",
        "pis",
        "cofins",
        "comissao",
        "margem",
        "custo",
        "fisco",
    )
    if "peso" in normalized or "weight" in normalized:
        return False
    return any(token in normalized for token in blocked)


def _product_weight_warning_message(code: str) -> str:
    return {
        WARNING_PRODUCT_WEIGHT_MISSING: "Produto consultado, mas o Nomus nao retornou peso unitario.",
        WARNING_PRODUCT_LOOKUP_FAILED: "Nao foi possivel consultar o peso deste produto no Nomus.",
        WARNING_PRODUCT_RESPONSE_INVALID: "A resposta do produto Nomus nao pode ser validada.",
        WARNING_PRODUCT_WEIGHT_INVALID: "O peso unitario do produto retornado pelo Nomus e invalido.",
        WARNING_PRODUCT_GROSS_WEIGHT_USED: "Peso liquido nao informado. Foi utilizado o peso bruto unitario.",
        WARNING_PRODUCT_QUANTITY_INVALID: "Quantidade ausente ou invalida; nao foi possivel calcular o peso do item.",
    }.get(code, "Peso do produto precisa de conferencia.")


def _weight_source_summary(items: list[NomusApiOrderItem]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for item in items:
        source = item.weight_source or "missing"
        summary[source] = summary.get(source, 0) + 1
    return summary
