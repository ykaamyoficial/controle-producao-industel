from __future__ import annotations

from decimal import Decimal

from .schemas import ProposalImportIssue, StandardProposalImportResult


_HEADER_TOKENS = (
    "DESCRICAO DO PRODUTO",
    "DESCRIÇÃO DO PRODUTO",
    "PRECO UNITARIO",
    "PREÇO UNITÁRIO",
    "SUBTOTAL",
    "VALOR",
)


def validate_standard_result(result: StandardProposalImportResult) -> tuple[list[ProposalImportIssue], list[ProposalImportIssue]]:
    warnings: list[ProposalImportIssue] = []
    errors: list[ProposalImportIssue] = []

    if not result.proposal.proposal_number:
        errors.append(_issue("proposal_number", "missing_proposal", "Numero da proposta nao identificado.", "error"))
    if not result.proposal.client:
        errors.append(_issue("client", "missing_client", "Cliente nao identificado.", "error"))
    if not result.proposal.site:
        warnings.append(_issue("site", "missing_site", "Obra/Site precisa confirmacao."))
    if result.proposal.deadline_days is not None and result.proposal.deadline_days < 0:
        errors.append(_issue("deadline_days", "invalid_deadline", "Prazo nao pode ser negativo.", "error"))
    if not result.items:
        errors.append(_issue("items", "missing_items", "Nenhum item operacional foi identificado.", "error"))

    seen_numbers: set[int] = set()
    for index, item in enumerate(result.items):
        item_label = f"item {item.item_number or index + 1}"
        if item.item_number in seen_numbers:
            warnings.append(_issue("item_number", "duplicate_item_number", f"Numero duplicado no {item_label}.", item_index=index))
        if item.item_number is not None:
            seen_numbers.add(item.item_number)
        if not item.description:
            errors.append(_issue("description", "missing_description", f"Descricao ausente no {item_label}.", "error", index))
        elif any(token in item.description.upper() for token in _HEADER_TOKENS):
            warnings.append(_issue("description", "header_like_description", f"Descricao do {item_label} parece cabecalho e precisa revisao.", item_index=index))
        if item.quantity is None or item.quantity <= 0:
            errors.append(_issue("quantity", "invalid_quantity", f"Quantidade invalida no {item_label}.", "error", index))
        if _is_negative(item.unit_weight) or _is_negative(item.total_weight):
            errors.append(_issue("weight", "invalid_weight", f"Peso negativo no {item_label}.", "error", index))
        if item.total_weight is None and item.unit_weight is None:
            warnings.append(_issue("weight", "missing_weight", f"Peso ausente no {item_label}.", item_index=index))

    return warnings, errors


def _issue(
    field_name: str,
    code: str,
    message: str,
    severity: str = "warning",
    item_index: int | None = None,
) -> ProposalImportIssue:
    return ProposalImportIssue(
        field_name=field_name,
        code=code,
        message=message,
        severity=severity,
        item_index=item_index,
    )


def _is_negative(value: Decimal | None) -> bool:
    return value is not None and value < 0
