from __future__ import annotations

from dataclasses import dataclass, field

# Ordem de severidade (indice = peso). Usada para comparar com o minimo
# de e-mail configurado por usuario e para decidir o que fura horario de
# silencio (`critica` sempre fura).
SEVERITY_ORDER: list[str] = ["info", "normal", "alta", "critica"]

CHANNELS: list[str] = ["in_app", "tray", "email"]


def severity_rank(severity: str) -> int:
    try:
        return SEVERITY_ORDER.index(severity)
    except ValueError:
        return SEVERITY_ORDER.index("normal")


@dataclass(frozen=True)
class CategoryDefault:
    code: str
    label: str
    default_channels: tuple[str, ...] = ("in_app", "tray")
    default_severity: str = "normal"
    # severidade minima (inclusive) para o canal e-mail quando o usuario
    # nao tem preferencia propria configurada.
    default_min_severity_email: str = "alta"


# Catalogo oficial de categorias. `chat/service.py` mapeia seus
# notification_type para as CHAT_*; os emissores de negocio (Fase 4) usam
# as demais.
CATEGORY_DEFAULTS: dict[str, CategoryDefault] = {
    c.code: c
    for c in [
        # Ruido de chat: nunca por e-mail por padrao (in_app + bandeja so).
        CategoryDefault("CHAT_MENSAGEM", "Chat — mensagens", default_severity="info", default_min_severity_email="critica"),
        CategoryDefault("CHAT_MENCAO", "Chat — mencoes"),
        CategoryDefault("CHAT_RESPOSTA", "Chat — respostas"),
        CategoryDefault("CHAT_NOTA", "Chat — notas internas"),
        # Pendencia real atribuida a voce: e-mail ligado por padrao.
        CategoryDefault("CHAT_PERGUNTA", "Chat — perguntas atribuidas a voce", default_channels=("in_app", "tray", "email"), default_severity="alta", default_min_severity_email="alta"),
        CategoryDefault("CHAT_PERGUNTA_ATRASADA", "Chat — perguntas atrasadas", default_channels=("in_app", "tray", "email"), default_severity="critica", default_min_severity_email="alta"),
        # Eventos de negocio: e-mail ligado por padrao, so severidade alta/critica dispara na hora.
        CategoryDefault("PROPOSTA_STATUS", "Propostas — mudanca de status", default_channels=("in_app", "tray", "email")),
        CategoryDefault("PRODUCAO_LOTE", "Producao — lotes", default_channels=("in_app", "tray", "email")),
        CategoryDefault("GALVANIZACAO_LOTE", "Galvanizacao — lotes", default_channels=("in_app", "tray", "email")),
        CategoryDefault("ALMOXARIFADO", "Almoxarifado — pendencias", default_channels=("in_app", "tray", "email")),
        CategoryDefault("NOMUS_IMPORTACAO", "Nomus — resultado de importacao", default_channels=("in_app", "tray", "email"), default_min_severity_email="alta"),
        CategoryDefault("EXPEDICAO", "Expedicao — entregas", default_channels=("in_app", "tray", "email")),
        CategoryDefault("SISTEMA", "Sistema — avisos gerais", default_channels=("in_app", "tray", "email"), default_severity="alta"),
    ]
}


def category_default(code: str) -> CategoryDefault:
    return CATEGORY_DEFAULTS.get(code) or CategoryDefault(code, code)
