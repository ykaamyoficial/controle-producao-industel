from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from .schemas import (
    ProposalImportField,
    ProposalImportItem,
    ProposalImportResult,
    ProposalImportWarning,
)


FORBIDDEN_FINANCIAL_TERMS = (
    "R$",
    "PRECO UNITARIO",
    "PREÇO UNITÁRIO",
    "VALOR",
    "SUB-TOTAL",
    "SUBTOTAL",
    "TOTAL",
    "ICMS",
    "IPI",
    "DIFAL",
    "FRETE",
    "CONDICAO DE PAGAMENTO",
    "CONDIÇÃO DE PAGAMENTO",
)

_BUDGET_RE = re.compile(r"\bOR.?AMENTO\s*:\s*(ETCP\s*\d+)\b", re.IGNORECASE)
_PROPOSAL_RE = re.compile(r"\bPROPOSTA\s*:\s*(CP\s*\d+)\b", re.IGNORECASE)
_DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
_SITE_RE = re.compile(r"(?:DADOS\s+DA\s+OBRA|OBRA/SITE)\s*:\s*(.+)", re.IGNORECASE)
_DEADLINE_RE = re.compile(r"\b(\d+)\s+DIAS?\b", re.IGNORECASE)
_VALIDITY_RE = re.compile(r"\bVALIDADE(?:\s+DO\s+OR.?AMENTO|\s+DA\s+PROPOSTA)?\s*:?\s*(.+)", re.IGNORECASE)
_DOC_RE = re.compile(r"\b(?:CNPJ|CPF|CNPJ/CPF)\s*:?\s*([0-9./-]{11,18})\b", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\(?\d{2}\)?\s*)?\d{4,5}[-\s]?\d{4}")
_WEIGHT_RE = re.compile(r"\bPESO\s*(?:TOTAL\s*)?[:=\-]?\s*(\d+(?:[.,]\d+)?)\s*KG\b", re.IGNORECASE)
_ITEM_START_RE = re.compile(r"^(?P<number>\d{3})\s+(?P<code>\S+)\s+(?P<body>.+)$", re.IGNORECASE)
_ITEM_ROW_RE = re.compile(r"^\d{3}\s+\S+\s+.+$", re.IGNORECASE)
_PRODUCT_TITLE_RE = re.compile(r"^(?P<code>\d{3}(?:\.\w+)+)\s*-\s+(?P<title>.+)", re.IGNORECASE)
_SIMPLE_ITEM_RE = re.compile(
    r"^(?P<number>\d{3})\s+(?P<code>\S+)\s+(?P<body>.+?)\s+"
    r"(?P<unit>UNIDADE|UN|PC|PECA|PEÇA)\s+(?P<qty>\d+(?:[.,]\d+)?)\s+(?:N/A|.+)?$",
    re.IGNORECASE,
)
_NCM_QTY_RE = re.compile(r"\b(?P<ncm>\d{8})\s+(?P<qty>\d+(?:[.,]\d+)?)\b")
_MONEY_RE = re.compile(r"R\$\s*\d[\d.]*,\d{2}|\b\d{1,3}(?:\.\d{3})*,\d{2}\b")
_PERCENT_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*%")
_NULL_RE = re.compile(r"\bNULL\b", re.IGNORECASE)

_ISSUER_TERMS = (
    "INDUSTEL TELECOM",
    "INDUSTEL TELECOM LTDA",
    "ENERTEL INDUSTRIA METALURGICA",
    "ENERTEL INDUSTRIA METALURGICA LTDA",
)
_CLIENT_TRAILING_NAMES = (
    " DANIELE ",
    " PEDRO ",
    " LUANA ",
    " ISADORA ",
    " SILVIO ",
    " PATRICIA ",
)


def _field(value, confidence: float = 0.0, needs_confirmation: bool = True, source: str = "rule"):
    return ProposalImportField(value=value, confidence=confidence, needs_confirmation=needs_confirmation, source=source)


def _clean_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip(" -|\t")


