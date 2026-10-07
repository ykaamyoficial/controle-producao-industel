"""Helpers de formatacao de texto puramente apresentacionais, compartilhados
entre a tabela principal de propostas e o dialogo de Detalhes - nenhuma
funcao aqui calcula status/regra de negocio, apenas garante que um valor ja
vindo do backend nunca aparece cru (None/""/0 quando o correto e "ausente")
e que a identificacao "CP xxxxx" e montada de um so jeito no projeto todo.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.ui.numeric_utils import format_decimal, parse_decimal

EMPTY_PLACEHOLDER = "-"

# Titulos de cartao que o servico manda sem acento. A chave de dados continua
# a mesma; so o texto mostrado ganha acento.
_ACCENTED_LABELS = {
    "propostas em producao": "Propostas em produção",
    "producao completa": "Produção completa",
    "producao parcial": "Produção parcial",
    "producao concluida": "Produção concluída",
    "producao em andamento": "Produção em andamento",
    "em separacao": "Em separação",
    "peso enviado galvanizacao": "Peso enviado galvanização",
    "peso retornado galvanizacao": "Peso retornado galvanização",
    "pendencias criticas": "Pendências críticas",
    "pendencias de remanejamento": "Pendências de remanejamento",
    "expedicoes concluidas": "Expedições concluídas",
    "+7 dias sem emissao": "+7 dias sem emissão",
    "producao": "Produção",
    "galvanizacao": "Galvanização",
    "expedicao": "Expedição",
}

_RELIABILITY = {"alta": "Alta", "media": "Média", "baixa": "Baixa"}


def reliability_label(value: Any) -> str:
    """"media" -> "Média"; valor ausente vira "-"."""
    raw = str(value or "").strip()
    return _RELIABILITY.get(raw.lower(), raw.title()) if raw else "-"


def accent_label(text: Any) -> str:
    """Devolve o titulo com acentuacao correta quando ele e um dos conhecidos."""
    raw = str(text or "")
    return _ACCENTED_LABELS.get(raw.strip().lower(), raw)


def format_empty(value: Any, default: str = EMPTY_PLACEHOLDER) -> str:
    """Nunca deixa None/""/{}/[] aparecerem crus numa tela - troca por um
    placeholder consistente. Valores validos (incluindo 0) passam direto."""
    if value is None:
        return default
    if isinstance(value, (str, list, tuple, dict, set)) and len(value) == 0:
        return default
    text = str(value).strip()
    return text if text else default


def format_proposal_label(value: Any) -> str:
    """Texto de identificacao operacional de uma proposta (ex.: "CP 05389").

    O numero ja vem formatado do backend (campo `proposta` = `proposal_number`
    da API) - esta funcao so garante o mesmo fallback em toda a UI, para nao
    reescrever `valor or "-"` em varios lugares diferentes."""
    return format_empty(value)


def format_proposal_header(proposal_labels: Iterable[Any], cliente: Any) -> str:
    """Monta o texto do cabecalho padrao "CP xxxxx | Cliente" (ou "CP xxxxx,
    CP yyyyy | Cliente" quando ha propostas agrupadas/parciais reunidas na
    mesma tela) - usado tanto no cabecalho fixo de Detalhes quanto em
    qualquer outro lugar que precise do mesmo formato, para nao duplicar essa
    montagem."""
    labels = [format_proposal_label(label) for label in proposal_labels]
    labels = [label for label in labels if label and label != EMPTY_PLACEHOLDER]
    proposals_text = ", ".join(dict.fromkeys(labels)) or EMPTY_PLACEHOLDER
    client_text = format_empty(cliente)
    return f"{proposals_text} | {client_text}"


def format_weight_or_missing(value: Any, *, suffix: str = " kg") -> str:
    """Peso ausente exibe "Não informado", nunca "0" - a mesma regra em todo
    lugar que mostra peso (Resumo, Fluxo, Itens)."""
    if value in (None, ""):
        return "Não informado"
    quantity = parse_decimal(value, "0")
    if quantity <= 0:
        return "Não informado"
    return f"{format_decimal(quantity)}{suffix}"


def format_quantity(value: Any) -> str:
    if value in (None, ""):
        return EMPTY_PLACEHOLDER
    return format_decimal(value)
