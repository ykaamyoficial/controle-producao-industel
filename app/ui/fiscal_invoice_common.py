"""Textos e mensagens compartilhados pelas telas de cancelamento/correcao de NF."""

from __future__ import annotations

from app.models.fiscal_table_model import format_weight
from app.ui.numeric_utils import format_decimal

_FISCAL_ERROR_MESSAGES = {
    "FISCAL_QUANTITY_EXCEEDED": "O saldo fiscal deste item foi alterado. Atualize os dados e revise a emissão.",
    "FISCAL_ITEM_INVALID": "Um item fiscal ficou indisponível ou inválido. Atualize os dados e revise a emissão.",
    "FISCAL_INVOICE_DUPLICATED": "Já existe outra nota fiscal ativa com este número e série. O número só é liberado quando a nota é cancelada.",
    "FISCAL_INVOICE_NOT_FOUND": "A nota fiscal não foi encontrada. Atualize a lista e tente novamente.",
    "FISCAL_INVOICE_ALREADY_CANCELLED": "Esta nota fiscal já foi cancelada. Atualize a lista.",
    "FISCAL_INVOICE_WITHDRAWN": "Esta NF já foi retirada pelo cliente e não pode ser corrigida.",
    "FISCAL_INVOICE_CORRECTION_INVALID": "Selecione pelo menos um item para a nota corrigida.",
    "FISCAL_VERSION_CONFLICT": "Os dados fiscais foram alterados por outra operação. Atualize e tente novamente.",
    "FISCAL_INVALID_STATE": "Esta proposta fiscal já está concluída (NF emitida). Atualize a lista e revise a seleção.",
    "PERMISSION_DENIED": "Seu usuário não possui permissão para esta operação fiscal.",
}


def fiscal_error_message(exc: Exception, default: str = "Não foi possível concluir a operação fiscal.") -> str:
    code = str(getattr(exc, "error_code", "") or getattr(exc, "technical_message", "") or "").upper()
    return _FISCAL_ERROR_MESSAGES.get(code, str(exc) or default)


def active_lines(invoice: dict) -> list[dict]:
    """Linhas vigentes da nota. Na nota cancelada todas as linhas ficam inativas;
    a API ja omite as trocadas em correcao anterior, entao valem todas."""
    lines = invoice.get("itens") or []
    if str(invoice.get("status") or "").upper() == "CANCELADA":
        return list(lines)
    return [line for line in lines if line.get("active", True)]


def invoice_label(invoice: dict) -> str:
    parts = [f"NF {invoice.get('numero_controle') or '-'}"]
    if invoice.get("serie"):
        parts.append(f"série {invoice['serie']}")
    parts.append(str(invoice.get("data_emissao") or "-")[:10])
    count = len(active_lines(invoice)) or int(invoice.get("quantidade_itens") or 0)
    parts.append(f"{count} item(ns)")
    parts.append(f"{format_decimal(invoice.get('quantidade_emitida'))} un")
    parts.append(format_weight(invoice.get("peso_emitido")))
    return " · ".join(parts)


def items_summary(invoice: dict) -> str:
    """"1: 10, 2: 5" - item e quantidade de cada linha da nota."""
    return ", ".join(
        f"{line.get('item_number') or '-'}: {format_decimal(line.get('quantity'))}" for line in active_lines(invoice)
    ) or "-"