def _ascii_upper(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in normalized if not unicodedata.combining(char)).upper()


def _money_free(value: str) -> str:
    cleaned = _MONEY_RE.sub("", value or "")
    cleaned = _PERCENT_RE.sub("", cleaned)
    for term in FORBIDDEN_FINANCIAL_TERMS:
        cleaned = re.sub(re.escape(term), "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(re.escape(_ascii_upper(term)), "", cleaned, flags=re.IGNORECASE)
    return _clean_space(cleaned)


def _non_financial_raw(value: str) -> str:
    parts: list[str] = []
    for token in _clean_space(value).split():
        normalized = _ascii_upper(token)
        if normalized in {"R$", "IPI", "ICMS", "DIFAL"}:
            continue
        if _MONEY_RE.fullmatch(token) or _PERCENT_RE.fullmatch(token):
            continue
        parts.append(token)
    return _money_free(" ".join(parts))


def _normalize_raw_number(raw: str | None) -> str | None:
    if not raw:
        return None
    upper = _clean_space(raw).upper()
    prefix = "ETCP" if "ETCP" in upper else "CP"
    digits = re.sub(r"\D", "", upper)
    return f"{prefix} {int(digits):05d}" if digits else None


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


def _find_date(lines: list[str]) -> str | None:
    for line in lines[:12]:
        match = _DATE_RE.search(line)
        if match:
            return match.group(1)
    return None


def _clean_client_candidate(candidate: str | None) -> str | None:
    value = _clean_space(candidate or "")
    if not value:
        return None
    normalized_initial = _ascii_upper(value)
    if normalized_initial.startswith(("CNPJ", "CPF", "CNPJ/CPF", "DADOS DA OBRA", "OBRA/SITE")):
        return None
    value = re.sub(r"\s+(?:CNPJ|CPF|CNPJ/CPF)\s*:.*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}.*$", "", value)
    normalized = f" {_ascii_upper(value)} "
    for marker in _CLIENT_TRAILING_NAMES:
        if marker in normalized:
            value = value[: normalized.index(marker)].strip()
            normalized = f" {_ascii_upper(value)} "
            break
    value = _clean_space(value).upper()
    if not value:
        return None
    if any(term == value or term in _ascii_upper(value) for term in _ISSUER_TERMS):
        return None
    return value


def _extract_client(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        if "DADOS DO CLIENTE" not in _ascii_upper(line):
            continue
        for candidate in lines[index + 1 : index + 7]:
            normalized = _ascii_upper(candidate)
            if any(stop in normalized for stop in ("DADOS DA OBRA", "OBRA/SITE", "ENDERECO", "ENDEREÇO", "TELEFONE", "COMPRADOR")):
                break
            match = re.match(r"(.+?)\s+(?:CNPJ|CPF|CNPJ/CPF)\s*:", candidate, re.IGNORECASE)
            if match:
                return _clean_client_candidate(match.group(1))
            if "CNPJ/CPF" in normalized and index + 1 < len(lines):
                previous = _clean_client_candidate(lines[index + 1])
                if previous:
                    return previous
            compact = _clean_client_candidate(candidate)
            if compact:
                return compact
        for candidate in reversed(lines[max(0, index - 5) : index]):
            normalized = _ascii_upper(candidate)
            if any(skip in normalized for skip in ("APARECIDA DE GOIANIA", "VENDEDOR", "ORCAMENTO", "PROPOSTA", "EMAIL", "TELEFONE", "COMPRADOR")):
                continue
            compact = _clean_client_candidate(candidate)
            if compact:
                return compact
    for index, line in enumerate(lines):
        if not (_BUDGET_RE.search(line) or _PROPOSAL_RE.search(line)):
            continue
        for candidate in lines[index + 1 : index + 8]:
            normalized = _ascii_upper(candidate)
            if "DADOS DO CLIENTE" in normalized:
                break
            if any(skip in normalized for skip in ("APARECIDA DE GOIANIA", "CNPJ", "CPF", "ORCAMENTO", "VENDEDOR")):
                continue
            compact = _clean_client_candidate(candidate)
            if compact:
                return compact
    return None


def _extract_site(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        match = _SITE_RE.search(line)
        if match:
            value = _clean_space(match.group(1))
            if value and not _NULL_RE.search(value):
                return value.upper()
        normalized = _ascii_upper(line)
        if any(label in normalized for label in ("DADOS DA OBRA", "OBRA/SITE")) and index + 1 < len(lines):
            candidate = _clean_space(lines[index + 1])
            if candidate and not _NULL_RE.search(candidate):
                return candidate.upper()
    return None


def _extract_after_label(lines: list[str], label: str, window: int = 3) -> str | None:
    normalized_label = _ascii_upper(label)
    for index, line in enumerate(lines):
        normalized = _ascii_upper(line)
        if normalized_label not in normalized:
            continue
        if ":" in line:
            remainder = _clean_space(line.split(":", 1)[1])
            if remainder:
                return remainder
        for candidate in lines[index + 1 : index + 1 + window]:
            candidate = _clean_space(candidate)
            if candidate:
                return candidate
    return None


def _extract_deadline(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        if "PRAZO DE ENTREGA" not in _ascii_upper(line):
            continue
        match = _DEADLINE_RE.search(line)
        if match:
            return _clean_space(match.group(0)).upper()
        date_match = _DATE_RE.search(line)
        if date_match:
            return date_match.group(1)
        if _NULL_RE.search(line):
            return None
        for candidate in lines[index + 1 : index + 5]:
            if _NULL_RE.search(candidate):
                return None
            match = _DEADLINE_RE.search(candidate)
            if match:
                return _clean_space(match.group(0)).upper()
            date_match = _DATE_RE.search(candidate)
            if date_match:
                return date_match.group(1)
    return None


def _is_item_row(line: str) -> bool:
    return bool(_ITEM_ROW_RE.match(line)) and not _PRODUCT_TITLE_RE.match(line)


def _item_blocks(section: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in section:
        if _PRODUCT_TITLE_RE.match(line):
            if current:
                blocks.append(current)
            current = [line]
            continue
        if _is_item_row(line) and current and any(_is_item_row(part) for part in current):
            blocks.append(current)
            current = [line]
            continue
        if current:
            current.append(line)
        elif _is_item_row(line):
            current = [line]
    if current:
        blocks.append(current)
    return blocks


def _extract_items(lines: list[str]) -> list[ProposalImportItem]:
    return _extract_budget_items(lines) or _extract_simple_order_items(lines)


def _extract_budget_items(lines: list[str]) -> list[ProposalImportItem]:
    start = None
    end = None
    for index, line in enumerate(lines):
        normalized = _ascii_upper(line)
        if start is None and "DESCRICAO DO PRODUTO" in normalized and "QTD" in normalized:
            start = index + 1
            continue
        if start is not None and any(term in normalized for term in ("TOTAL", "CONDICAO DE PAGAMENTO", "CONDIÇÃO DE PAGAMENTO", "OBSERVACOES")):
            end = index
            break
    section = lines[start:end] if start is not None else []
    items: list[ProposalImportItem] = []
    for block in _item_blocks(section):
        item_index = next((index for index, line in enumerate(block) if _is_item_row(line)), None)
        if item_index is None:
            continue
        raw_block = _clean_space(" ".join(block))
        first_match = _ITEM_START_RE.match(block[item_index])
        if not first_match:
            continue
        item_number = int(first_match.group("number"))
        product_code = first_match.group("code")
        title_match = _PRODUCT_TITLE_RE.match(block[0]) if block else None
        if product_code.upper() == "N/A" and title_match:
            product_code = title_match.group("code")
        body = _clean_space(" ".join(block[:item_index] + [first_match.group("body")] + block[item_index + 1 :]))
        ncm_match = _NCM_QTY_RE.search(body)
        ncm = ncm_match.group("ncm") if ncm_match else None
        quantity: int | None = None
        if ncm_match:
            quantity_raw = ncm_match.group("qty").replace(",", ".")
            quantity = int(float(quantity_raw))
            description = body[: ncm_match.start()]
        else:
            description = body
        weight_match = _WEIGHT_RE.search(body)
        weight = float(weight_match.group(1).replace(".", "").replace(",", ".")) if weight_match else None
        description = _WEIGHT_RE.sub("", description)
        description = _money_free(description)
        description = re.sub(r"^\d{3}(?:\.\w+)+\s*-\s*", "", description)
        if not description:
            description = f"Item {item_number:03d}"
        items.append(
            ProposalImportItem(
                item_number=item_number,
                product_code=product_code if product_code.upper() != "N/A" else None,
                description=description.upper(),
                unit=None,
                quantity=quantity,
                ncm=ncm,
                weight_kg=weight,
                weight_extracted_from_text=weight is not None,
                weight_needs_confirmation=weight is None,
                raw_text=_non_financial_raw(raw_block),
                confidence=0.86 if ncm and quantity is not None else 0.55,
                weight_confidence=0.95 if weight is not None else 0.0,
                needs_confirmation=quantity is None or weight is None,
            )
        )
    return items


def _extract_simple_order_items(lines: list[str]) -> list[ProposalImportItem]:
    start = None
    end = None
    for index, line in enumerate(lines):
        normalized = _ascii_upper(line)
        if start is None and "ITEM PRODUTO" in normalized and "QTDE" in normalized:
            start = index + 1
            continue
        if start is not None and any(term in normalized for term in ("PRAZO DE ENTREGA", "TERMO DE CONFERENCIA", "TERMO DE CONFERÊNCIA", "TOTAL")):
            end = index
            break
    section = lines[start:end] if start is not None else []
    items: list[ProposalImportItem] = []
    pending_description: list[str] = []
    for line in section:
        match = _SIMPLE_ITEM_RE.match(line)
        if not match:
            pending_description.append(line)
            continue
        item_number = int(match.group("number"))
        product_code = match.group("code")
        body = _clean_space(" ".join(pending_description + [match.group("body")]))
        pending_description = []
        weight_match = _WEIGHT_RE.search(body)
        weight = float(weight_match.group(1).replace(".", "").replace(",", ".")) if weight_match else None
        body = _WEIGHT_RE.sub("", body)
        description = _money_free(body) or f"Item {item_number:03d}"
        unit = _clean_space(match.group("unit")).upper()
        quantity = int(float(match.group("qty").replace(",", ".")))
        items.append(
            ProposalImportItem(
                item_number=item_number,
                product_code=product_code if product_code.upper() != "N/A" else None,
                description=description.upper(),
                unit=unit,
                quantity=quantity,
                ncm=None,
                weight_kg=weight,
                weight_extracted_from_text=weight is not None,
                weight_needs_confirmation=weight is None,
                raw_text=_non_financial_raw(" ".join([description, unit, str(quantity)])),
                confidence=0.82 if quantity else 0.55,
                weight_confidence=0.95 if weight is not None else 0.0,
                needs_confirmation=weight is None,
            )
        )
    return items


def _warnings(result_fields: dict[str, ProposalImportField], items: list[ProposalImportItem]) -> list[ProposalImportWarning]:
    warnings: list[ProposalImportWarning] = []
    for key, label in {
        "proposal_number": "Numero da proposta",
        "client": "Cliente",
        "site": "Obra/Site",
        "proposal_date": "Data do orcamento",
    }.items():
        if not result_fields[key].value:
            warnings.append(ProposalImportWarning(key, f"{label} nao identificado; precisa confirmacao."))
    if not items:
        warnings.append(ProposalImportWarning("items", "Nenhum item operacional foi identificado."))
    if any(item.weight_needs_confirmation for item in items):
        warnings.append(ProposalImportWarning("item_weight", "Existem itens sem peso explicitamente informado em kg."))
    if result_fields["delivery_deadline_raw"].value is None:
        warnings.append(ProposalImportWarning("deadline_missing", "Prazo nao identificado; precisa confirmacao."))
    elif result_fields["delivery_deadline_days"].value is not None:
        warnings.append(ProposalImportWarning("deadline", "Prazo relativo precisa de confirmacao humana."))
    return warnings


def parse_nomus_text(text: str) -> ProposalImportResult:
    lines = [_clean_space(line) for line in (text or "").splitlines() if _clean_space(line)]
    budget_match = _BUDGET_RE.search(text or "")
    proposal_match = _PROPOSAL_RE.search(text or "")
    raw_budget = _normalize_raw_number(
        budget_match.group(1) if budget_match else (proposal_match.group(1) if proposal_match else None)
    )
    proposal_number = _proposal_number(raw_budget)
    raw_date = _find_date(lines)
    deadline_raw = _extract_deadline(lines)
    deadline_match = _DEADLINE_RE.search(deadline_raw or "")
    validity_raw = _extract_after_label(lines, "VALIDADE") or ""
    validity_match = _VALIDITY_RE.search("\n".join(lines))
    client = _extract_client(lines)
    site = _extract_site(lines)
    buyer = _extract_after_label(lines, "COMPRADOR")
    email_match = _EMAIL_RE.search(text or "")
    phone_match = _PHONE_RE.search(text or "")
    doc_match = _DOC_RE.search(text or "")
    notes = _extract_after_label(lines, "OBSERVACOES OPERACIONAIS") or _extract_after_label(lines, "OBSERVAÇÕES OPERACIONAIS")
    items = _extract_items(lines)
    fields = {
        "proposal_number": _field(proposal_number, 0.96 if proposal_number else 0.0, proposal_number is None),
        "raw_budget_number": _field(raw_budget, 0.96 if raw_budget else 0.0, raw_budget is None),
        "proposal_date": _field(_iso_date(raw_date), 0.9 if raw_date else 0.0, raw_date is None),
        "client": _field(client, 0.88 if client else 0.0, client is None),
        "client_document": _field(doc_match.group(1) if doc_match else None, 0.65 if doc_match else 0.0, doc_match is None),
        "buyer_name": _field(_money_free(buyer or "") or None, 0.65 if buyer else 0.0, buyer is None),
        "buyer_email": _field(email_match.group(0) if email_match else None, 0.8 if email_match else 0.0, email_match is None),
        "buyer_phone": _field(phone_match.group(0) if phone_match else None, 0.55 if phone_match else 0.0, phone_match is None),
        "site": _field(site, 0.95 if site else 0.0, site is None),
        "delivery_deadline_days": _field(int(deadline_match.group(1)) if deadline_match else None, 0.93 if deadline_match else 0.0, True),
        "delivery_deadline_raw": _field(_clean_space(deadline_raw).upper() if deadline_raw else None, 0.93 if deadline_raw else 0.0, True),
        "budget_validity": _field(_money_free(validity_match.group(1)).upper() if validity_match else (_money_free(validity_raw) or None), 0.7 if validity_match or validity_raw else 0.0, not bool(validity_match or validity_raw)),
        "operational_notes": _field(_money_free(notes or "") or None, 0.55 if notes else 0.0, False),
    }
    return ProposalImportResult(
        source="nomus_pdf_hybrid",
        proposal_number=fields["proposal_number"],
        raw_budget_number=fields["raw_budget_number"],
        proposal_date=fields["proposal_date"],
        client=fields["client"],
        client_document=fields["client_document"],
        buyer_name=fields["buyer_name"],
        buyer_email=fields["buyer_email"],
        buyer_phone=fields["buyer_phone"],
        site=fields["site"],
        delivery_deadline_days=fields["delivery_deadline_days"],
        delivery_deadline_raw=fields["delivery_deadline_raw"],
        budget_validity=fields["budget_validity"],
        operational_notes=fields["operational_notes"],
        items=items,
        warnings=_warnings(fields, items),
        requires_human_review=True,
    )
