import hashlib
import hmac
import json
import math
import os
import shutil
import socket
import sqlite3
import sys
import textwrap
import traceback
import unicodedata
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape


APP_NAME = "Controle de Producao Industel"
APP_VERSION = "1.0.0"
BASE_DIR = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
CONFIG_FILE = BASE_DIR / "controle_producao_config.json"
DEFAULT_DB_FILE = BASE_DIR / "controle_producao.db"
DEFAULT_BACKUP_DIR = BASE_DIR / "backups_controle_producao"
DATE_FMT = "%d/%m/%Y"
DATETIME_FMT = "%d/%m/%Y %H:%M:%S"
FONT_FAMILY = "Arial"


COLOR_PALETTES = {
    "aurora": {
        "label": "Aurora profissional",
        "bg": "#f5f7fb",
        "surface": "#ffffff",
        "surface_alt": "#e8f1ff",
        "text": "#0f172a",
        "muted": "#475569",
        "border": "#cbd5e1",
        "accent": "#006fc9",
        "accent_hover": "#005aa3",
        "accent_text": "#ffffff",
        "secondary": "#be123c",
        "success": "#047857",
        "warning": "#b45309",
        "danger": "#b91c1c",
        "area_control": "#006fc9",
        "area_production": "#047857",
        "area_galvanization": "#7c3aed",
        "area_expedition": "#c2410c",
        "area_stock": "#64748b",
        "tree_selected": "#bfdbfe",
        "tree_heading": "#dbeafe",
    },
    "grafite": {
        "label": "Grafite alto contraste",
        "bg": "#0f172a",
        "surface": "#172033",
        "surface_alt": "#24324a",
        "text": "#f8fafc",
        "muted": "#cbd5e1",
        "border": "#475569",
        "accent": "#38bdf8",
        "accent_hover": "#7dd3fc",
        "accent_text": "#0f172a",
        "secondary": "#fb923c",
        "success": "#34d399",
        "warning": "#facc15",
        "danger": "#fb7185",
        "area_control": "#38bdf8",
        "area_production": "#34d399",
        "area_galvanization": "#a78bfa",
        "area_expedition": "#fb923c",
        "area_stock": "#94a3b8",
        "tree_selected": "#0e7490",
        "tree_heading": "#1e293b",
    },
    "energia": {
        "label": "Verde operacional",
        "bg": "#f5fbf7",
        "surface": "#ffffff",
        "surface_alt": "#e5f7ec",
        "text": "#10251b",
        "muted": "#3f5f50",
        "border": "#b7d7c4",
        "accent": "#047857",
        "accent_hover": "#065f46",
        "accent_text": "#ffffff",
        "secondary": "#1d4ed8",
        "success": "#16a34a",
        "warning": "#b45309",
        "danger": "#b91c1c",
        "area_control": "#047857",
        "area_production": "#16a34a",
        "area_galvanization": "#7c3aed",
        "area_expedition": "#c2410c",
        "area_stock": "#3f5f50",
        "tree_selected": "#bbf7d0",
        "tree_heading": "#dcfce7",
    },
    "pulso": {
        "label": "Pulso executivo",
        "bg": "#fbf7ff",
        "surface": "#ffffff",
        "surface_alt": "#f1e5ff",
        "text": "#241332",
        "muted": "#5b476a",
        "border": "#d8b4fe",
        "accent": "#9d174d",
        "accent_hover": "#831843",
        "accent_text": "#ffffff",
        "secondary": "#0369a1",
        "success": "#0f9f6e",
        "warning": "#b45309",
        "danger": "#be123c",
        "area_control": "#9d174d",
        "area_production": "#0f9f6e",
        "area_galvanization": "#7c3aed",
        "area_expedition": "#c2410c",
        "area_stock": "#5b476a",
        "tree_selected": "#f5d0fe",
        "tree_heading": "#fae8ff",
    },
}


AREAS = {
    "CONTROLE GERAL": {
        "column": "status_geral",
        "date_columns": {},
        "observation_column": "observacoes_gerais",
    },
    "PRODUCAO": {
        "column": "status_producao",
        "date_columns": {"FINALIZADO": "data_final_producao", "FINALIZADO_PARCIAL": "data_final_producao"},
        "observation_column": "observacoes_producao",
    },
    "GALVANIZACAO": {
        "column": "status_galvanizacao",
        "date_columns": {
            "ENVIADO_GALVANIZACAO": "data_envio_galv",
            "RETORNOU_GALVANIZACAO": "data_retorno_galv",
            "RETORNOU_GALVANIZACAO_PARCIAL": "data_retorno_galv",
            "RETORNOU_PARCIAL": "data_retorno_galv",
        },
        "observation_column": "observacoes_galvanizacao",
    },
    "EXPEDICAO": {
        "column": "status_expedicao",
        "date_columns": {
            "EM_SEPARACAO": "data_separacao",
            "AGUARDANDO_SEPARACAO_PARCIAL": "data_separacao",
            "SEPARADO": "data_separacao",
            "ENTREGUE": "data_retirada",
            "ENTREGUE_PARCIAL": "data_retirada",
        },
        "observation_column": "observacoes_expedicao",
    },
    "ALMOXARIFADO": {
        "column": "status_almoxarifado",
        "date_columns": {
            "SEPARADO": "data_separacao",
            "ALMOXARIFADO_ENTREGUE": "data_retirada",
            "ALMOXARIFADO_ENTREGUE_PARCIAL": "data_retirada",
            "SEM_PARAFUSOS": "data_retirada",
        },
        "observation_column": "observacoes_almoxarifado",
    },
}


STATUS_OPTIONS = [
    ("CONTROLE GERAL", "NAO_LIBERADO", "CONTROLE GERAL", "CONTROLE GERAL", 10),
    ("CONTROLE GERAL", "LIBERADO_PRODUCAO", "CONTROLE GERAL", "PRODUCAO", 20),
    ("CONTROLE GERAL", "CANCELADA", "CONTROLE GERAL", "FINALIZADO", 30),
    ("PRODUCAO", "NAO_INICIADO", "PRODUCAO", "PRODUCAO", 10),
    ("PRODUCAO", "ITEM_PENDENTE_FABRICACAO", "PRODUCAO", "PRODUCAO", 15),
    ("PRODUCAO", "INICIADO", "PRODUCAO", "PRODUCAO", 20),
    ("PRODUCAO", "FINALIZADO", "PRODUCAO", "GALVANIZACAO", 30),
    ("PRODUCAO", "FINALIZADO_PARCIAL", "PRODUCAO", "GALVANIZACAO", 40),
    ("PRODUCAO", "PARADO", "PRODUCAO", "PRODUCAO", 50),
    ("GALVANIZACAO", "AGUARDANDO_ENVIO", "GALVANIZACAO", "GALVANIZACAO", 10),
    ("GALVANIZACAO", "DISPONIVEL_PARCIAL", "GALVANIZACAO", "GALVANIZACAO", 15),
    ("GALVANIZACAO", "EM_CARGA", "GALVANIZACAO", "GALVANIZACAO", 20),
    ("GALVANIZACAO", "ENVIADO_GALVANIZACAO", "GALVANIZACAO", "GALVANIZACAO", 30),
    ("GALVANIZACAO", "RETORNOU_GALVANIZACAO", "GALVANIZACAO", "EXPEDICAO", 40),
    ("EXPEDICAO", "EM_SEPARACAO", "EXPEDICAO", "EXPEDICAO", 10),
    ("EXPEDICAO", "AGUARDANDO_SEPARACAO_PARCIAL", "EXPEDICAO", "EXPEDICAO", 15),
    ("EXPEDICAO", "SEPARACAO_INICIADA", "EXPEDICAO", "EXPEDICAO", 18),
    ("EXPEDICAO", "SEPARADO", "EXPEDICAO", "EXPEDICAO", 20),
    ("EXPEDICAO", "ENTREGUE_PARCIAL", "EXPEDICAO", "EXPEDICAO", 30),
    ("EXPEDICAO", "ENTREGUE", "EXPEDICAO", "FINALIZADO", 40),
    ("ALMOXARIFADO", "AGUARDANDO_CONFIRMACAO", "ALMOXARIFADO", "ALMOXARIFADO", 10),
    ("ALMOXARIFADO", "EM_SEPARACAO", "ALMOXARIFADO", "ALMOXARIFADO", 20),
    ("ALMOXARIFADO", "SEM_PARAFUSOS", "ALMOXARIFADO", "ALMOXARIFADO_FINALIZADO", 30),
    ("ALMOXARIFADO", "SEPARADO", "ALMOXARIFADO", "ALMOXARIFADO", 40),
    ("ALMOXARIFADO", "ALMOXARIFADO_ENTREGUE", "ALMOXARIFADO", "ALMOXARIFADO_FINALIZADO", 50),
    ("ALMOXARIFADO", "ALMOXARIFADO_ENTREGUE_PARCIAL", "ALMOXARIFADO", "ALMOXARIFADO", 60),
]

CLOSED_PRODUCTION_STATUS = {"FINALIZADO"}
CLOSED_GALVANIZATION_STATUS = {"RETORNOU_GALVANIZACAO"}
EXPEDITION_FINISHED_STATUS = {"ENTREGUE"}

STATUS_FLOW_ORDER = {
    "CONTROLE GERAL": ["NAO_LIBERADO", "LIBERADO_PRODUCAO", "CANCELADA"],
    "PRODUCAO": ["NAO_INICIADO", "ITEM_PENDENTE_FABRICACAO", "INICIADO", "PARADO", "FINALIZADO_PARCIAL", "FINALIZADO"],
    "GALVANIZACAO": ["AGUARDANDO_ENVIO", "DISPONIVEL_PARCIAL", "EM_CARGA", "ENVIADO_GALVANIZACAO", "RETORNOU_GALVANIZACAO"],
    "EXPEDICAO": ["EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARACAO_INICIADA", "SEPARADO", "ENTREGUE_PARCIAL", "ENTREGUE"],
    "ALMOXARIFADO": ["AGUARDANDO_CONFIRMACAO", "EM_SEPARACAO", "SEM_PARAFUSOS", "SEPARADO", "ALMOXARIFADO_ENTREGUE", "ALMOXARIFADO_ENTREGUE_PARCIAL"],
}

LEGACY_STATUS_RENAMES = {
    "AGUADANDO_ENVIO": "AGUARDANDO_ENVIO",
    "GALVANIZADO": "ENVIADO_GALVANIZACAO",
}

LOAD_STATUS_LABELS = {
    "AGUARDANDO_LIBERACAO": "Aguardando liberacao",
    "LIBERADA_PARA_ENVIO": "Liberada para envio",
    "RETORNADA_GALVANIZACAO": "Retornada da galvanizacao",
}

EXPORT_LABELS = {
    "id": "ID",
    "cliente": "Cliente",
    "proposta": "Proposta",
    "pedido_compra": "OC/Pedido",
    "obra_site": "Obra/Site",
    "peso": "Peso",
    "lote": "Lote",
    "data_entrada": "Entrada",
    "data_cadastro": "Cadastro",
    "prazo_entrega": "Prazo",
    "status_geral": "Status Geral",
    "status_producao": "Status Producao",
    "status_galvanizacao": "Status Galvanizacao",
    "status_expedicao": "Status Expedicao",
    "status_almoxarifado": "Status Almoxarifado",
    "necessita_almoxarifado": "Necessita Almoxarifado",
    "situacao_fluxo": "Situacao do Fluxo",
    "tem_pendencia_producao": "Pendencia Producao",
    "origem_remanejamento": "Origem Remanejamento",
    "observacao_remanejamento": "Obs. Remanejamento",
    "tipo_processo": "Tipo",
    "processo_pai_id": "Processo Pai",
    "numero_parcial": "Parcial",
    "peso_parcial": "Peso Parcial",
    "saldo_pendente": "Saldo Pendente",
    "descricao_parcial": "Descricao Parcial",
    "data_final_producao": "Final Producao",
    "data_envio_galv": "Envio Galv.",
    "data_prevista_retorno_galv": "Prev. Retorno Galv.",
    "data_retorno_galv": "Retorno Galv.",
    "data_separacao": "Separacao",
    "data_retirada": "Retirada",
    "status_anterior": "Status Anterior",
    "status_novo": "Status Novo",
    "data_hora": "Data/Hora",
    "usuario": "Usuario",
    "computador": "Computador",
    "observacao": "Observacao",
    "entidade": "Modulo",
    "entidade_id": "Registro",
    "acao": "Acao",
    "campo": "Campo",
    "valor_anterior": "Antes",
    "valor_novo": "Depois",
    "total": "Total",
}

AREA_FINISHED_STATUS = {
    "CONTROLE GERAL": {"ENTREGUE", "FINALIZADO", "CANCELADA"},
    "PRODUCAO": {"FINALIZADO"},
    "GALVANIZACAO": {"RETORNOU_GALVANIZACAO"},
    "EXPEDICAO": {"ENTREGUE", "UNIFICADA_PRINCIPAL"},
    "ALMOXARIFADO": {"ALMOXARIFADO_ENTREGUE", "SEM_PARAFUSOS"},
}

PAGE_SIZE_OPTIONS = ["50", "100", "200", "500", "Todos"]

REPORT_SOURCE_OPTIONS = [
    ("ANDAMENTO", "Processos em andamento"),
    ("VENCIMENTOS", "Vencidos ou proximos"),
    ("PRODUCAO_STATUS", "Producao por status"),
    ("GALVANIZACAO", "Galvanizacao enviada/retorno"),
    ("ENTREGAS", "Entregas por cliente"),
    ("PARCIAIS", "Parciais e pendencias"),
    ("REMANEJAMENTOS", "Remanejamentos"),
    ("LISTAGEM", "Listagem filtrada"),
]

REPORT_FIELD_OPTIONS = [
    "proposta",
    "tipo_processo",
    "cliente",
    "pedido_compra",
    "obra_site",
    "lote",
    "peso",
    "peso_parcial",
    "saldo_pendente",
    "data_entrada",
    "prazo_entrega",
    "data_envio_galv",
    "data_prevista_retorno_galv",
    "data_retorno_galv",
    "data_separacao",
    "data_retirada",
    "status_geral",
    "status_producao",
    "status_galvanizacao",
    "status_expedicao",
    "status_almoxarifado",
    "necessita_almoxarifado",
    "situacao_fluxo",
    "origem_remanejamento",
    "observacao_remanejamento",
    "observacoes_gerais",
    "observacoes_producao",
    "observacoes_galvanizacao",
    "observacoes_expedicao",
    "observacoes_almoxarifado",
    "atualizado_em",
    "atualizado_por",
]

DEFAULT_REPORT_DEFINITIONS = [
    {
        "name": "Processos em andamento",
        "source": "ANDAMENTO",
        "columns": ["proposta", "cliente", "obra_site", "lote", "peso", "prazo_entrega", "status_geral", "status_producao", "status_galvanizacao", "status_expedicao", "situacao_fluxo"],
    },
    {
        "name": "Parciais e pendencias",
        "source": "PARCIAIS",
        "columns": ["proposta", "tipo_processo", "cliente", "obra_site", "peso_parcial", "saldo_pendente", "status_producao", "status_galvanizacao", "status_expedicao", "situacao_fluxo", "origem_remanejamento", "observacao_remanejamento"],
    },
    {
        "name": "Galvanizacao enviada/retorno",
        "source": "GALVANIZACAO",
        "columns": ["proposta", "cliente", "obra_site", "lote", "peso", "data_envio_galv", "data_prevista_retorno_galv", "data_retorno_galv", "status_galvanizacao", "status_expedicao"],
    },
    {
        "name": "Entregas por cliente",
        "source": "ENTREGAS",
        "columns": ["cliente", "proposta", "pedido_compra", "obra_site", "prazo_entrega", "data_retirada", "status_expedicao", "status_geral"],
    },
]

ICONS = {
    "dashboard": "â–¦",
    "general": "â—Ž",
    "production": "âš™",
    "galvanization": "â—†",
    "expedition": "â–£",
    "stock": "â–¤",
    "history": "â—·",
    "audit": "âŒ•",
    "reports": "â–§",
    "settings": "âš™",
    "new": "+",
    "search": "âŒ•",
    "clear": "Ã—",
    "load": "â‡„",
    "batch": "â˜‘",
    "early": "â†ª",
    "pdf": "â—«",
    "excel": "â–¦",
    "save": "âœ“",
    "cancel": "Ã—",
    "refresh": "â†»",
    "edit": "âœŽ",
    "delete": "âˆ’",
    "users": "â™™",
    "backup": "â¤“",
    "restore": "â¤’",
    "database": "â–£",
    "status": "â—",
}

AREA_ICONS = {
    "CONTROLE GERAL": "â—Ž",
    "PRODUCAO": "âš™",
    "GALVANIZACAO": "â—†",
    "EXPEDICAO": "â–£",
    "ALMOXARIFADO": "â–¤",
}

STATUS_ICONS = {
    "NAO_LIBERADO": "â—‹",
    "LIBERADO_PRODUCAO": "â–¶",
    "NAO_INICIADO": "â—‹",
    "ITEM_PENDENTE_FABRICACAO": "!",
    "INICIADO": "â–¶",
    "PARADO": "â– ",
    "FINALIZADO": "âœ“",
    "FINALIZADO_PARCIAL": "â—",
    "AGUARDANDO_ENVIO": "â—·",
    "DISPONIVEL_PARCIAL": "â—",
    "EM_CARGA": "â–£",
    "ENVIADO_GALVANIZACAO": "âžœ",
    "RETORNOU_GALVANIZACAO": "âœ“",
    "RETORNOU_PARCIAL": "â—",
    "EM_SEPARACAO": "â–¤",
    "AGUARDANDO_SEPARACAO_PARCIAL": "â—",
    "SEPARADO": "âœ“",
    "ENTREGUE": "âœ“",
    "ENTREGUE_PARCIAL": "â—",
    "CANCELADA": "Ã—",
    "AGUARDANDO_CONFIRMACAO": "â—‹",
    "EM_ANDAMENTO": "â–¶",
    "SEM_PARAFUSOS": "âˆ’",
    "ALMOXARIFADO_ENTREGUE": "âœ“",
    "ALMOXARIFADO_ENTREGUE_PARCIAL": "â—",
}

ICON_IMAGE_FILES = {
    "new": "acao_novo.png",
    "search": "acao_pesquisar.png",
    "clear": "acao_limpar.png",
    "save": "acao_salvar.png",
    "cancel": "acao_limpar.png",
    "edit": "acao_editar.png",
    "delete": "acao_remover.png",
    "refresh": "acao_atualizar.png",
    "load": "acao_cargas.png",
    "batch": "acao_lote.png",
    "early": "acao_entrega_remanejada.png",
    "pdf": "acao_pdf.png",
    "excel": "acao_excel.png",
    "dashboard": "area_painel.png",
    "general": "area_controle_geral.png",
    "production": "area_producao.png",
    "galvanization": "area_galvanizacao.png",
    "expedition": "area_expedicao.png",
    "stock": "area_almoxarifado.png",
    "history": "sistema_historico.png",
    "audit": "sistema_auditoria.png",
    "reports": "sistema_relatorios.png",
    "settings": "sistema_configuracoes.png",
    "users": "sistema_usuarios.png",
    "backup": "sistema_backup.png",
    "restore": "sistema_restaurar.png",
    "database": "sistema_banco_sqlite.png",
    "previous": "acao_anterior.png",
    "next": "acao_proximo.png",
    "status": "status_em_andamento.png",
    "waiting": "status_aguardando.png",
    "partial": "status_parcial.png",
    "finished": "status_finalizado.png",
    "canceled": "status_cancelado.png",
    "pending": "status_pendente.png",
}
AREA_ICON_KEYS = {
    "CONTROLE GERAL": "general",
    "PRODUCAO": "production",
    "GALVANIZACAO": "galvanization",
    "EXPEDICAO": "expedition",
    "ALMOXARIFADO": "stock",
}

STATUS_TAG_COLORS = {
    "NAO_LIBERADO": ("#fde047", "#0f172a"),
    "LIBERADO_PRODUCAO": ("#7dd3fc", "#0f172a"),
    "EM_PRODUCAO": ("#38bdf8", "#0f172a"),
    "NAO_INICIADO": ("#c4b5fd", "#0f172a"),
    "ITEM_PENDENTE_FABRICACAO": ("#f9a8d4", "#0f172a"),
    "INICIADO": ("#86efac", "#0f172a"),
    "PARADO": ("#fb7185", "#0f172a"),
    "FINALIZADO": ("#4ade80", "#0f172a"),
    "FINALIZADO_PARCIAL": ("#fdba74", "#0f172a"),
    "PRODUCAO_CANCELADA": ("#94a3b8", "#0f172a"),
    "EM_GALVANIZACAO": ("#c084fc", "#0f172a"),
    "AGUARDANDO_ENVIO": ("#facc15", "#0f172a"),
    "DISPONIVEL_PARCIAL": ("#f0abfc", "#0f172a"),
    "EM_CARGA": ("#818cf8", "#0f172a"),
    "ENVIADO_GALVANIZACAO": ("#a78bfa", "#0f172a"),
    "RETORNOU_GALVANIZACAO": ("#5eead4", "#0f172a"),
    "RETORNOU_PARCIAL": ("#fb923c", "#0f172a"),
    "EM_EXPEDICAO": ("#22d3ee", "#0f172a"),
    "EM_SEPARACAO": ("#60a5fa", "#0f172a"),
    "AGUARDANDO_SEPARACAO_PARCIAL": ("#d8b4fe", "#0f172a"),
    "SEPARACAO_INICIADA": ("#38bdf8", "#0f172a"),
    "SEPARADO": ("#34d399", "#0f172a"),
    "ENTREGUE": ("#22c55e", "#0f172a"),
    "ENTREGUE_PARCIAL": ("#f97316", "#0f172a"),
    "UNIFICADA_PRINCIPAL": ("#14b8a6", "#0f172a"),
    "CANCELADA": ("#94a3b8", "#0f172a"),
    "AGUARDANDO_CONFIRMACAO": ("#bae6fd", "#0f172a"),
    "EM_ANDAMENTO": ("#38bdf8", "#0f172a"),
    "SEM_PARAFUSOS": ("#cbd5e1", "#0f172a"),
    "ALMOXARIFADO_ENTREGUE": ("#4ade80", "#0f172a"),
    "ALMOXARIFADO_ENTREGUE_PARCIAL": ("#fbbf24", "#0f172a"),
}

STATUS_IMAGE_KEYS = {
    status: f"status_{status.lower()}"
    for status in STATUS_TAG_COLORS
}
STATUS_BADGE_IMAGE_KEYS = {
    status: f"{icon_key}_badge"
    for status, icon_key in STATUS_IMAGE_KEYS.items()
}
ICON_IMAGE_FILES.update({
    icon_key: f"{icon_key}.png"
    for icon_key in STATUS_IMAGE_KEYS.values()
})
ICON_IMAGE_FILES.update({
    icon_key: f"{icon_key}.png"
    for icon_key in STATUS_BADGE_IMAGE_KEYS.values()
})


PROCESS_COLUMNS = [
    ("id", "ID", 60),
    ("tipo_processo", "Tipo", 80),
    ("cliente", "Cliente", 150),
    ("proposta", "Proposta", 110),
    ("pedido_compra", "OC/Pedido", 110),
    ("obra_site", "Obra/Site", 140),
    ("peso", "Peso", 80),
    ("lote", "Lote", 90),
    ("data_entrada", "Entrada", 100),
    ("prazo_entrega", "Prazo", 100),
    ("status_geral", "Geral", 145),
    ("status_producao", "Producao", 145),
    ("status_galvanizacao", "Galvanizacao", 155),
    ("status_expedicao", "Expedicao", 145),
    ("status_almoxarifado", "Almoxarifado", 155),
    ("localizacao_atual", "Localizacao", 210),
]

BASE_AREA_PROCESS_COLUMNS = [
    ("id", "ID", 60),
    ("tipo_processo", "Tipo", 75),
    ("cliente", "Cliente", 170),
    ("proposta", "Proposta", 120),
    ("pedido_compra", "OC/Pedido", 120),
    ("obra_site", "Obra/Site", 160),
    ("peso", "Peso", 80),
    ("lote", "Lote", 90),
    ("data_entrada", "Entrada", 100),
    ("prazo_entrega", "Prazo", 100),
]

AREA_STATUS_LABELS = {
    "CONTROLE GERAL": "Status controle",
    "PRODUCAO": "Status producao",
    "GALVANIZACAO": "Status galvanizacao",
    "EXPEDICAO": "Status expedicao",
    "ALMOXARIFADO": "Status almoxarifado",
}

PROFILE_OPTIONS = [
    ("admin", "Administrador"),
    ("operador", "Operador geral"),
    ("controle", "Controle geral"),
    ("producao", "Producao"),
    ("galvanizacao", "Galvanizacao"),
    ("expedicao", "Expedicao"),
    ("almoxarifado", "Almoxarifado"),
    ("consulta", "Consulta"),
]

PROFILE_LABELS = dict(PROFILE_OPTIONS)

PROFILE_DEFAULT_AREAS = {
    "admin": list(AREAS.keys()),
    "controle": ["CONTROLE GERAL"],
    "producao": ["PRODUCAO"],
    "galvanizacao": ["GALVANIZACAO"],
    "expedicao": ["EXPEDICAO"],
    "almoxarifado": ["ALMOXARIFADO"],
    "consulta": [],
    "operador": list(AREAS.keys()),
}

STATUS_LABELS = {
    "": "",
    "NAO_LIBERADO": "Nao liberado",
    "LIBERADO_PRODUCAO": "Liberado para producao",
    "EM_PRODUCAO": "Em producao",
    "EM_GALVANIZACAO": "Em galvanizacao",
    "EM_EXPEDICAO": "Em expedicao",
    "ENTREGUE": "Entregue",
    "NAO_INICIADO": "Aguardando inicio",
    "ITEM_PENDENTE_FABRICACAO": "Item pendente de fabricacao",
    "INICIADO": "Em producao",
    "FINALIZADO": "Producao concluida",
    "FINALIZADO_PARCIAL": "Produzido parcialmente",
    "PRODUCAO_CANCELADA": "Producao cancelada",
    "PARADO": "Producao pausada",
    "AGUARDANDO_ENVIO": "Aguardando montagem de carga",
    "AGUADANDO_ENVIO": "Aguardando montagem de carga",
    "DISPONIVEL_PARCIAL": "Disponivel parcialmente",
    "EM_CARGA": "Em carga",
    "ENVIADO_GALVANIZACAO": "Enviado para galvanizacao",
    "RETORNOU_GALVANIZACAO": "Retornou da galvanizacao",
    "RETORNOU_PARCIAL": "Retornou parcialmente",
    "EM_SEPARACAO": "Aguardando separacao",
    "AGUARDANDO_SEPARACAO_PARCIAL": "Aguardando separacao parcial",
    "SEPARACAO_INICIADA": "Em separacao",
    "SEPARADO": "Separado para entrega",
    "ENTREGUE_PARCIAL": "Entregue parcialmente",
    "UNIFICADA_PRINCIPAL": "Parciais agrupadas",
    "CANCELADA": "Cancelada",
    "AGUARDANDO_CONFIRMACAO": "Aguardando confirmacao",
    "EM_ANDAMENTO": "Em andamento",
    "SEM_PARAFUSOS": "Sem parafusos",
    "NAO_DEFINIDO": "Nao definido",
    "SIM": "Sim",
    "NAO": "Nao",
    "ALMOXARIFADO_ENTREGUE": "Almoxarifado entregue",
    "ALMOXARIFADO_ENTREGUE_PARCIAL": "Almoxarifado entregue parcial",
    "NORMAL": "Normal",
    "PARCIAL_COM_PENDENCIA": "Parcial com pendencia",
    "PARCIAL_EM_ANDAMENTO": "Parcial em andamento",
    "PENDENTE_POR_REMANEJAMENTO": "Pendente por remanejamento",
    "UNIFICADA_NA_PRINCIPAL": "Parciais agrupadas",
    "CONCLUIDA": "Concluida",
    "CANCELADA_FLUXO": "Cancelada",
    "PRINCIPAL": "Principal",
    "PARCIAL": "Parcial",
}

AREA_STATUS_LABEL_OVERRIDES = {
    "ALMOXARIFADO": {
        "AGUARDANDO_CONFIRMACAO": "Aguardando confirmacao",
        "EM_SEPARACAO": "Em separacao",
        "SEM_PARAFUSOS": "Sem almoxarifado",
        "SEPARADO": "Separado",
        "ALMOXARIFADO_ENTREGUE_PARCIAL": "Entregue parcial",
        "ALMOXARIFADO_ENTREGUE": "Entregue",
        "EM_ANDAMENTO": "Aguardando confirmacao",
        "FINALIZADO": "Entregue",
    },
    "PRODUCAO": {
        "FINALIZADO": "Producao concluida",
        "FINALIZADO_PARCIAL": "Produzido parcialmente",
    },
    "GALVANIZACAO": {
        "RETORNOU_GALVANIZACAO": "Retornou da galvanizacao",
        "RETORNOU_PARCIAL": "Retornou parcialmente",
    },
    "EXPEDICAO": {
        "ENTREGUE": "Entregue",
        "ENTREGUE_PARCIAL": "Entregue parcial",
        "UNIFICADA_PRINCIPAL": "Unificada na principal",
    },
}


FORM_FIELDS = [
    ("cliente", "Cliente", True),
    ("proposta", "Proposta", True),
    ("pedido_compra", "Ordem de compra / pedido", False),
    ("obra_site", "Obra / site", False),
    ("peso", "Peso", False),
    ("lote", "Lote", False),
    ("data_entrada", "Data de entrada", False),
    ("prazo_entrega", "Prazo de entrega", False),
]


class AppError(Exception):
    pass


def today_br():
    return date.today().strftime(DATE_FMT)


def now_br():
    return datetime.now().strftime(DATETIME_FMT)


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def parse_date(value):
    value = (value or "").strip()
    if not value:
        return None
    for fmt in (DATE_FMT, "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise AppError(f"Data invalida: {value}. Use DD/MM/AAAA.")


def normalize_status(status):
    text = (status or "").strip().upper().replace(" ", "_").replace("-", "_")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return LEGACY_STATUS_RENAMES.get(text, text)
    replacements = {
        "Ãƒâ€¡": "C",
        "Ã‡": "C",
        "Ã§": "C",
        "Ãƒ": "A",
        "Ã": "A",
        "Ã€": "A",
        "Ã‚": "A",
        "Ãƒ": "A",
        "Ã‰": "E",
        "ÃŠ": "E",
        "Ã": "I",
        "Ã“": "O",
        "Ã”": "O",
        "Ã•": "O",
        "Ãš": "U",
        "NÃ£o": "NAO",
        "NÃƒO": "NAO",
    }
    text = (status or "").strip().upper().replace(" ", "_").replace("-", "_")
    for old, new in replacements.items():
        text = text.replace(old.upper(), new)
    return LEGACY_STATUS_RENAMES.get(text, text)


def normalize_stockroom_need(value):
    text = (value or "NAO_DEFINIDO").strip().upper().replace(" ", "_").replace("-", "_")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    aliases = {
        "S": "SIM",
        "SIM": "SIM",
        "TEM": "SIM",
        "TEM_ALMOX": "SIM",
        "TEM_ALMOXARIFADO": "SIM",
        "N": "NAO",
        "NAO": "NAO",
        "SEM": "NAO",
        "SEM_ALMOX": "NAO",
        "SEM_ALMOXARIFADO": "NAO",
        "SEM_PARAFUSOS": "NAO",
        "NAO_DEFINIDO": "NAO_DEFINIDO",
        "INDEFINIDO": "NAO_DEFINIDO",
        "": "NAO_DEFINIDO",
    }
    return aliases.get(text, "NAO_DEFINIDO")


def status_label(status):
    status = normalize_status(status)
    return STATUS_LABELS.get(status, status.replace("_", " ").title())


def area_status_label(area, status):
    status = normalize_status(status)
    return AREA_STATUS_LABEL_OVERRIDES.get(area, {}).get(status, status_label(status))


def load_status_label(status):
    status = status or ""
    return LOAD_STATUS_LABELS.get(status, status.replace("_", " ").title())


def icon_text(icon_key, text):
    icon = ICONS.get(icon_key, icon_key)
    return f"{icon} {text}" if text else icon


def icon_image(widget, icon_key):
    current = widget
    while current is not None:
        if hasattr(current, "icon_images"):
            return current.icon_images.get(icon_key)
        current = getattr(current, "master", None)
    return None


def widget_palette(widget):
    current = widget
    while current is not None:
        if hasattr(current, "config_data"):
            return COLOR_PALETTES[current.config_data.get("color_palette", "aurora")]
        current = getattr(current, "master", None)
    return COLOR_PALETTES["aurora"]



def status_display(status):
    status = normalize_status(status)
    label = status_label(status)
    if not label:
        return ""
    return label


def status_icon_key(status):
    status = normalize_status(status)
    if status in STATUS_IMAGE_KEYS:
        return STATUS_IMAGE_KEYS[status]
    if "PARCIAL" in status:
        return "partial"
    if "PENDENTE" in status:
        return "pending"
    if "CANCEL" in status:
        return "canceled"
    if status in AREA_FINISHED_STATUS.get("EXPEDICAO", set()) or status == "FINALIZADO":
        return "finished"
    return "status"


def format_proposal(value):
    text = (value or "").strip().upper().replace(" ", "")
    if not text:
        return ""
    if "-P" in text:
        base, partial = text.split("-P", 1)
        base_digits = "".join(ch for ch in base if ch.isdigit())
        partial_digits = "".join(ch for ch in partial if ch.isdigit())
        if base_digits and partial_digits:
            return f"CP{int(base_digits):05d}-P{int(partial_digits)}"
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        return f"CP{int(digits):05d}"
    return text


def display_cell(key, value):
    if value is None:
        return ""
    if key.startswith("status_") or key in ("status_anterior", "status_novo", "situacao_fluxo"):
        return status_display(value)
    if key == "tipo_processo":
        return status_label(value)
    if key == "tem_pendencia_producao":
        return "Sim" if int(value or 0) else "Nao"
    if key == "necessita_almoxarifado":
        return status_label(normalize_stockroom_need(value))
    if key == "acao":
        return str(value).replace("_", " ").title()
    if key == "campo":
        return EXPORT_LABELS.get(str(value), str(value).replace("_", " ").title())
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def export_label(key):
    return EXPORT_LABELS.get(key, key.replace("_", " ").title())


def profile_label(profile):
    return PROFILE_LABELS.get(profile or "", profile or "")


def area_csv(areas):
    return ",".join(area for area in AREAS if area in set(areas or []))


def user_areas(user):
    if not user:
        return set()
    profile = user["perfil"] if "perfil" in user.keys() else ""
    if profile == "admin":
        return set(AREAS.keys())
    try:
        raw = user["areas_acesso"] or ""
    except (KeyError, IndexError):
        raw = ""
    areas = {part.strip().upper() for part in raw.split(",") if part.strip()}
    if areas:
        return areas & set(AREAS.keys())
    return set(PROFILE_DEFAULT_AREAS.get(profile, []))


def user_can_admin(user):
    return bool(user and user["perfil"] == "admin")


def user_can_edit_process(user):
    return user_can_admin(user) or "CONTROLE GERAL" in user_areas(user)


def user_can_access_area(user, area):
    return user_can_admin(user) or area in user_areas(user)


def user_can_mount_galvanization_load(user):
    return user_can_admin(user) or bool(user_areas(user) & {"EXPEDICAO", "GALVANIZACAO"})


def visible_area_names(user):
    if user_can_admin(user):
        return list(AREAS.keys())
    return [area for area in AREAS if area in user_areas(user)]


def editable_observation_areas(user):
    if user_can_admin(user):
        return list(AREAS.keys())
    return visible_area_names(user)


def format_date_for_db(value):
    value = (value or "").strip()
    if not value:
        return ""
    return parse_date(value).strftime(DATE_FMT)


def load_config():
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}
    data.setdefault("db_path", str(DEFAULT_DB_FILE))
    data.setdefault("backup_dir", str(DEFAULT_BACKUP_DIR))
    data.setdefault("backup_keep", 20)
    data.setdefault("company", "Industel")
    data.setdefault("color_palette", "aurora")
    data.setdefault("saved_reports", DEFAULT_REPORT_DEFINITIONS)
    if data["color_palette"] not in COLOR_PALETTES:
        data["color_palette"] = "aurora"
    return data


def save_config(config):
    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def pbkdf2_hash(password, salt=None):
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 180000)
    return salt.hex(), digest.hex()


def verify_password(password, salt_hex, digest_hex):
    salt = bytes.fromhex(salt_hex)
    _, candidate = pbkdf2_hash(password, salt)
    return hmac.compare_digest(candidate, digest_hex)


def db_connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def initialize_database(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            login TEXT NOT NULL UNIQUE,
            senha_salt TEXT NOT NULL,
            senha_hash TEXT NOT NULL,
            perfil TEXT NOT NULL DEFAULT 'operador',
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS processos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente TEXT NOT NULL,
            proposta TEXT NOT NULL UNIQUE,
            pedido_compra TEXT,
            obra_site TEXT,
            peso REAL,
            lote TEXT,
            data_entrada TEXT,
            data_cadastro TEXT NOT NULL,
            prazo_entrega TEXT,
            status_geral TEXT,
            status_producao TEXT,
            data_final_producao TEXT,
            status_galvanizacao TEXT,
            data_envio_galv TEXT,
            data_prevista_retorno_galv TEXT,
            data_retorno_galv TEXT,
            status_expedicao TEXT,
            data_separacao TEXT,
            data_retirada TEXT,
            status_almoxarifado TEXT,
            necessita_almoxarifado TEXT NOT NULL DEFAULT 'NAO_DEFINIDO',
            observacoes_gerais TEXT,
            observacoes_producao TEXT,
            observacoes_galvanizacao TEXT,
            observacoes_expedicao TEXT,
            observacoes_almoxarifado TEXT,
            situacao_fluxo TEXT NOT NULL DEFAULT 'NORMAL',
            tem_pendencia_producao INTEGER NOT NULL DEFAULT 0,
            origem_remanejamento TEXT,
            observacao_remanejamento TEXT,
            processo_pai_id INTEGER,
            tipo_processo TEXT NOT NULL DEFAULT 'PRINCIPAL',
            numero_parcial INTEGER NOT NULL DEFAULT 0,
            peso_parcial REAL,
            saldo_pendente REAL,
            descricao_parcial TEXT,
            atualizado_em TEXT,
            atualizado_por TEXT,
            FOREIGN KEY(processo_pai_id) REFERENCES processos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS status_opcoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            area TEXT NOT NULL,
            nome_status TEXT NOT NULL,
            etapa_atual TEXT NOT NULL,
            proxima_etapa TEXT NOT NULL,
            ordem INTEGER NOT NULL DEFAULT 0,
            ativo INTEGER NOT NULL DEFAULT 1,
            UNIQUE(area, nome_status)
        );

        CREATE TABLE IF NOT EXISTS historico_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            processo_id INTEGER NOT NULL,
            proposta TEXT NOT NULL,
            area TEXT NOT NULL,
            status_anterior TEXT,
            status_novo TEXT NOT NULL,
            data_hora TEXT NOT NULL,
            usuario TEXT NOT NULL,
            computador TEXT NOT NULL,
            observacao TEXT,
            FOREIGN KEY(processo_id) REFERENCES processos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS auditoria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entidade TEXT NOT NULL,
            entidade_id INTEGER,
            acao TEXT NOT NULL,
            campo TEXT,
            valor_anterior TEXT,
            valor_novo TEXT,
            data_hora TEXT NOT NULL,
            usuario TEXT NOT NULL,
            computador TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bloqueios_edicao (
            processo_id INTEGER PRIMARY KEY,
            usuario TEXT NOT NULL,
            computador TEXT NOT NULL,
            bloqueado_em TEXT NOT NULL,
            FOREIGN KEY(processo_id) REFERENCES processos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS configuracoes (
            chave TEXT PRIMARY KEY,
            valor TEXT
        );

        CREATE TABLE IF NOT EXISTS cargas_galvanizacao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            motorista TEXT NOT NULL,
            peso_maximo REAL,
            peso_total REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'AGUARDANDO_LIBERACAO',
            data_prevista_retorno TEXT,
            data_retorno TEXT,
            criado_em TEXT NOT NULL,
            criado_por TEXT NOT NULL,
            computador TEXT NOT NULL,
            observacao TEXT
        );

        CREATE TABLE IF NOT EXISTS cargas_galvanizacao_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            carga_id INTEGER NOT NULL,
            processo_id INTEGER NOT NULL,
            proposta TEXT NOT NULL,
            cliente TEXT,
            peso_total_proposta REAL,
            peso_enviado REAL,
            parcial INTEGER NOT NULL DEFAULT 0,
            observacao TEXT,
            FOREIGN KEY(carga_id) REFERENCES cargas_galvanizacao(id) ON DELETE CASCADE,
            FOREIGN KEY(processo_id) REFERENCES processos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS proposta_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            processo_principal_id INTEGER NOT NULL,
            processo_atual_id INTEGER NOT NULL,
            numero_item TEXT NOT NULL,
            descricao TEXT,
            quantidade INTEGER NOT NULL DEFAULT 1,
            peso REAL NOT NULL DEFAULT 0,
            produzido INTEGER NOT NULL DEFAULT 0,
            galvanizado INTEGER NOT NULL DEFAULT 0,
            entregue INTEGER NOT NULL DEFAULT 0,
            entregue_em TEXT,
            atualizado_em TEXT,
            atualizado_por TEXT,
            UNIQUE(processo_principal_id, numero_item),
            FOREIGN KEY(processo_principal_id) REFERENCES processos(id) ON DELETE CASCADE,
            FOREIGN KEY(processo_atual_id) REFERENCES processos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS entregas_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            processo_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            tipo_entrega TEXT NOT NULL,
            data_hora TEXT NOT NULL,
            usuario TEXT NOT NULL,
            observacao TEXT,
            FOREIGN KEY(processo_id) REFERENCES processos(id) ON DELETE CASCADE,
            FOREIGN KEY(item_id) REFERENCES proposta_itens(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS remanejamentos_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            processo_destino_id INTEGER NOT NULL,
            processo_origem_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            data_hora TEXT NOT NULL,
            usuario TEXT NOT NULL,
            observacao TEXT,
            FOREIGN KEY(processo_destino_id) REFERENCES processos(id) ON DELETE CASCADE,
            FOREIGN KEY(processo_origem_id) REFERENCES processos(id) ON DELETE CASCADE,
            FOREIGN KEY(item_id) REFERENCES proposta_itens(id) ON DELETE CASCADE
        );
        """
    )
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(usuarios)").fetchall()}
    if "areas_acesso" not in columns:
        conn.execute("ALTER TABLE usuarios ADD COLUMN areas_acesso TEXT NOT NULL DEFAULT ''")
        conn.execute(
            "UPDATE usuarios SET areas_acesso = ? WHERE perfil = 'admin' OR login = 'admin'",
            (area_csv(AREAS.keys()),),
        )
        conn.execute(
            "UPDATE usuarios SET areas_acesso = ? WHERE COALESCE(areas_acesso, '') = '' AND perfil = 'operador'",
            (area_csv(AREAS.keys()),),
        )
    process_columns = {row["name"] for row in conn.execute("PRAGMA table_info(processos)").fetchall()}
    process_column_defaults = {
        "situacao_fluxo": "TEXT NOT NULL DEFAULT 'NORMAL'",
        "tem_pendencia_producao": "INTEGER NOT NULL DEFAULT 0",
        "origem_remanejamento": "TEXT",
        "observacao_remanejamento": "TEXT",
        "processo_pai_id": "INTEGER",
        "tipo_processo": "TEXT NOT NULL DEFAULT 'PRINCIPAL'",
        "numero_parcial": "INTEGER NOT NULL DEFAULT 0",
        "peso_parcial": "REAL",
        "saldo_pendente": "REAL",
        "descricao_parcial": "TEXT",
        "data_prevista_retorno_galv": "TEXT",
        "necessita_almoxarifado": "TEXT NOT NULL DEFAULT 'NAO_DEFINIDO'",
        "quantidade_itens": "INTEGER NOT NULL DEFAULT 0",
        "peso_produzido": "REAL NOT NULL DEFAULT 0",
        "peso_entregue": "REAL NOT NULL DEFAULT 0",
    }
    for column, ddl in process_column_defaults.items():
        if column not in process_columns:
            conn.execute(f"ALTER TABLE processos ADD COLUMN {column} {ddl}")
    item_columns = {row["name"] for row in conn.execute("PRAGMA table_info(proposta_itens)").fetchall()}
    if "quantidade" not in item_columns:
        conn.execute("ALTER TABLE proposta_itens ADD COLUMN quantidade INTEGER NOT NULL DEFAULT 1")
    conn.execute(
        """
        UPDATE processos
        SET necessita_almoxarifado = CASE
            WHEN COALESCE(necessita_almoxarifado, '') <> '' THEN necessita_almoxarifado
            WHEN COALESCE(status_almoxarifado, '') = 'SEM_PARAFUSOS' THEN 'NAO'
            WHEN COALESCE(status_almoxarifado, '') <> '' THEN 'SIM'
            ELSE 'NAO_DEFINIDO'
        END
        """
    )
    load_columns = {row["name"] for row in conn.execute("PRAGMA table_info(cargas_galvanizacao)").fetchall()}
    load_column_defaults = {
        "data_prevista_retorno": "TEXT",
        "data_retorno": "TEXT",
    }
    for column, ddl in load_column_defaults.items():
        if column not in load_columns:
            conn.execute(f"ALTER TABLE cargas_galvanizacao ADD COLUMN {column} {ddl}")
    for row in conn.execute("SELECT id, proposta FROM processos").fetchall():
        formatted = format_proposal(row["proposta"])
        if (
            formatted
            and formatted != row["proposta"]
            and formatted.startswith("CP")
            and len(formatted) == 7
            and formatted[2:].isdigit()
        ):
            exists = conn.execute(
                "SELECT id FROM processos WHERE proposta = ? AND id <> ?",
                (formatted, row["id"]),
            ).fetchone()
            if not exists:
                conn.execute("UPDATE processos SET proposta = ? WHERE id = ?", (formatted, row["id"]))
                conn.execute("UPDATE historico_status SET proposta = ? WHERE processo_id = ?", (formatted, row["id"]))
                conn.execute("UPDATE cargas_galvanizacao_itens SET proposta = ? WHERE processo_id = ?", (formatted, row["id"]))
    conn.execute("UPDATE processos SET status_galvanizacao = 'AGUARDANDO_ENVIO' WHERE status_galvanizacao = 'AGUADANDO_ENVIO'")
    conn.execute("UPDATE processos SET status_galvanizacao = 'ENVIADO_GALVANIZACAO' WHERE status_galvanizacao = 'GALVANIZADO'")
    conn.execute("UPDATE processos SET status_expedicao = 'AGUARDANDO_SEPARACAO_PARCIAL' WHERE status_expedicao = 'EM_SEPARACAO_PARCIAL'")
    conn.execute("UPDATE processos SET status_geral = 'CANCELADA' WHERE status_expedicao = 'CANCELADA'")
    conn.execute("UPDATE processos SET status_geral = 'CANCELADA' WHERE status_producao = 'PRODUCAO_CANCELADA'")
    conn.execute("UPDATE processos SET status_geral = 'CANCELADA' WHERE status_galvanizacao = 'GALVANIZACAO_CANCELADA'")
    conn.execute("UPDATE processos SET status_geral = 'CANCELADA' WHERE status_almoxarifado = 'CANCELADO'")
    conn.execute("UPDATE processos SET status_almoxarifado = 'ALMOXARIFADO_ENTREGUE' WHERE status_almoxarifado = 'FINALIZADO'")
    conn.execute("UPDATE processos SET status_almoxarifado = 'AGUARDANDO_CONFIRMACAO' WHERE status_almoxarifado = 'EM_ANDAMENTO'")
    conn.execute("UPDATE historico_status SET status_novo = 'ALMOXARIFADO_ENTREGUE' WHERE area = 'ALMOXARIFADO' AND status_novo = 'FINALIZADO'")
    conn.execute("UPDATE historico_status SET status_anterior = 'ALMOXARIFADO_ENTREGUE' WHERE area = 'ALMOXARIFADO' AND status_anterior = 'FINALIZADO'")
    conn.execute("UPDATE historico_status SET status_novo = 'AGUARDANDO_CONFIRMACAO' WHERE area = 'ALMOXARIFADO' AND status_novo = 'EM_ANDAMENTO'")
    conn.execute("UPDATE historico_status SET status_anterior = 'AGUARDANDO_CONFIRMACAO' WHERE area = 'ALMOXARIFADO' AND status_anterior = 'EM_ANDAMENTO'")
    conn.execute(
        """
        UPDATE processos
        SET situacao_fluxo = CASE
                WHEN status_geral = 'CANCELADA' THEN 'CANCELADA_FLUXO'
                WHEN status_expedicao = 'ENTREGUE' THEN 'CONCLUIDA'
                WHEN status_producao = 'ITEM_PENDENTE_FABRICACAO' THEN 'PENDENTE_POR_REMANEJAMENTO'
                WHEN status_producao = 'FINALIZADO_PARCIAL' THEN 'PARCIAL_COM_PENDENCIA'
                WHEN status_galvanizacao IN ('DISPONIVEL_PARCIAL', 'RETORNOU_PARCIAL')
                  OR status_expedicao IN ('AGUARDANDO_SEPARACAO_PARCIAL', 'ENTREGUE_PARCIAL')
                THEN 'PARCIAL_EM_ANDAMENTO'
                ELSE 'NORMAL'
            END,
            tem_pendencia_producao = CASE
                WHEN status_producao IN ('FINALIZADO_PARCIAL', 'ITEM_PENDENTE_FABRICACAO') THEN 1
                ELSE 0
            END
        """
    )
    conn.execute("UPDATE cargas_galvanizacao SET status = 'LIBERADA_PARA_ENVIO' WHERE status = 'MONTADA'")
    valid_statuses_by_area = {}
    for area, status, etapa_atual, proxima_etapa, ordem in STATUS_OPTIONS:
        valid_statuses_by_area.setdefault(area, set()).add(status)
        conn.execute(
            """
            INSERT OR IGNORE INTO status_opcoes(area, nome_status, etapa_atual, proxima_etapa, ordem)
            VALUES (?, ?, ?, ?, ?)
            """,
            (area, status, etapa_atual, proxima_etapa, ordem),
        )
        conn.execute(
            """
            UPDATE status_opcoes
            SET etapa_atual = ?, proxima_etapa = ?, ordem = ?, ativo = 1
            WHERE area = ? AND nome_status = ?
            """,
            (etapa_atual, proxima_etapa, ordem, area, status),
        )
    for area, valid_statuses in valid_statuses_by_area.items():
        placeholders = ", ".join("?" for _ in valid_statuses)
        conn.execute(
            f"UPDATE status_opcoes SET ativo = 0 WHERE area = ? AND nome_status NOT IN ({placeholders})",
            (area, *sorted(valid_statuses)),
        )
    user_count = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    if user_count == 0:
        salt, digest = pbkdf2_hash("admin")
        conn.execute(
            """
            INSERT INTO usuarios(nome, login, senha_salt, senha_hash, perfil, ativo, criado_em, areas_acesso)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            ("Administrador", "admin", salt, digest, "admin", now_br(), area_csv(AREAS.keys())),
        )
    conn.execute(
        "INSERT OR IGNORE INTO configuracoes(chave, valor) VALUES ('admin_repair_available', '1')"
    )
    conn.commit()


def backup_database(config, reason="auto"):
    db_path = Path(config["db_path"])
    if not db_path.exists():
        return None
    backup_dir = Path(config["backup_dir"])
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"controle_producao_{reason}_{stamp}.db"
    source = sqlite3.connect(str(db_path), timeout=30)
    try:
        destination = sqlite3.connect(str(target))
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    backups = sorted(backup_dir.glob("controle_producao_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    keep = int(config.get("backup_keep", 20))
    for old in backups[keep:]:
        try:
            old.unlink()
        except OSError:
            pass
    return target


def validate_database_file(path):
    path = Path(path)
    if not path.exists() or not path.is_file():
        raise AppError("Arquivo de backup nao encontrado.")
    try:
        conn = sqlite3.connect(str(path))
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise AppError("O arquivo escolhido nao passou na verificacao do SQLite.")
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise AppError("O arquivo escolhido nao parece ser um banco SQLite valido.") from exc
    required = {"usuarios", "processos", "status_opcoes", "historico_status", "configuracoes"}
    missing = required - tables
    if missing:
        raise AppError("O arquivo escolhido nao parece ser um backup deste sistema.")


def remove_database_sidecars(db_path):
    db_path = Path(db_path)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + suffix)
        try:
            if sidecar.exists():
                sidecar.unlink()
        except OSError:
            pass


def sql_filters(filters):
    where = []
    params = []
    text = filters.get("text", "").strip()
    if text:
        pattern = f"%{text}%"
        proposal_pattern = f"%{format_proposal(text)}%" if any(ch.isdigit() for ch in text) else pattern
        where.append("(proposta LIKE ? OR cliente LIKE ? OR obra_site LIKE ? OR lote LIKE ?)")
        params.extend([proposal_pattern, pattern, pattern, pattern])
    cliente = filters.get("cliente", "").strip()
    if cliente:
        where.append("cliente LIKE ?")
        params.append(f"%{cliente}%")
    status = filters.get("status", "").strip()
    if status:
        status_area = filters.get("status_area", "").strip()
        if status_area in AREAS:
            where.append(f"{AREAS[status_area]['column']} = ?")
            params.append(status)
        else:
            where.append(
                """
                (status_geral = ? OR status_producao = ? OR status_galvanizacao = ?
                 OR status_expedicao = ? OR status_almoxarifado = ?)
                """
            )
            params.extend([status] * 5)
    area = filters.get("area", "").strip()
    if area and area != "TODAS":
        column = AREAS[area]["column"]
        where.append(f"COALESCE({column}, '') <> ''")
    prazo = filters.get("prazo", "").strip()
    if prazo == "VENCIDOS":
        today = date.today()
        where.append("prazo_entrega <> ''")
        where.append("date(substr(prazo_entrega, 7, 4) || '-' || substr(prazo_entrega, 4, 2) || '-' || substr(prazo_entrega, 1, 2)) < ?")
        params.append(today.isoformat())
    elif prazo == "PROXIMOS_7_DIAS":
        today = date.today()
        end = today + timedelta(days=7)
        where.append("prazo_entrega <> ''")
        where.append(
            "date(substr(prazo_entrega, 7, 4) || '-' || substr(prazo_entrega, 4, 2) || '-' || substr(prazo_entrega, 1, 2)) BETWEEN ? AND ?"
        )
        params.extend([today.isoformat(), end.isoformat()])
    sql = " WHERE " + " AND ".join(where) if where else ""
    return sql, params


class Repository:
    def __init__(self, conn):
        self.conn = conn
        self.computer = socket.gethostname()

    def authenticate(self, login, password):
        login = login.strip()
        row = self.conn.execute(
            "SELECT * FROM usuarios WHERE login = ? AND ativo = 1", (login,)
        ).fetchone()
        if row and verify_password(password, row["senha_salt"], row["senha_hash"]):
            return row
        if login.lower() == "admin" and password == "admin" and self.repair_admin_once():
            return self.conn.execute(
                "SELECT * FROM usuarios WHERE login = ? AND ativo = 1", ("admin",)
            ).fetchone()
        return None

    def repair_admin_once(self):
        flag = self.conn.execute(
            "SELECT valor FROM configuracoes WHERE chave = 'admin_repair_available'"
        ).fetchone()
        if not flag or flag["valor"] != "1":
            return False
        salt, digest = pbkdf2_hash("admin")
        existing = self.conn.execute("SELECT id FROM usuarios WHERE login = 'admin'").fetchone()
        if existing:
            self.conn.execute(
                """
                UPDATE usuarios
                SET nome = 'Administrador', senha_salt = ?, senha_hash = ?,
                    perfil = 'admin', ativo = 1, areas_acesso = ?
                WHERE login = 'admin'
                """,
                (salt, digest, area_csv(AREAS.keys())),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO usuarios(nome, login, senha_salt, senha_hash, perfil, ativo, criado_em, areas_acesso)
                VALUES ('Administrador', 'admin', ?, ?, 'admin', 1, ?, ?)
                """,
                (salt, digest, now_br(), area_csv(AREAS.keys())),
            )
        self.conn.execute(
            "UPDATE configuracoes SET valor = '0' WHERE chave = 'admin_repair_available'"
        )
        self.conn.commit()
        return True

    def list_status(self, area=None):
        if area:
            rows = self.conn.execute(
                "SELECT nome_status FROM status_opcoes WHERE area = ? AND ativo = 1 ORDER BY ordem, nome_status",
                (area,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT DISTINCT nome_status FROM status_opcoes WHERE ativo = 1 ORDER BY nome_status"
            ).fetchall()
        return [r["nome_status"] for r in rows if r["nome_status"]]

    def allowed_status_transitions(self, area, old_status):
        old_status = normalize_status(old_status or "")
        transitions = {
            "CONTROLE GERAL": {
                "": {"NAO_LIBERADO"},
                "NAO_LIBERADO": {"LIBERADO_PRODUCAO", "CANCELADA"},
                "LIBERADO_PRODUCAO": {"CANCELADA"},
            },
            "PRODUCAO": {
                "": {"NAO_INICIADO"},
                "NAO_INICIADO": {"INICIADO"},
                "ITEM_PENDENTE_FABRICACAO": {"INICIADO"},
                "INICIADO": {"PARADO", "FINALIZADO", "FINALIZADO_PARCIAL"},
                "PARADO": {"INICIADO"},
                "FINALIZADO_PARCIAL": {"FINALIZADO"},
            },
            "GALVANIZACAO": {
                "": {"AGUARDANDO_ENVIO"},
                "AGUARDANDO_ENVIO": {"EM_CARGA"},
                "DISPONIVEL_PARCIAL": {"EM_CARGA"},
                "EM_CARGA": {"ENVIADO_GALVANIZACAO"},
                "ENVIADO_GALVANIZACAO": {"RETORNOU_GALVANIZACAO"},
            },
            "EXPEDICAO": {
                "": {"EM_SEPARACAO"},
                "EM_SEPARACAO": {"SEPARACAO_INICIADA"},
                "AGUARDANDO_SEPARACAO_PARCIAL": {"SEPARACAO_INICIADA"},
                "SEPARACAO_INICIADA": {"SEPARADO"},
                "SEPARADO": {"ENTREGUE", "ENTREGUE_PARCIAL"},
                "ENTREGUE_PARCIAL": {"ENTREGUE_PARCIAL", "ENTREGUE"},
            },
            "ALMOXARIFADO": {
                "": {"AGUARDANDO_CONFIRMACAO"},
                "AGUARDANDO_CONFIRMACAO": {"EM_SEPARACAO", "SEM_PARAFUSOS"},
                "EM_ANDAMENTO": {"EM_SEPARACAO", "SEM_PARAFUSOS"},
                "EM_SEPARACAO": {"SEPARADO"},
                "SEPARADO": {"ALMOXARIFADO_ENTREGUE", "ALMOXARIFADO_ENTREGUE_PARCIAL"},
                "ALMOXARIFADO_ENTREGUE_PARCIAL": {"ALMOXARIFADO_ENTREGUE"},
            },
        }
        return transitions.get(area, {}).get(old_status, set())

    def is_partial_delivery_context(self, process):
        return (
            (process["situacao_fluxo"] or "") in ("PARCIAL_COM_PENDENCIA", "PARCIAL_EM_ANDAMENTO")
            or int(process["tem_pendencia_producao"] or 0) == 1
            or (process["status_producao"] or "") == "FINALIZADO_PARCIAL"
            or (process["status_galvanizacao"] or "") in ("DISPONIVEL_PARCIAL", "RETORNOU_PARCIAL")
            or (process["status_expedicao"] or "") in ("AGUARDANDO_SEPARACAO_PARCIAL", "ENTREGUE_PARCIAL")
        )

    def expedition_completion_requires_remanagement(self, process):
        return (
            self.is_partial_process(process)
            or int(process["tem_pendencia_producao"] or 0) == 1
            or (process["status_producao"] or "") in ("FINALIZADO_PARCIAL", "ITEM_PENDENTE_FABRICACAO")
            or (process["status_galvanizacao"] or "") in ("DISPONIVEL_PARCIAL", "RETORNOU_PARCIAL")
            or (process["status_expedicao"] or "") == "AGUARDANDO_SEPARACAO_PARCIAL"
        )

    def expedition_delivery_can_close_after_customer_partial(self, process):
        if (process["status_expedicao"] or "") != "ENTREGUE_PARCIAL":
            return False
        if self.is_partial_process(process):
            return False
        if int(process["tem_pendencia_producao"] or 0) == 1:
            return False
        if (process["status_producao"] or "") in ("FINALIZADO_PARCIAL", "ITEM_PENDENTE_FABRICACAO"):
            return False
        if (process["status_galvanizacao"] or "") in ("DISPONIVEL_PARCIAL", "RETORNOU_PARCIAL"):
            return False
        if self.list_active_child_partials(process["id"]):
            return False
        return True

    def next_status_options(self, area, process):
        if area not in AREAS:
            return []
        current = process[AREAS[area]["column"]] or ""
        valid = set(self.list_status(area))
        options = [status for status in STATUS_FLOW_ORDER.get(area, []) if status in self.allowed_status_transitions(area, current) and status in valid]
        if area == "EXPEDICAO" and self.is_partial_delivery_context(process):
            if current == "SEPARADO":
                options = [status for status in options if status == "ENTREGUE_PARCIAL"]
            elif current == "AGUARDANDO_SEPARACAO_PARCIAL":
                options = [status for status in options if status == "SEPARACAO_INICIADA"]
            elif current == "ENTREGUE_PARCIAL":
                options = [status for status in options if status in ("ENTREGUE_PARCIAL", "ENTREGUE")]
        if area == "GALVANIZACAO":
            options = [status for status in options if status != "RETORNOU_PARCIAL"]
        return options

    def list_processes(self, filters=None):
        filters = filters or {}
        where, params = sql_filters(filters)
        query = "SELECT * FROM processos" + where + " ORDER BY id DESC"
        return self.conn.execute(query, params).fetchall()

    def get_process(self, process_id):
        return self.conn.execute("SELECT * FROM processos WHERE id = ?", (process_id,)).fetchone()

    def get_process_by_proposal(self, proposal):
        return self.conn.execute("SELECT * FROM processos WHERE proposta = ?", (format_proposal(proposal),)).fetchone()

    def fiscal_entry_exists(self, process_id):
        return self.conn.execute(
            "SELECT id FROM fiscal_processos WHERE processo_id = ?",
            (process_id,),
        ).fetchone() is not None

    def ensure_fiscal_entry_for_process(self, processo_id, usuario, observacao=None):
        process = self.get_process(processo_id)
        if not process:
            raise AppError("Processo nao encontrado para entrada fiscal.")
        if (process["status_galvanizacao"] or "") != "RETORNOU_GALVANIZACAO":
            return None
        if process["origem_remanejamento"] or (process["situacao_fluxo"] or "") == "PENDENTE_POR_REMANEJAMENTO":
            return None
        existing = self.conn.execute(
            "SELECT * FROM fiscal_processos WHERE processo_id = ?",
            (process["id"],),
        ).fetchone()
        if existing:
            return existing["id"]

        created_at = now_br()
        fiscal_id = self.conn.execute(
            """
            INSERT INTO fiscal_processos(
                processo_id, proposta, status_fiscal, data_entrada_fiscal,
                observacao, created_at, updated_at
            ) VALUES (?, ?, 'FALTA_EMITIR_NOTA_FISCAL', ?, ?, ?, ?)
            """,
            (
                process["id"],
                process["proposta"],
                today_br(),
                observacao or "",
                created_at,
                created_at,
            ),
        ).lastrowid
        self.create_fiscal_items_from_process_items(process["id"], fiscal_id)
        self.conn.execute(
            """
            INSERT INTO fiscal_movimentacoes(
                fiscal_processo_id, processo_id, tipo_movimento, status_anterior,
                status_novo, usuario, data_hora, observacao
            ) VALUES (?, ?, 'ENTRADA_FISCAL', 'FORA_DO_FISCAL',
                      'FALTA_EMITIR_NOTA_FISCAL', ?, ?, ?)
            """,
            (
                fiscal_id,
                process["id"],
                usuario["login"],
                now_br(),
                observacao or "Entrada fiscal automatica pelo retorno da galvanizacao.",
            ),
        )
        return fiscal_id

    def create_fiscal_items_from_process_items(self, processo_id, fiscal_processo_id=None):
        process = self.get_process(processo_id)
        if not process:
            raise AppError("Processo nao encontrado para itens fiscais.")
        fiscal_id = fiscal_processo_id
        if fiscal_id is None:
            fiscal = self.conn.execute(
                "SELECT id FROM fiscal_processos WHERE processo_id = ?",
                (process["id"],),
            ).fetchone()
            if not fiscal:
                raise AppError("Entrada fiscal nao encontrada para criar itens.")
            fiscal_id = fiscal["id"]
        created_at = now_br()
        for item in self.list_proposal_items(process["id"]):
            quantity = float(item["quantidade"] or 0)
            unit_weight = float(item["peso"] or 0)
            self.conn.execute(
                """
                INSERT OR IGNORE INTO fiscal_itens(
                    fiscal_processo_id, processo_id, item_id, numero_item,
                    descricao, quantidade_total, quantidade_faturada, peso_total,
                    peso_faturado, status_item_fiscal, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, 0, 'PENDENTE', ?, ?)
                """,
                (
                    fiscal_id,
                    process["id"],
                    item["id"],
                    item["numero_item"],
                    item["descricao"] or "",
                    quantity,
                    quantity * unit_weight,
                    created_at,
                    created_at,
                ),
            )

    def process_main_id(self, process):
        return int(process["processo_pai_id"] or process["id"])

    def list_proposal_items(self, process_id, pending_production=False, pending_delivery=False):
        process = self.get_process(process_id)
        if not process:
            return []
        where = ["processo_principal_id = ?"]
        params = [self.process_main_id(process)]
        if self.is_partial_process(process):
            where.append("processo_atual_id = ?")
            params.append(process["id"])
        elif pending_delivery:
            where.append("processo_atual_id = ?")
            params.append(process["id"])
        if pending_production:
            where.append("produzido = 0")
        if pending_delivery:
            where.extend(["produzido = 1", "entregue = 0"])
        return self.conn.execute(
            "SELECT * FROM proposta_itens WHERE " + " AND ".join(where) +
            " ORDER BY CAST(numero_item AS INTEGER), numero_item, id",
            tuple(params),
        ).fetchall()

    def replace_proposal_items(self, process_id, items, user):
        process = self.get_process(process_id)
        if not process or self.is_partial_process(process):
            raise AppError("Os itens devem ser cadastrados na proposta principal.")
        existing_used = self.conn.execute(
            "SELECT COUNT(*) FROM proposta_itens WHERE processo_principal_id = ? AND (produzido = 1 OR entregue = 1 OR processo_atual_id <> ?)",
            (process_id, process_id),
        ).fetchone()[0]
        if existing_used:
            raise AppError("Os itens nao podem ser substituidos depois que o processo por itens foi iniciado.")
        normalized = []
        numbers = set()
        for index, item in enumerate(items or [], start=1):
            number = str(item.get("numero_item") or index).strip()
            if not number or number in numbers:
                raise AppError("Cada item deve possuir uma numeracao unica.")
            numbers.add(number)
            try:
                quantity = int(str(item.get("quantidade", 1) or 1).strip())
            except ValueError as exc:
                raise AppError("A quantidade do item deve ser um numero inteiro.") from exc
            if quantity <= 0:
                raise AppError("A quantidade do item deve ser maior que zero.")
            weight = self.to_float(item.get("peso", "")) or 0
            if weight < 0:
                raise AppError("O peso do item nao pode ser negativo.")
            normalized.append((number, (item.get("descricao") or "").strip(), quantity, weight))
        self.conn.execute("DELETE FROM proposta_itens WHERE processo_principal_id = ?", (process_id,))
        for number, description, quantity, weight in normalized:
            self.conn.execute(
                """
                INSERT INTO proposta_itens(
                    processo_principal_id, processo_atual_id, numero_item, descricao, quantidade, peso,
                    produzido, galvanizado, entregue, atualizado_em, atualizado_por
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, ?, ?)
                """,
                (process_id, process_id, number, description, quantity, weight, now_br(), user["login"]),
            )
        total_weight = sum(item[2] * item[3] for item in normalized)
        updates = {"quantidade_itens": sum(item[2] for item in normalized)}
        if normalized and total_weight > 0:
            updates["peso"] = total_weight
        assignments = ", ".join(f"{key} = ?" for key in updates)
        self.conn.execute(f"UPDATE processos SET {assignments} WHERE id = ?", tuple(updates.values()) + (process_id,))

    def item_progress(self, process_id):
        process = self.get_process(process_id)
        if not process:
            return {"total": 0, "produzido": 0, "entregue": 0, "peso_total": 0, "peso_produzido": 0, "peso_entregue": 0}
        main_id = self.process_main_id(process)
        scope = "processo_principal_id = ?"
        params = [main_id]
        if self.is_partial_process(process):
            scope += " AND processo_atual_id = ?"
            params.append(process["id"])
        row = self.conn.execute(
            f"""
            SELECT COALESCE(SUM(quantidade), 0) total,
                   COALESCE(SUM(CASE WHEN produzido = 1 THEN quantidade ELSE 0 END), 0) produzido,
                   COALESCE(SUM(CASE WHEN entregue = 1 THEN quantidade ELSE 0 END), 0) entregue,
                   COALESCE(SUM(quantidade * peso), 0) peso_total,
                   COALESCE(SUM(CASE WHEN produzido = 1 THEN quantidade * peso ELSE 0 END), 0) peso_produzido,
                   COALESCE(SUM(CASE WHEN entregue = 1 THEN quantidade * peso ELSE 0 END), 0) peso_entregue
            FROM proposta_itens WHERE {scope}
            """,
            tuple(params),
        ).fetchone()
        return dict(row)

    def weight_progress_text(self, process_id):
        process = self.get_process(process_id)
        if not process:
            return "-"
        progress = self.item_progress(process_id)
        main = self.get_process(self.process_main_id(process))
        main_progress = self.item_progress(main["id"])
        total = float(main_progress["peso_total"] or 0) or float(main["peso"] or 0)
        if not total:
            return "-"
        if self.is_partial_process(process):
            value = float(process["peso"] or 0) or float(progress["peso_total"] or 0)
        else:
            produced = max(
                float(main_progress["peso_produzido"] or 0),
                float(main["peso_produzido"] or 0),
            )
            value = total if produced >= total and total else max(0, total - produced)
        return f"{value:g}/{total:g} kg"

    def register_item_delivery(self, process_id, item_ids, user, observation=""):
        process = self.get_process(process_id)
        if not process:
            raise AppError("Processo nao encontrado.")
        available = {row["id"]: row for row in self.list_proposal_items(process_id, pending_delivery=True)}
        selected = [available[int(item_id)] for item_id in item_ids if int(item_id) in available]
        if not selected:
            raise AppError("Selecione pelo menos um item disponivel para entrega.")
        for item in selected:
            self.conn.execute(
                "UPDATE proposta_itens SET entregue = 1, entregue_em = ?, atualizado_em = ?, atualizado_por = ? WHERE id = ?",
                (now_br(), now_br(), user["login"], item["id"]),
            )
            self.conn.execute(
                "INSERT INTO entregas_itens(processo_id, item_id, tipo_entrega, data_hora, usuario, observacao) VALUES (?, ?, 'PARCIAL', ?, ?, ?)",
                (process_id, item["id"], now_br(), user["login"], observation),
            )
        remaining = self.list_proposal_items(process_id, pending_delivery=True)
        delivered_weight = self.item_progress(process_id)["peso_entregue"]
        new_status = "ENTREGUE_PARCIAL" if remaining else "ENTREGUE"
        general_status = "EM_EXPEDICAO" if remaining else "ENTREGUE"
        flow_status = "PARCIAL_EM_ANDAMENTO" if remaining else "CONCLUIDA"
        self.conn.execute(
            """
            UPDATE processos
            SET status_expedicao = ?, status_geral = ?, situacao_fluxo = ?,
                peso_entregue = ?, data_retirada = ?, atualizado_em = ?, atualizado_por = ?
            WHERE id = ?
            """,
            (
                new_status,
                general_status,
                flow_status,
                delivered_weight,
                today_br(),
                now_br(),
                user["login"],
                process_id,
            ),
        )
        self.add_history(process_id, process["proposta"], "EXPEDICAO", process["status_expedicao"] or "", new_status, user, observation or "Entrega de itens selecionados")
        if not remaining and process["processo_pai_id"]:
            self.refresh_parent_completion(process["processo_pai_id"], user)
        self.conn.commit()
        return new_status

    def list_partial_pending_processes(self, filters=None):
        rows = self.list_processes(filters or {})
        result = []
        for row in rows:
            if (row["status_expedicao"] or "") == "UNIFICADA_PRINCIPAL":
                continue
            if (
                (row["tipo_processo"] or "") == "PARCIAL"
                or (row["situacao_fluxo"] or "") in ("PARCIAL_COM_PENDENCIA", "PARCIAL_EM_ANDAMENTO", "PENDENTE_POR_REMANEJAMENTO")
                or int(row["tem_pendencia_producao"] or 0) == 1
                or (row["status_producao"] or "") in ("FINALIZADO_PARCIAL", "ITEM_PENDENTE_FABRICACAO")
                or (row["status_galvanizacao"] or "") in ("DISPONIVEL_PARCIAL", "RETORNOU_PARCIAL")
                or (row["status_expedicao"] or "") in ("AGUARDANDO_SEPARACAO_PARCIAL", "ENTREGUE_PARCIAL")
                or bool(row["origem_remanejamento"] or "")
            ):
                result.append(row)
        return result

    def list_process_partials(self, process):
        if not process:
            return []
        parent_id = process["processo_pai_id"] or process["id"]
        return self.conn.execute(
            """
            SELECT * FROM processos
            WHERE processo_pai_id = ? OR id = ?
            ORDER BY tipo_processo, numero_parcial, id
            """,
            (parent_id, parent_id),
        ).fetchall()

    def list_active_child_partials(self, parent_id):
        if not parent_id:
            return []
        return self.conn.execute(
            """
            SELECT * FROM processos
            WHERE processo_pai_id = ?
              AND COALESCE(status_geral, '') NOT IN ('CANCELADA', 'ENTREGUE')
              AND COALESCE(status_expedicao, '') <> 'UNIFICADA_PRINCIPAL'
            ORDER BY numero_parcial, id
            """,
            (parent_id,),
        ).fetchall()

    def list_process_loads(self, process_id):
        return self.conn.execute(
            """
            SELECT c.id, c.status, c.motorista, c.data_prevista_retorno, c.data_retorno,
                   i.proposta, i.peso_enviado, i.parcial, i.observacao
            FROM cargas_galvanizacao_itens i
            JOIN cargas_galvanizacao c ON c.id = i.carga_id
            WHERE i.processo_id = ?
            ORDER BY c.id DESC
            """,
            (process_id,),
        ).fetchall()

    def is_partial_process(self, process):
        return (process["tipo_processo"] if "tipo_processo" in process.keys() else "PRINCIPAL") == "PARCIAL"

    def principal_still_in_production(self, process):
        return (
            not self.is_partial_process(process)
            and (process["status_producao"] or "") in ("FINALIZADO_PARCIAL", "ITEM_PENDENTE_FABRICACAO")
        )

    def next_partial_number(self, parent_id):
        row = self.conn.execute(
            "SELECT COALESCE(MAX(numero_parcial), 0) + 1 AS next_number FROM processos WHERE processo_pai_id = ?",
            (parent_id,),
        ).fetchone()
        return int(row["next_number"] or 1)

    def create_partial_subprocess(
        self,
        parent,
        user,
        description="",
        final_balance=False,
        item_ids=None,
        produced_weight=None,
    ):
        if self.is_partial_process(parent):
            return None
        partial_number = self.next_partial_number(parent["id"])
        proposal = f"{parent['proposta']}-P{partial_number}"
        description = (description or "").strip()
        if not description:
            description = "Parcial liberada pela Producao."
        existing = self.get_process_by_proposal(proposal)
        if existing:
            raise AppError(f"Ja existe o subprocesso {proposal}.")
        status_production = "FINALIZADO"
        status_general = "EM_GALVANIZACAO"
        status_galv = "AGUARDANDO_ENVIO" if final_balance else "DISPONIVEL_PARCIAL"
        situation = "NORMAL" if final_balance else "PARCIAL_EM_ANDAMENTO"
        selected_items = []
        if item_ids:
            pending_rows = self.list_proposal_items(parent["id"], pending_production=True)
            pending = {row["id"]: row for row in pending_rows}
            selected_items = [pending[int(item_id)] for item_id in item_ids if int(item_id) in pending]
            if not selected_items:
                raise AppError("Selecione pelo menos um item pendente para criar a parcial.")
            if not final_balance and len(selected_items) == len(pending_rows):
                raise AppError("Todos os itens foram selecionados. Use o status Producao concluida.")
        calculated_weight = sum(
            int(item["quantidade"] or 1) * float(item["peso"] or 0)
            for item in selected_items
        ) if selected_items else 0
        partial_weight = float(produced_weight or 0) or calculated_weight or None
        if selected_items and not partial_weight:
            raise AppError("Informe o peso total produzido nesta parcial.")
        values = {
            "cliente": parent["cliente"],
            "proposta": proposal,
            "pedido_compra": parent["pedido_compra"],
            "obra_site": parent["obra_site"],
            "peso": partial_weight,
            "lote": parent["lote"],
            "data_entrada": parent["data_entrada"],
            "data_cadastro": now_br(),
            "prazo_entrega": parent["prazo_entrega"],
            "status_geral": status_general,
            "status_producao": status_production,
            "data_final_producao": today_br(),
            "status_galvanizacao": status_galv,
            "data_envio_galv": None,
            "data_prevista_retorno_galv": None,
            "data_retorno_galv": None,
            "status_expedicao": "",
            "data_separacao": None,
            "data_retirada": None,
            "status_almoxarifado": "",
            "observacoes_gerais": parent["observacoes_gerais"],
            "observacoes_producao": description,
            "observacoes_galvanizacao": "",
            "observacoes_expedicao": "",
            "observacoes_almoxarifado": "",
            "situacao_fluxo": situation,
            "tem_pendencia_producao": 0,
            "origem_remanejamento": "",
            "observacao_remanejamento": "",
            "processo_pai_id": parent["id"],
            "tipo_processo": "PARCIAL",
            "numero_parcial": partial_number,
            "peso_parcial": partial_weight,
            "saldo_pendente": None,
            "descricao_parcial": description,
            "atualizado_em": now_br(),
            "atualizado_por": user["login"],
        }
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        cur = self.conn.execute(
            f"INSERT INTO processos({columns}) VALUES ({placeholders})",
            tuple(values.values()),
        )
        partial_id = cur.lastrowid
        if selected_items:
            item_id_values = [item["id"] for item in selected_items]
            placeholders = ", ".join("?" for _ in item_id_values)
            self.conn.execute(
                f"""
                UPDATE proposta_itens
                SET processo_atual_id = ?, produzido = 1, atualizado_em = ?, atualizado_por = ?
                WHERE id IN ({placeholders})
                """,
                (partial_id, now_br(), user["login"], *item_id_values),
            )
            progress = self.item_progress(parent["id"])
            produced_total = self.conn.execute(
                "SELECT COALESCE(SUM(peso), 0) FROM processos WHERE processo_pai_id = ?",
                (parent["id"],),
            ).fetchone()[0]
            main_total = float(parent["peso"] or 0) or float(progress["peso_total"] or 0)
            self.conn.execute(
                "UPDATE processos SET peso_produzido = ?, saldo_pendente = ?, quantidade_itens = ? WHERE id = ?",
                (
                    produced_total,
                    max(0, main_total - float(produced_total or 0)),
                    progress["total"],
                    parent["id"],
                ),
            )
            self.conn.execute(
                "UPDATE processos SET quantidade_itens = ?, peso_produzido = ? WHERE id = ?",
                (sum(int(item["quantidade"] or 1) for item in selected_items), partial_weight or 0, partial_id),
            )
        self.add_history(partial_id, proposal, "PRODUCAO", "", status_production, user, f"Subprocesso parcial criado a partir de {parent['proposta']} | {description}")
        self.add_history(partial_id, proposal, "GALVANIZACAO", "", status_galv, user, "Liberacao automatica do subprocesso parcial")
        self.add_audit("processos", partial_id, "CRIACAO_SUBPROCESSO", "processo_pai_id", "", parent["proposta"], user)
        return partial_id

    def refresh_parent_completion(self, parent_id, user):
        if not parent_id:
            return
        parent = self.get_process(parent_id)
        if not parent:
            return
        if parent["status_producao"] != "FINALIZADO":
            return
        open_child = self.conn.execute(
            """
            SELECT id FROM processos
            WHERE processo_pai_id = ?
              AND COALESCE(status_geral, '') <> 'CANCELADA'
              AND COALESCE(status_expedicao, '') <> 'ENTREGUE'
            LIMIT 1
            """,
            (parent_id,),
        ).fetchone()
        if open_child:
            return
        if parent["status_geral"] == "ENTREGUE":
            return
        self.conn.execute(
            """
            UPDATE processos
            SET status_geral = ?, situacao_fluxo = ?, tem_pendencia_producao = ?,
                atualizado_em = ?, atualizado_por = ?
            WHERE id = ?
            """,
            ("ENTREGUE", "CONCLUIDA", 0, now_br(), user["login"], parent_id),
        )
        self.add_history(parent_id, parent["proposta"], "CONTROLE GERAL", parent["status_geral"] or "", "ENTREGUE", user, "Todas as parciais foram entregues.")

    def merge_expedition_partials(self, process_ids, user, automatic=False):
        if not automatic and not user_can_access_area(user, "EXPEDICAO"):
            raise AppError("Seu usuario nao tem permissao para juntar parciais na Expedicao.")
        selected = [self.get_process(process_id) for process_id in process_ids]
        selected = [process for process in selected if process]
        if not selected:
            raise AppError("Selecione uma parcial na Expedicao.")
        parent_ids = set()
        for process in selected:
            if self.is_partial_process(process):
                parent_ids.add(process["processo_pai_id"])
            else:
                parent_ids.add(process["id"])
        parent_ids.discard(None)
        if len(parent_ids) != 1:
            raise AppError("Selecione parciais da mesma proposta principal.")
        parent_id = next(iter(parent_ids))
        parent = self.get_process(parent_id)
        if not parent:
            raise AppError("Proposta principal nao encontrada.")
        partials = self.conn.execute(
            """
            SELECT * FROM processos
            WHERE processo_pai_id = ?
              AND COALESCE(status_geral, '') <> 'CANCELADA'
              AND COALESCE(status_expedicao, '') <> 'UNIFICADA_PRINCIPAL'
            ORDER BY numero_parcial, id
            """,
            (parent_id,),
        ).fetchall()
        if len(partials) < 2:
            raise AppError("Para juntar, e necessario ter pelo menos duas parciais ativas da mesma proposta.")
        expedition_ready = {"EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARACAO_INICIADA", "SEPARADO"}
        not_ready = [partial["proposta"] for partial in partials if (partial["status_expedicao"] or "") not in expedition_ready]
        if not_ready:
            raise AppError("Ainda existem parciais que nao chegaram ou ja sairam da Expedicao: " + ", ".join(not_ready))
        delivered = [partial["proposta"] for partial in partials if (partial["status_expedicao"] or "") in ("ENTREGUE", "ENTREGUE_PARCIAL")]
        if delivered:
            raise AppError("Nao e possivel juntar parciais que ja tiveram entrega: " + ", ".join(delivered))
        parent_old_expedition = parent["status_expedicao"] or ""
        partial_statuses = {(partial["status_expedicao"] or "") for partial in partials}
        if partial_statuses == {"SEPARADO"}:
            parent_new_expedition = "SEPARADO"
        elif "SEPARACAO_INICIADA" in partial_statuses:
            parent_new_expedition = "SEPARACAO_INICIADA"
        else:
            parent_new_expedition = "EM_SEPARACAO"
        note = "Parciais reunidas na Expedicao: " + ", ".join(partial["proposta"] for partial in partials)
        parent_updates = {
            "tipo_processo": "PRINCIPAL",
            "status_geral": "EM_EXPEDICAO",
            "status_producao": "FINALIZADO",
            "status_galvanizacao": "RETORNOU_GALVANIZACAO",
            "status_expedicao": parent_new_expedition,
            "situacao_fluxo": "NORMAL",
            "tem_pendencia_producao": 0,
            "observacoes_expedicao": note,
            "atualizado_em": now_br(),
            "atualizado_por": user["login"],
        }
        if not parent["data_retorno_galv"]:
            parent_updates["data_retorno_galv"] = today_br()
        if not parent["data_separacao"]:
            parent_updates["data_separacao"] = today_br()
        assignments = ", ".join(f"{key} = ?" for key in parent_updates)
        self.conn.execute(
            f"UPDATE processos SET {assignments} WHERE id = ?",
            tuple(parent_updates.values()) + (parent_id,),
        )
        if parent_old_expedition != parent_new_expedition:
            self.add_history(parent_id, parent["proposta"], "EXPEDICAO", parent_old_expedition, parent_new_expedition, user, note)
        for partial in partials:
            old_expedition = partial["status_expedicao"] or ""
            self.conn.execute(
                """
                UPDATE processos
                SET status_geral = ?, status_galvanizacao = ?, status_expedicao = ?,
                    situacao_fluxo = ?, tem_pendencia_producao = ?, observacoes_expedicao = ?,
                    atualizado_em = ?, atualizado_por = ?
                WHERE id = ?
                """,
                (
                    "ENTREGUE",
                    "RETORNOU_GALVANIZACAO",
                    "UNIFICADA_PRINCIPAL",
                    "UNIFICADA_NA_PRINCIPAL",
                    0,
                    f"Unificada na proposta principal {parent['proposta']}.",
                    now_br(),
                    user["login"],
                    partial["id"],
                ),
            )
            self.add_history(partial["id"], partial["proposta"], "EXPEDICAO", old_expedition, "UNIFICADA_PRINCIPAL", user, f"Unificada na principal {parent['proposta']}")
        self.add_audit("processos", parent_id, "UNIFICACAO_PARCIAIS", "status_expedicao", parent_old_expedition, parent_new_expedition, user)
        self.conn.commit()
        return parent_id, len(partials)

    def try_auto_merge_expedition_partials(self, process_id, user):
        process = self.get_process(process_id)
        if not process or not self.is_partial_process(process):
            return None
        if (process["status_expedicao"] or "") not in ("EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARACAO_INICIADA", "SEPARADO"):
            return None
        try:
            return self.merge_expedition_partials([process_id], user, automatic=True)
        except AppError:
            return None

    def process_family_id(self, process):
        if not process:
            return None
        return process["processo_pai_id"] or process["id"]

    def same_process_family(self, first, second):
        return bool(first and second and self.process_family_id(first) == self.process_family_id(second))

    def list_remanagement_source_candidates(self, exclude_process_id=None):
        params = []
        where = [
            "status_producao = 'FINALIZADO'",
            "status_expedicao IN ('SEPARADO', 'ENTREGUE_PARCIAL')",
            "COALESCE(status_geral, '') NOT IN ('CANCELADA', 'ENTREGUE', 'FINALIZADO')",
        ]
        if exclude_process_id:
            where.append("id <> ?")
            params.append(exclude_process_id)
        rows = self.conn.execute(
            "SELECT * FROM processos WHERE " + " AND ".join(where) + " ORDER BY proposta",
            params,
        ).fetchall()
        destination = self.get_process(exclude_process_id) if exclude_process_id else None
        if not destination:
            return rows
        destination_family_id = self.process_family_id(destination)
        return [row for row in rows if self.process_family_id(row) != destination_family_id]

    def list_early_delivery_destination_candidates(self, search=""):
        filters = {"text": search} if (search or "").strip() else {}
        rows = self.list_processes(filters)
        return [
            row for row in rows
            if (row["status_geral"] or "") not in ("ENTREGUE", "CANCELADA", "FINALIZADO")
            and (row["tipo_processo"] if "tipo_processo" in row.keys() else "PRINCIPAL") == "PRINCIPAL"
        ]

    def deliver_by_material_remanagement(self, destination_id, source_id, user, observation, item_ids=None):
        if not user_can_access_area(user, "EXPEDICAO"):
            raise AppError("Seu usuario nao tem permissao para fazer entrega por remanejamento.")
        if destination_id == source_id:
            raise AppError("A proposta entregue e a proposta origem devem ser diferentes.")
        observation = (observation or "").strip()
        destination = self.get_process(destination_id)
        source = self.get_process(source_id)
        if not destination or not source:
            raise AppError("Proposta nao encontrada.")
        if self.same_process_family(destination, source):
            raise AppError("Nao e permitido remanejar material entre a proposta principal e as parciais dela mesma.")
        if (destination["status_geral"] or "") in ("ENTREGUE", "CANCELADA", "FINALIZADO"):
            raise AppError("A proposta de destino nao esta disponivel para entrega por remanejamento.")
        if source["status_geral"] == "CANCELADA":
            raise AppError("A proposta origem esta cancelada.")
        if source["status_producao"] != "FINALIZADO":
            raise AppError("A proposta origem precisa estar pronta na Producao para ceder material.")
        if (source["status_expedicao"] or "") not in ("SEPARADO", "ENTREGUE_PARCIAL"):
            raise AppError("A proposta origem precisa possuir material pronto na Expedicao.")
        source_items = self.list_proposal_items(source_id)
        selected_items = []
        if source_items:
            available = {
                int(item["id"]): item
                for item in source_items
                if int(item["produzido"] or 0) == 1 and int(item["entregue"] or 0) == 0
            }
            selected_items = [available[int(item_id)] for item_id in (item_ids or []) if int(item_id) in available]
            if not selected_items:
                raise AppError("Selecione pelo menos um item pronto da proposta origem.")
            selected_labels = [
                f"Item {item['numero_item']} ({int(item['quantidade'] or 1)} un.)"
                for item in selected_items
            ]
            item_note = ", ".join(selected_labels)
            observation = f"{item_note}. {observation}".strip().rstrip(".")
        elif not observation:
            raise AppError("Informe quais itens foram remanejados.")
        self.confirm_stockroom_delivery(destination_id, user, "Confirmacao automatica pela entrega por remanejamento")

        note_source = f"{observation} | Material usado para entrega antecipada de {destination['proposta']}"
        note_destination = f"Entrega antecipada por remanejamento da proposta {source['proposta']} | {observation}"
        old_source_production = source["status_producao"] or ""
        old_source_galvanization = source["status_galvanizacao"] or ""
        old_source_expedition = source["status_expedicao"] or ""
        old_destination_general = destination["status_geral"] or ""
        old_destination_production = destination["status_producao"] or ""
        old_destination_expedition = destination["status_expedicao"] or ""

        partial_remanagement = bool(selected_items and len(selected_items) < len(available))
        pending_process_id = source_id
        pending_process = source
        if partial_remanagement:
            main_id = self.process_family_id(source)
            main = self.get_process(main_id)
            partial_number = self.next_partial_number(main_id)
            pending_proposal = f"{main['proposta']}-P{partial_number}"
            selected_weight = sum(
                int(item["quantidade"] or 1) * float(item["peso"] or 0)
                for item in selected_items
            )
            selected_quantity = sum(int(item["quantidade"] or 1) for item in selected_items)
            values = {
                "cliente": main["cliente"],
                "proposta": pending_proposal,
                "pedido_compra": main["pedido_compra"],
                "obra_site": main["obra_site"],
                "peso": selected_weight,
                "lote": main["lote"],
                "data_entrada": main["data_entrada"],
                "data_cadastro": now_br(),
                "prazo_entrega": main["prazo_entrega"],
                "status_geral": "EM_PRODUCAO",
                "status_producao": "ITEM_PENDENTE_FABRICACAO",
                "status_galvanizacao": "",
                "status_expedicao": "",
                "status_almoxarifado": "",
                "observacoes_gerais": main["observacoes_gerais"],
                "observacoes_producao": note_source,
                "situacao_fluxo": "PENDENTE_POR_REMANEJAMENTO",
                "tem_pendencia_producao": 1,
                "origem_remanejamento": destination["proposta"],
                "observacao_remanejamento": note_source,
                "processo_pai_id": main_id,
                "tipo_processo": "PARCIAL",
                "numero_parcial": partial_number,
                "peso_parcial": selected_weight,
                "saldo_pendente": selected_weight,
                "descricao_parcial": "Reposicao de itens remanejados",
                "quantidade_itens": selected_quantity,
                "peso_produzido": 0,
                "atualizado_em": now_br(),
                "atualizado_por": user["login"],
            }
            columns = ", ".join(values)
            placeholders = ", ".join("?" for _ in values)
            cursor = self.conn.execute(
                f"INSERT INTO processos({columns}) VALUES ({placeholders})",
                tuple(values.values()),
            )
            pending_process_id = cursor.lastrowid
            pending_process = self.get_process(pending_process_id)
            self.add_history(
                pending_process_id,
                pending_proposal,
                "PRODUCAO",
                "",
                "ITEM_PENDENTE_FABRICACAO",
                user,
                note_source,
            )
            self.add_audit(
                "processos",
                pending_process_id,
                "CRIACAO_REPOSICAO_REMANEJAMENTO",
                "processo_pai_id",
                "",
                str(main_id),
                user,
            )

        for item in selected_items:
            self.conn.execute(
                """
                INSERT INTO remanejamentos_itens(
                    processo_destino_id, processo_origem_id, item_id,
                    data_hora, usuario, observacao
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (destination_id, source_id, item["id"], now_br(), user["login"], observation),
            )
            self.conn.execute(
                """
                UPDATE proposta_itens
                SET processo_atual_id = ?, produzido = 0, galvanizado = 0, entregue = 0,
                    entregue_em = NULL, atualizado_em = ?, atualizado_por = ?
                WHERE id = ?
                """,
                (pending_process_id, now_br(), user["login"], item["id"]),
            )

        if selected_items:
            main_id = self.process_family_id(source)
            progress = self.item_progress(main_id)
            main = self.get_process(main_id)
            self.conn.execute(
                "UPDATE processos SET peso_produzido = ?, saldo_pendente = ? WHERE id = ?",
                (
                    progress["peso_produzido"],
                    max(0, float(progress["peso_total"] or main["peso"] or 0) - float(progress["peso_produzido"] or 0)),
                    main_id,
                ),
            )

        if partial_remanagement:
            self.conn.execute(
                """
                UPDATE processos
                SET observacoes_expedicao = ?, atualizado_em = ?, atualizado_por = ?
                WHERE id = ?
                """,
                (note_source, now_br(), user["login"], source_id),
            )
            self.add_history(
                source_id,
                source["proposta"],
                "EXPEDICAO",
                old_source_expedition,
                old_source_expedition,
                user,
                f"Remanejamento parcial; material restante permanece na Expedicao. Reposicao: {pending_process['proposta']}",
            )
        else:
            self.conn.execute(
                """
                UPDATE processos
                SET status_geral = ?, status_producao = ?,
                    status_galvanizacao = '', data_envio_galv = NULL, data_prevista_retorno_galv = NULL, data_retorno_galv = NULL,
                    status_expedicao = '', data_separacao = NULL, data_retirada = NULL,
                    observacoes_producao = ?, situacao_fluxo = ?, tem_pendencia_producao = ?,
                    origem_remanejamento = ?, observacao_remanejamento = ?,
                    atualizado_em = ?, atualizado_por = ?
                WHERE id = ?
                """,
                (
                    "EM_PRODUCAO",
                    "ITEM_PENDENTE_FABRICACAO",
                    note_source,
                    "PENDENTE_POR_REMANEJAMENTO",
                    1,
                    destination["proposta"],
                    note_source,
                    now_br(),
                    user["login"],
                    source_id,
                ),
            )
        self.conn.execute(
            """
            UPDATE processos
            SET status_geral = ?, status_producao = ?, data_final_producao = ?,
                status_expedicao = ?, data_separacao = ?, data_retirada = ?,
                observacoes_expedicao = ?, situacao_fluxo = ?, tem_pendencia_producao = ?,
                origem_remanejamento = ?, observacao_remanejamento = ?,
                atualizado_em = ?, atualizado_por = ?
            WHERE id = ?
            """,
            (
                "ENTREGUE",
                "FINALIZADO",
                today_br(),
                "ENTREGUE",
                today_br(),
                today_br(),
                note_destination,
                "CONCLUIDA",
                0,
                source["proposta"],
                note_destination,
                now_br(),
                user["login"],
                destination_id,
            ),
        )

        if not partial_remanagement:
            self.add_history(source_id, source["proposta"], "PRODUCAO", old_source_production, "ITEM_PENDENTE_FABRICACAO", user, note_source)
            if old_source_galvanization:
                self.add_history(source_id, source["proposta"], "GALVANIZACAO", old_source_galvanization, "", user, "Remanejada para repor material entregue antecipadamente")
            if old_source_expedition:
                self.add_history(source_id, source["proposta"], "EXPEDICAO", old_source_expedition, "", user, "Todo o material foi remanejado; proposta voltou para Producao")
        if old_destination_production != "FINALIZADO":
            self.add_history(destination_id, destination["proposta"], "PRODUCAO", old_destination_production, "FINALIZADO", user, "Atendida por material remanejado")
        self.add_history(destination_id, destination["proposta"], "EXPEDICAO", old_destination_expedition, "ENTREGUE", user, note_destination)
        self.add_history(destination_id, destination["proposta"], "CONTROLE GERAL", old_destination_general, "ENTREGUE", user, "Entrega antecipada por remanejamento")
        self.absorb_destination_partials_after_delivery(destination_id, user, "Principal entregue por remanejamento")
        self.add_audit(
            "processos",
            pending_process_id,
            "REMANEJAMENTO_ENTREGA_ANTECIPADA",
            "status_producao",
            old_source_production if not partial_remanagement else "",
            "ITEM_PENDENTE_FABRICACAO",
            user,
        )
        self.add_audit("processos", destination_id, "ENTREGA_ANTECIPADA", "status_expedicao", old_destination_expedition, "ENTREGUE", user)
        self.conn.commit()

    def absorb_destination_partials_after_delivery(self, parent_id, user, observation):
        parent = self.get_process(parent_id)
        if not parent:
            return
        partials = self.conn.execute(
            """
            SELECT * FROM processos
            WHERE processo_pai_id = ?
              AND COALESCE(status_geral, '') <> 'CANCELADA'
              AND COALESCE(status_expedicao, '') <> 'UNIFICADA_PRINCIPAL'
            """,
            (parent_id,),
        ).fetchall()
        for partial in partials:
            old_general = partial["status_geral"] or ""
            old_expedition = partial["status_expedicao"] or ""
            note = f"{observation}: vinculada a {parent['proposta']}."
            self.conn.execute(
                """
                UPDATE processos
                SET status_geral = ?, status_expedicao = ?, situacao_fluxo = ?,
                    tem_pendencia_producao = ?, observacoes_expedicao = ?,
                    atualizado_em = ?, atualizado_por = ?
                WHERE id = ?
                """,
                ("ENTREGUE", "UNIFICADA_PRINCIPAL", "UNIFICADA_NA_PRINCIPAL", 0, note, now_br(), user["login"], partial["id"]),
            )
            if old_expedition != "UNIFICADA_PRINCIPAL":
                self.add_history(partial["id"], partial["proposta"], "EXPEDICAO", old_expedition, "UNIFICADA_PRINCIPAL", user, note)
            if old_general != "ENTREGUE":
                self.add_history(partial["id"], partial["proposta"], "CONTROLE GERAL", old_general, "ENTREGUE", user, note)

    def acquire_process_lock(self, process_id, user, max_age_minutes=30):
        process = self.get_process(process_id)
        if not process:
            raise AppError("Processo nao encontrado.")
        stale_limit = (datetime.now() - timedelta(minutes=max_age_minutes)).isoformat(timespec="seconds")
        self.conn.execute("DELETE FROM bloqueios_edicao WHERE bloqueado_em < ?", (stale_limit,))
        owner = self.conn.execute(
            "SELECT * FROM bloqueios_edicao WHERE processo_id = ?", (process_id,)
        ).fetchone()
        if owner and (owner["usuario"], owner["computador"]) != (user["login"], self.computer):
            raise AppError(
                "Este processo esta sendo editado por "
                f"{owner['usuario']} no computador {owner['computador']} desde {owner['bloqueado_em']}."
            )
        self.conn.execute(
            """
            INSERT OR REPLACE INTO bloqueios_edicao(processo_id, usuario, computador, bloqueado_em)
            VALUES (?, ?, ?, ?)
            """,
            (process_id, user["login"], self.computer, now_iso()),
        )
        self.conn.commit()

    def release_process_lock(self, process_id, user):
        self.conn.execute(
            """
            DELETE FROM bloqueios_edicao
            WHERE processo_id = ? AND usuario = ? AND computador = ?
            """,
            (process_id, user["login"], self.computer),
        )
        self.conn.commit()

    def save_process(self, data, user, process_id=None, import_metadata=None):
        try:
            saved_id = self._save_process_without_commit(data, user, process_id)
            if import_metadata:
                if process_id:
                    raise AppError("A origem PDF Nomus so pode ser registrada na criacao do processo.")
                self.register_pdf_import(saved_id, data, import_metadata, user)
            self.conn.commit()
            return saved_id
        except Exception:
            self.conn.rollback()
            raise

    def _save_process_without_commit(self, data, user, process_id=None):
        if not user_can_edit_process(user):
            raise AppError("Seu usuario nao tem permissao para cadastrar ou editar dados de processos.")
        self.validate_process(data, process_id)
        previous = self.get_process(process_id) if process_id else None
        def note_value(field):
            if field in data:
                return data.get(field, "").strip()
            if previous:
                return previous[field] or ""
            return ""
        values = {
            "cliente": data["cliente"].strip(),
            "proposta": format_proposal(data["proposta"]),
            "pedido_compra": data.get("pedido_compra", "").strip(),
            "obra_site": data.get("obra_site", "").strip(),
            "peso": self.to_float(data.get("peso", "")),
            "lote": data.get("lote", "").strip(),
            "data_entrada": format_date_for_db(data.get("data_entrada", "")),
            "prazo_entrega": format_date_for_db(data.get("prazo_entrega", "")),
            "observacoes_gerais": note_value("observacoes_gerais"),
            "observacoes_producao": note_value("observacoes_producao"),
            "observacoes_galvanizacao": note_value("observacoes_galvanizacao"),
            "observacoes_expedicao": note_value("observacoes_expedicao"),
            "observacoes_almoxarifado": note_value("observacoes_almoxarifado"),
            "necessita_almoxarifado": normalize_stockroom_need(data.get("necessita_almoxarifado", previous["necessita_almoxarifado"] if previous and "necessita_almoxarifado" in previous.keys() else "NAO_DEFINIDO")),
            "atualizado_em": now_br(),
            "atualizado_por": user["login"],
        }
        if values["necessita_almoxarifado"] == "NAO":
            values["status_almoxarifado"] = "SEM_PARAFUSOS"
        elif values["necessita_almoxarifado"] == "SIM" and previous and (not (previous["status_almoxarifado"] or "") or previous["status_almoxarifado"] == "SEM_PARAFUSOS"):
            values["status_almoxarifado"] = "AGUARDANDO_CONFIRMACAO"
        if process_id:
            assignments = ", ".join(f"{key} = ?" for key in values)
            self.conn.execute(
                f"UPDATE processos SET {assignments} WHERE id = ?",
                tuple(values.values()) + (process_id,),
            )
            saved_id = process_id
            self.audit_process_update(saved_id, previous, values, user)
        else:
            stockroom_need = values.pop("necessita_almoxarifado", "NAO_DEFINIDO")
            initial_stockroom_status = ""
            if stockroom_need == "NAO":
                initial_stockroom_status = "SEM_PARAFUSOS"
            elif stockroom_need == "SIM":
                initial_stockroom_status = "AGUARDANDO_CONFIRMACAO"
            defaults = {
                "data_cadastro": now_br(),
                "status_geral": "NAO_LIBERADO",
                "status_producao": "",
                "status_galvanizacao": "",
                "status_expedicao": "",
                "status_almoxarifado": initial_stockroom_status,
                "necessita_almoxarifado": stockroom_need,
                "situacao_fluxo": "NORMAL",
                "tem_pendencia_producao": 0,
                "origem_remanejamento": "",
                "observacao_remanejamento": "",
                "processo_pai_id": None,
                "tipo_processo": "PRINCIPAL",
                "numero_parcial": 0,
                "peso_parcial": None,
                "saldo_pendente": None,
                "descricao_parcial": "",
            }
            all_values = {**defaults, **values}
            columns = ", ".join(all_values)
            placeholders = ", ".join("?" for _ in all_values)
            cur = self.conn.execute(
                f"INSERT INTO processos({columns}) VALUES ({placeholders})",
                tuple(all_values.values()),
            )
            saved_id = cur.lastrowid
            self.add_history(saved_id, all_values["proposta"], "CONTROLE GERAL", "", "NAO_LIBERADO", user, "Cadastro inicial")
            self.add_audit("processos", saved_id, "CRIACAO", "", "", all_values["proposta"], user)
        if "itens" in data:
            self.replace_proposal_items(saved_id, data.get("itens") or [], user)
        return saved_id

    def pdf_import_by_hash(self, hash_sha256):
        normalized = str(hash_sha256 or "").strip().lower()
        if not normalized:
            return None
        return self.conn.execute(
            "SELECT * FROM proposta_importacoes_pdf WHERE hash_sha256 = ?",
            (normalized,),
        ).fetchone()

    def register_pdf_import(self, process_id, process_data, metadata, user):
        origin = str(metadata.get("origem") or "").strip().upper()
        file_name = str(metadata.get("nome_arquivo") or "").strip()
        file_hash = str(metadata.get("hash_sha256") or "").strip().lower()
        observation = str(metadata.get("observacao") or "").strip()
        if origin != "NOMUS_PDF":
            raise AppError("Origem de importacao PDF invalida.")
        if not file_name or not file_hash:
            raise AppError("Nao foi possivel validar o nome e o hash do PDF Nomus.")
        if len(file_hash) != 64 or any(char not in "0123456789abcdef" for char in file_hash):
            raise AppError("Hash SHA-256 do PDF Nomus invalido.")
        previous = self.pdf_import_by_hash(file_hash)
        if previous:
            raise AppError("Este PDF Nomus ja foi utilizado em outro cadastro.")

        imported_at = now_br()
        self.conn.execute(
            """
            INSERT INTO proposta_importacoes_pdf(
                processo_id, origem, nome_arquivo, hash_sha256, importado_em,
                importado_por, observacao, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                process_id,
                origin,
                file_name,
                file_hash,
                imported_at,
                user["login"],
                observation,
                imported_at,
            ),
        )
        proposal = format_proposal(process_data.get("proposta", ""))
        history_note = (
            "Processo criado a partir de importacao PDF Nomus"
            f" | Arquivo: {file_name} | SHA-256: {file_hash}"
        )
        if observation:
            history_note += f" | Confirmacoes: {observation}"
        self.add_history(
            process_id,
            proposal,
            "CONTROLE GERAL",
            "",
            "IMPORTACAO_PDF_NOMUS",
            user,
            history_note,
        )
        self.add_audit(
            "proposta_importacoes_pdf",
            process_id,
            "IMPORTACAO_PDF_NOMUS",
            "hash_sha256",
            "",
            file_hash,
            user,
        )

    def validate_process(self, data, process_id=None):
        if not data.get("cliente", "").strip():
            raise AppError("Informe o cliente.")
        if not data.get("proposta", "").strip():
            raise AppError("Informe a proposta.")
        proposal = format_proposal(data["proposta"])
        existing_process = self.get_process(process_id) if process_id else None
        is_existing_partial = bool(existing_process and (existing_process["tipo_processo"] if "tipo_processo" in existing_process.keys() else "") == "PARCIAL")
        valid_main = proposal.startswith("CP") and proposal[2:].isdigit() and len(proposal) == 7
        valid_partial = "-P" in proposal and proposal.split("-P", 1)[0].startswith("CP") and proposal.split("-P", 1)[1].isdigit()
        if not valid_main and not (is_existing_partial and valid_partial):
            raise AppError("Use uma numeracao de proposta no padrao CP00000.")
        row = self.conn.execute(
            "SELECT id FROM processos WHERE proposta = ? AND (? IS NULL OR id <> ?)",
            (proposal, process_id, process_id),
        ).fetchone()
        if row:
            raise AppError("Ja existe um processo com essa proposta.")
        if data.get("data_entrada", "").strip():
            parse_date(data["data_entrada"])
        if data.get("prazo_entrega", "").strip():
            parse_date(data["prazo_entrega"])
        self.to_float(data.get("peso", ""))

    def to_float(self, value):
        value = str(value or "").strip().replace(",", ".")
        if not value:
            return None
        try:
            return float(value)
        except ValueError as exc:
            raise AppError("Peso deve ser numerico.") from exc

    def update_status(
        self,
        process_id,
        area,
        new_status,
        observation,
        user,
        allow_partial_delivery_completion=False,
        item_ids=None,
        produced_weight=None,
    ):
        process = self.get_process(process_id)
        if not process:
            raise AppError("Processo nao encontrado.")
        if area not in AREAS:
            raise AppError("Area invalida.")
        if process["status_geral"] == "CANCELADA" and area != "CONTROLE GERAL":
            raise AppError("Proposta cancelada so pode ser alterada pelo Controle Geral.")
        if not user_can_access_area(user, area):
            raise AppError(f"Seu usuario nao tem permissao para alterar status em {area.title()}.")
        if not self.area_available(process, area):
            raise AppError("Este processo ainda nao foi liberado para essa area.")
        new_status = normalize_status(new_status)
        if "CANCEL" in new_status and area != "CONTROLE GERAL":
            raise AppError("Cancelamento de proposta deve ser feito apenas no Controle Geral.")
        if new_status not in self.list_status(area):
            raise AppError("Status invalido para a area selecionada.")
        column = AREAS[area]["column"]
        old_status = normalize_status(process[column] or "")
        if old_status == new_status:
            raise AppError("O status selecionado ja esta aplicado.")
        if area == "GALVANIZACAO" and new_status == "RETORNOU_PARCIAL":
            raise AppError("O retorno parcial foi removido. Cada parcial retorna completa dentro do proprio subprocesso.")
        if area == "PRODUCAO" and new_status == "FINALIZADO_PARCIAL" and self.is_partial_process(process):
            raise AppError("Subprocesso parcial nao pode gerar outro subprocesso parcial.")
        if (
            area == "EXPEDICAO"
            and new_status == "ENTREGUE"
            and self.expedition_completion_requires_remanagement(process)
            and not (old_status == "ENTREGUE_PARCIAL" and (allow_partial_delivery_completion or self.expedition_delivery_can_close_after_customer_partial(process)))
        ):
            raise AppError("Proposta parcial ou com pendencia nao pode ir direto para Entregue. Primeiro use Entregue parcialmente e conclua pelo remanejamento quando necessario.")
        if (
            area == "EXPEDICAO"
            and old_status == "ENTREGUE_PARCIAL"
            and new_status == "ENTREGUE"
            and self.expedition_completion_requires_remanagement(process)
            and not (allow_partial_delivery_completion or self.expedition_delivery_can_close_after_customer_partial(process))
        ):
            raise AppError("Entrega completa de proposta parcial exige remanejamento de material pela tela de Expedicao.")
        self.validate_status_sequence(area, old_status, new_status)
        updates = {
            column: new_status,
            "atualizado_em": now_br(),
            "atualizado_por": user["login"],
        }
        date_column = AREAS[area]["date_columns"].get(new_status)
        if date_column:
            updates[date_column] = today_br()
        observation_column = AREAS[area]["observation_column"]
        if observation.strip():
            updates[observation_column] = observation.strip()
        updates.update(self.cascade_updates(area, new_status, process))
        if area == "ALMOXARIFADO":
            if new_status == "SEM_PARAFUSOS":
                updates["necessita_almoxarifado"] = "NAO"
            else:
                updates["necessita_almoxarifado"] = "SIM"
        if area != "CONTROLE GERAL":
            preview = {key: process[key] for key in process.keys()}
            preview.update(updates)
            geral = self.general_status_for(area, new_status, preview)
            if geral:
                updates["status_geral"] = geral
        preview = {key: process[key] for key in process.keys()}
        preview.update(updates)
        updates.update(self.flow_state_updates(preview))
        assignments = ", ".join(f"{key} = ?" for key in updates)
        self.conn.execute(
            f"UPDATE processos SET {assignments} WHERE id = ?",
            tuple(updates.values()) + (process_id,),
        )
        self.add_history(process_id, process["proposta"], area, old_status, new_status, user, observation)
        for auto_area, status_column in (
            ("PRODUCAO", "status_producao"),
            ("GALVANIZACAO", "status_galvanizacao"),
            ("EXPEDICAO", "status_expedicao"),
            ("ALMOXARIFADO", "status_almoxarifado"),
        ):
            if auto_area != area and status_column in updates and (process[status_column] or "") != (updates[status_column] or ""):
                self.add_history(
                    process_id,
                    process["proposta"],
                    auto_area,
                    process[status_column] or "",
                    updates[status_column] or "",
                    user,
                    "Liberacao automatica por cascata",
                )
        if area == "PRODUCAO" and new_status == "FINALIZADO_PARCIAL" and not self.is_partial_process(process):
            partial_id = self.create_partial_subprocess(
                process,
                user,
                observation,
                item_ids=item_ids,
                produced_weight=produced_weight,
            )
            if partial_id:
                self.add_history(
                    process_id,
                    process["proposta"],
                    "PRODUCAO",
                    new_status,
                    new_status,
                    user,
                    f"Subprocesso parcial criado: {process['proposta']}-P{self.next_partial_number(process_id) - 1}",
                )
        elif area == "PRODUCAO" and new_status == "FINALIZADO" and self.is_partial_process(process):
            self.conn.execute(
                """
                UPDATE proposta_itens
                SET produzido = 1, atualizado_em = ?, atualizado_por = ?
                WHERE processo_atual_id = ? AND entregue = 0
                """,
                (now_br(), user["login"], process_id),
            )
            progress = self.item_progress(process_id)
            completed_weight = float(produced_weight or 0) or float(progress["peso_produzido"] or 0) or float(process["peso"] or 0)
            self.conn.execute(
                "UPDATE processos SET peso_produzido = ?, saldo_pendente = 0, quantidade_itens = ? WHERE id = ?",
                (completed_weight, progress["total"], process_id),
            )
        elif area == "PRODUCAO" and new_status == "FINALIZADO" and not self.is_partial_process(process):
            has_partials = self.conn.execute(
                "SELECT COUNT(*) FROM processos WHERE processo_pai_id = ?",
                (process_id,),
            ).fetchone()[0]
            if has_partials:
                remaining_items = self.list_proposal_items(process_id, pending_production=True)
                partial_id = self.create_partial_subprocess(
                    process,
                    user,
                    observation or "Saldo final liberado.",
                    final_balance=True,
                    item_ids=[row["id"] for row in remaining_items] if remaining_items else None,
                    produced_weight=produced_weight,
                )
                if partial_id:
                    final_updates = {
                        "status_galvanizacao": "",
                        "status_expedicao": "",
                        "status_geral": "EM_GALVANIZACAO",
                        "situacao_fluxo": "NORMAL",
                        "tem_pendencia_producao": 0,
                    }
                    final_assignments = ", ".join(f"{key} = ?" for key in final_updates)
                    self.conn.execute(
                        f"UPDATE processos SET {final_assignments} WHERE id = ?",
                        tuple(final_updates.values()) + (process_id,),
                    )
                    self.add_history(
                        process_id,
                        process["proposta"],
                        "PRODUCAO",
                        new_status,
                        new_status,
                        user,
                        "Saldo final criado como subprocesso parcial para seguir nas proximas areas.",
                    )
            else:
                self.conn.execute(
                    "UPDATE proposta_itens SET produzido = 1, processo_atual_id = ?, atualizado_em = ?, atualizado_por = ? WHERE processo_principal_id = ? AND entregue = 0",
                    (process_id, now_br(), user["login"], process_id),
                )
                progress = self.item_progress(process_id)
                completed_weight = float(produced_weight or 0) or float(progress["peso_produzido"] or 0) or float(process["peso"] or 0)
                self.conn.execute(
                    "UPDATE processos SET peso_produzido = ?, saldo_pendente = 0, quantidade_itens = ? WHERE id = ?",
                    (completed_weight, progress["total"], process_id),
                )
        elif area == "EXPEDICAO" and new_status == "ENTREGUE" and self.is_partial_process(process):
            self.refresh_parent_completion(process["processo_pai_id"], user)
        if area in ("GALVANIZACAO", "EXPEDICAO") or "status_expedicao" in updates:
            self.try_auto_merge_expedition_partials(process_id, user)
        if area == "GALVANIZACAO" and new_status == "RETORNOU_GALVANIZACAO":
            returned_process = self.get_process(process_id)
            if returned_process:
                self.ensure_fiscal_entry_for_process(
                    process_id,
                    user,
                    observation or "Entrada fiscal automatica pelo retorno da galvanizacao.",
                )
        self.conn.commit()

    def stockroom_delivery_required(self, process):
        need = normalize_stockroom_need(process["necessita_almoxarifado"] if "necessita_almoxarifado" in process.keys() else "NAO_DEFINIDO")
        if need == "NAO":
            return False
        status = normalize_status(process["status_almoxarifado"] or "")
        return bool(status) and status not in ("SEM_PARAFUSOS", "ALMOXARIFADO_ENTREGUE")

    def confirm_stockroom_delivery(self, process_id, user, observation="Confirmacao de entrega junto com a Expedicao"):
        process = self.get_process(process_id)
        if not process or not self.stockroom_delivery_required(process):
            return False
        old_status = normalize_status(process["status_almoxarifado"] or "")
        updates = {
            "status_almoxarifado": "ALMOXARIFADO_ENTREGUE",
            "necessita_almoxarifado": "SIM",
            "data_retirada": today_br(),
            "observacoes_almoxarifado": observation,
            "atualizado_em": now_br(),
            "atualizado_por": user["login"],
        }
        assignments = ", ".join(f"{key} = ?" for key in updates)
        self.conn.execute(
            f"UPDATE processos SET {assignments} WHERE id = ?",
            tuple(updates.values()) + (process_id,),
        )
        self.add_history(process_id, process["proposta"], "ALMOXARIFADO", old_status, "ALMOXARIFADO_ENTREGUE", user, observation)
        self.add_audit("processos", process_id, "CONFIRMACAO_ALMOXARIFADO", "status_almoxarifado", old_status, "ALMOXARIFADO_ENTREGUE", user)
        self.conn.commit()
        return True

    def validate_status_sequence(self, area, old_status, new_status):
        if area == "CONTROLE GERAL" and new_status == "CANCELADA":
            return
        if area == "PRODUCAO" and new_status == "ITEM_PENDENTE_FABRICACAO":
            raise AppError("Item pendente de fabricacao e gerado apenas pelo remanejamento de material.")
        if area == "PRODUCAO" and old_status == "FINALIZADO_PARCIAL" and new_status == "FINALIZADO":
            return
        allowed_next = self.allowed_status_transitions(area, old_status)
        if allowed_next:
            if new_status not in allowed_next:
                allowed = ", ".join(area_status_label(area, status) for status in allowed_next)
                raise AppError(f"Proximo status permitido: {allowed}.")
            return
        flow = STATUS_FLOW_ORDER.get(area, [])
        if not flow:
            return
        if new_status not in flow:
            raise AppError("Status fora da sequencia permitida para esta area.")
        if not old_status:
            if new_status != flow[0]:
                raise AppError(f"O primeiro status da area deve ser {area_status_label(area, flow[0])}.")
            return
        if old_status not in flow:
            return
        old_index = flow.index(old_status)
        new_index = flow.index(new_status)
        if new_index < old_index:
            raise AppError("Nao e permitido voltar status na sequencia. Use observacao ou procure o Controle Geral.")
        if new_index > old_index + 1:
            raise AppError("Avance apenas para o proximo status da sequencia.")

    def list_galvanization_load_candidates(self):
        rows = self.list_processes({"area": "GALVANIZACAO", "status_area": "GALVANIZACAO"})
        blocked = {"EM_CARGA", "ENVIADO_GALVANIZACAO", "RETORNOU_GALVANIZACAO", "RETORNOU_PARCIAL"}
        return [
            row
            for row in rows
            if self.visible_for_area(row, "GALVANIZACAO")
            and (row["status_galvanizacao"] or "") not in blocked
        ]

    def create_galvanization_load(self, driver, max_weight, expected_return_date, items, user):
        return self.save_galvanization_load(driver, max_weight, expected_return_date, items, user)

    def list_galvanization_loads(self):
        return self.conn.execute(
            """
            SELECT c.*, COUNT(i.id) AS item_count
            FROM cargas_galvanizacao c
            LEFT JOIN cargas_galvanizacao_itens i ON i.carga_id = c.id
            GROUP BY c.id
            ORDER BY c.id DESC
            """
        ).fetchall()

    def get_galvanization_load(self, load_id):
        return self.conn.execute("SELECT * FROM cargas_galvanizacao WHERE id = ?", (load_id,)).fetchone()

    def list_galvanization_load_items(self, load_id):
        return self.conn.execute(
            "SELECT * FROM cargas_galvanizacao_itens WHERE carga_id = ? ORDER BY proposta, id",
            (load_id,),
        ).fetchall()

    def list_galvanization_load_proposal_items(self, load_id, process_id):
        linked = self.conn.execute(
            "SELECT 1 FROM cargas_galvanizacao_itens WHERE carga_id = ? AND processo_id = ?",
            (load_id, process_id),
        ).fetchone()
        if not linked:
            return []
        process = self.get_process(process_id)
        if not process:
            return []
        main_id = self.process_main_id(process)
        if self.is_partial_process(process):
            return self.conn.execute(
                """
                SELECT * FROM proposta_itens
                WHERE processo_principal_id = ? AND processo_atual_id = ?
                ORDER BY CAST(numero_item AS INTEGER), numero_item, id
                """,
                (main_id, process_id),
            ).fetchall()
        return self.conn.execute(
            """
            SELECT * FROM proposta_itens
            WHERE processo_principal_id = ? AND processo_atual_id = ?
            ORDER BY CAST(numero_item AS INTEGER), numero_item, id
            """,
            (main_id, process_id),
        ).fetchall()

    def current_galvanization_load_id(self, process_id):
        row = self.conn.execute(
            """
            SELECT c.id
            FROM cargas_galvanizacao_itens i
            JOIN cargas_galvanizacao c ON c.id = i.carga_id
            WHERE i.processo_id = ?
              AND c.status IN ('AGUARDANDO_LIBERACAO', 'LIBERADA_PARA_ENVIO')
            ORDER BY c.id DESC
            LIMIT 1
            """,
            (process_id,),
        ).fetchone()
        return int(row["id"]) if row else None

    def current_galvanization_load_ids(self, process_ids):
        ids = [int(process_id) for process_id in process_ids]
        if not ids:
            return {}
        placeholders = ", ".join("?" for _ in ids)
        rows = self.conn.execute(
            f"""
            SELECT i.processo_id, MAX(c.id) AS carga_id
            FROM cargas_galvanizacao_itens i
            JOIN cargas_galvanizacao c ON c.id = i.carga_id
            WHERE i.processo_id IN ({placeholders})
              AND c.status IN ('AGUARDANDO_LIBERACAO', 'LIBERADA_PARA_ENVIO')
            GROUP BY i.processo_id
            """,
            tuple(ids),
        ).fetchall()
        return {int(row["processo_id"]): int(row["carga_id"]) for row in rows}

    def save_galvanization_load(self, driver, max_weight, expected_return_date, items, user, load_id=None):
        if not user_can_mount_galvanization_load(user):
            raise AppError("Seu usuario nao tem permissao para montar carga de galvanizacao.")
        driver = (driver or "").strip()
        if not driver:
            raise AppError("Informe o nome do motorista.")
        if not items:
            raise AppError("Adicione pelo menos uma proposta na carga.")
        max_weight = self.to_float(max_weight)
        if max_weight is not None and max_weight <= 0:
            raise AppError("A capacidade do caminhao deve ser maior que zero.")
        expected_return_date = format_date_for_db(expected_return_date or "")
        if load_id:
            existing_load = self.get_galvanization_load(load_id)
            if not existing_load:
                raise AppError("Carga nao encontrada.")
            if existing_load["status"] != "AGUARDANDO_LIBERACAO":
                raise AppError("Apenas cargas aguardando liberacao podem ser editadas.")
        grouped = {}
        for item in items:
            process_id = int(item["process_id"])
            sent_weight = self.to_float(item.get("peso_enviado", ""))
            observation = (item.get("observacao") or "").strip()
            if process_id not in grouped:
                grouped[process_id] = {"process_id": process_id, "peso_enviado": 0.0, "observacao": observation}
            if sent_weight is not None:
                grouped[process_id]["peso_enviado"] += sent_weight
            if observation and observation not in grouped[process_id]["observacao"]:
                grouped[process_id]["observacao"] = " | ".join(filter(None, [grouped[process_id]["observacao"], observation]))
        normalized = []
        total_weight = 0.0
        for item in grouped.values():
            process = self.get_process(item["process_id"])
            if not process:
                raise AppError(f"Processo {item['process_id']} nao encontrado.")
            if not self.area_available(process, "GALVANIZACAO"):
                raise AppError(f"A proposta {process['proposta']} ainda nao esta liberada para galvanizacao.")
            sent_weight = self.to_float(item.get("peso_enviado", ""))
            proposal_weight = process["peso"] or 0
            if sent_weight is None:
                sent_weight = proposal_weight
            if sent_weight <= 0:
                raise AppError(f"Informe um peso enviado maior que zero para a proposta {process['proposta']}.")
            if proposal_weight and sent_weight > proposal_weight:
                raise AppError(f"O peso enviado da proposta {process['proposta']} e maior que o peso cadastrado.")
            duplicate_load = self.conn.execute(
                """
                SELECT c.id, c.status
                FROM cargas_galvanizacao_itens i
                JOIN cargas_galvanizacao c ON c.id = i.carga_id
                WHERE i.processo_id = ?
                  AND c.status IN ('AGUARDANDO_LIBERACAO', 'LIBERADA_PARA_ENVIO')
                  AND (? IS NULL OR c.id <> ?)
                LIMIT 1
                """,
                (process["id"], load_id, load_id),
            ).fetchone()
            if duplicate_load:
                raise AppError(f"A proposta {process['proposta']} ja esta na carga {duplicate_load['id']} em andamento.")
            partial = 1 if proposal_weight and sent_weight < proposal_weight else 0
            total_weight += sent_weight
            normalized.append((process, sent_weight, partial, (item.get("observacao") or "").strip()))
        if max_weight is not None and total_weight > max_weight:
            raise AppError("O peso total da carga ultrapassa a capacidade do caminhao.")
        previous_item_ids = set()
        if load_id:
            previous_item_ids = {row["processo_id"] for row in self.list_galvanization_load_items(load_id)}
            self.conn.execute(
                """
                UPDATE cargas_galvanizacao
                SET motorista = ?, peso_maximo = ?, peso_total = ?, data_prevista_retorno = ?, computador = ?
                WHERE id = ?
                """,
                (driver, max_weight, total_weight, expected_return_date, self.computer, load_id),
            )
            self.conn.execute("DELETE FROM cargas_galvanizacao_itens WHERE carga_id = ?", (load_id,))
        else:
            cur = self.conn.execute(
                """
                INSERT INTO cargas_galvanizacao(
                    motorista, peso_maximo, peso_total, status, data_prevista_retorno,
                    criado_em, criado_por, computador, observacao
                ) VALUES (?, ?, ?, 'AGUARDANDO_LIBERACAO', ?, ?, ?, ?, ?)
                """,
                (driver, max_weight, total_weight, expected_return_date, now_br(), user["login"], self.computer, ""),
            )
            load_id = cur.lastrowid
        current_item_ids = {process["id"] for process, _sent_weight, _partial, _obs in normalized}
        for removed_id in previous_item_ids - current_item_ids:
            removed = self.get_process(removed_id)
            if removed and removed["status_galvanizacao"] == "EM_CARGA":
                restore_status = "DISPONIVEL_PARCIAL" if (
                    removed["status_producao"] == "FINALIZADO_PARCIAL"
                    or ((removed["tipo_processo"] if "tipo_processo" in removed.keys() else "") == "PARCIAL" and removed["situacao_fluxo"] == "PARCIAL_EM_ANDAMENTO")
                ) else "AGUARDANDO_ENVIO"
                self.conn.execute(
                    """
                    UPDATE processos
                    SET status_galvanizacao = ?, atualizado_em = ?, atualizado_por = ?
                    WHERE id = ?
                    """,
                    (restore_status, now_br(), user["login"], removed_id),
                )
                self.add_history(removed_id, removed["proposta"], "GALVANIZACAO", "EM_CARGA", restore_status, user, f"Removida da carga {load_id}")
        for process, sent_weight, partial, item_observation in normalized:
            self.conn.execute(
                """
                INSERT INTO cargas_galvanizacao_itens(
                    carga_id, processo_id, proposta, cliente, peso_total_proposta,
                    peso_enviado, parcial, observacao
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    load_id,
                    process["id"],
                    process["proposta"],
                    process["cliente"],
                    process["peso"],
                    sent_weight,
                    partial,
                    item_observation,
                ),
            )
            old_status = process["status_galvanizacao"] or ""
            new_status = "EM_CARGA"
            note_parts = [f"Carga {load_id} aguardando liberacao", f"Motorista: {driver}", f"Peso na carga: {sent_weight:g}"]
            if process["peso"]:
                note_parts.append(f"Peso total proposta: {process['peso']:g}")
            if partial:
                note_parts.append("Envio parcial")
            if item_observation:
                note_parts.append(item_observation)
            observation = " | ".join(note_parts)
            self.conn.execute(
                """
                UPDATE processos
                SET status_galvanizacao = ?, observacoes_galvanizacao = ?, atualizado_em = ?, atualizado_por = ?
                WHERE id = ?
                """,
                (new_status, observation, now_br(), user["login"], process["id"]),
            )
            if old_status != new_status:
                self.add_history(process["id"], process["proposta"], "GALVANIZACAO", old_status, new_status, user, observation)
        self.conn.commit()
        return load_id

    def release_galvanization_load(self, load_id, user):
        if not user_can_mount_galvanization_load(user):
            raise AppError("Seu usuario nao tem permissao para liberar carga de galvanizacao.")
        load = self.get_galvanization_load(load_id)
        if not load:
            raise AppError("Carga nao encontrada.")
        if load["status"] != "AGUARDANDO_LIBERACAO":
            raise AppError("Somente cargas aguardando liberacao podem ser liberadas.")
        items = self.list_galvanization_load_items(load_id)
        if not items:
            raise AppError("A carga nao possui propostas.")
        returned_process_ids = []
        for item in items:
            process = self.get_process(item["processo_id"])
            if not process:
                continue
            returned_process_ids.append(process["id"])
            old_status = process["status_galvanizacao"] or ""
            new_status = "ENVIADO_GALVANIZACAO"
            observation = (
                f"Carga {load_id} liberada para envio | Motorista: {load['motorista']} | "
                f"Peso enviado: {float(item['peso_enviado'] or 0):g}"
            )
            if load["data_prevista_retorno"]:
                observation += f" | Prev. retorno: {load['data_prevista_retorno']}"
            self.conn.execute(
                """
                UPDATE processos
                SET status_galvanizacao = ?, data_envio_galv = ?, data_prevista_retorno_galv = ?, observacoes_galvanizacao = ?,
                    atualizado_em = ?, atualizado_por = ?, status_geral = ?
                WHERE id = ?
                """,
                (new_status, today_br(), load["data_prevista_retorno"] or "", observation, now_br(), user["login"], "EM_GALVANIZACAO", process["id"]),
            )
            if old_status != new_status:
                self.add_history(process["id"], process["proposta"], "GALVANIZACAO", old_status, new_status, user, observation)
        self.conn.execute(
            "UPDATE cargas_galvanizacao SET status = ?, observacao = ? WHERE id = ?",
            ("LIBERADA_PARA_ENVIO", f"Liberada em {now_br()} por {user['login']}", load_id),
        )
        self.conn.commit()

    def mark_galvanization_load_returned(self, load_id, user):
        try:
            if not user_can_mount_galvanization_load(user):
                raise AppError("Seu usuario nao tem permissao para marcar retorno de carga.")
            load = self.get_galvanization_load(load_id)
            if not load:
                raise AppError("Carga nao encontrada.")
            if load["status"] != "LIBERADA_PARA_ENVIO":
                raise AppError("Somente cargas liberadas para envio podem ser marcadas como retornadas.")
            items = self.list_galvanization_load_items(load_id)
            if not items:
                raise AppError("A carga nao possui propostas.")
            returned_process_ids = []
            for item in items:
                process = self.get_process(item["processo_id"])
                if not process:
                    continue
                returned_process_ids.append(process["id"])
                old_status = process["status_galvanizacao"] or ""
                new_status = "RETORNOU_GALVANIZACAO"
                expedition_status = "EM_SEPARACAO"
                observation = f"Carga {load_id} retornou da galvanizacao | Motorista: {load['motorista']}"
                self.conn.execute(
                    """
                    UPDATE processos
                    SET status_galvanizacao = ?, data_retorno_galv = ?, observacoes_galvanizacao = ?,
                        status_expedicao = CASE WHEN COALESCE(status_expedicao, '') = '' THEN ? ELSE status_expedicao END,
                        atualizado_em = ?, atualizado_por = ?, status_geral = ?
                    WHERE id = ?
                    """,
                    (new_status, today_br(), observation, expedition_status, now_br(), user["login"], "EM_EXPEDICAO", process["id"]),
                )
                self.conn.execute(
                    "UPDATE proposta_itens SET galvanizado = 1, atualizado_em = ?, atualizado_por = ? WHERE processo_atual_id = ? AND produzido = 1",
                    (now_br(), user["login"], process["id"]),
                )
                if old_status != new_status:
                    self.add_history(process["id"], process["proposta"], "GALVANIZACAO", old_status, new_status, user, observation)
                if not process["status_expedicao"]:
                    self.add_history(process["id"], process["proposta"], "EXPEDICAO", "", expedition_status, user, "Liberacao automatica pelo retorno da carga")
                returned_process = self.get_process(process["id"])
                if returned_process:
                    self.ensure_fiscal_entry_for_process(returned_process["id"], user, observation)
            for process_id in returned_process_ids:
                self.try_auto_merge_expedition_partials(process_id, user)
            self.conn.execute(
                "UPDATE cargas_galvanizacao SET status = ?, data_retorno = ?, observacao = ? WHERE id = ?",
                ("RETORNADA_GALVANIZACAO", today_br(), f"Retornada em {now_br()} por {user['login']}", load_id),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def remanage_material_to_production(self, process_id, user, observation="", destination_process=None):
        if not user_can_access_area(user, "EXPEDICAO"):
            raise AppError("Seu usuario nao tem permissao para remanejar material para producao.")
        process = self.get_process(process_id)
        if not process:
            raise AppError("Processo nao encontrado.")
        if process["status_geral"] == "CANCELADA":
            raise AppError("Proposta cancelada nao pode ser remanejada.")
        if process["status_producao"] != "FINALIZADO":
            raise AppError("O remanejamento so pode retirar material de proposta ja finalizada na Producao.")
        if destination_process and self.same_process_family(process, destination_process):
            raise AppError("Nao e permitido remanejar material entre a proposta principal e as parciais dela mesma.")
        old_production = process["status_producao"] or ""
        old_galvanization = process["status_galvanizacao"] or ""
        old_expedition = process["status_expedicao"] or ""
        if not observation.strip():
            raise AppError("Informe os itens remanejados.")
        note = observation.strip()
        destination_label = ""
        if destination_process:
            destination_label = destination_process["proposta"] if "proposta" in destination_process.keys() else str(destination_process)
            note = f"{note} | Material usado para concluir {destination_label}"
        self.conn.execute(
            """
            UPDATE processos
            SET status_geral = ?, status_producao = ?,
                status_galvanizacao = '', data_envio_galv = NULL, data_prevista_retorno_galv = NULL, data_retorno_galv = NULL,
                status_expedicao = '', data_separacao = NULL, data_retirada = NULL,
                observacoes_producao = ?, situacao_fluxo = ?, tem_pendencia_producao = ?, origem_remanejamento = ?,
                observacao_remanejamento = ?, atualizado_em = ?, atualizado_por = ?
            WHERE id = ?
            """,
            ("EM_PRODUCAO", "ITEM_PENDENTE_FABRICACAO", note, "PENDENTE_POR_REMANEJAMENTO", 1, destination_label, note, now_br(), user["login"], process_id),
        )
        if old_production != "ITEM_PENDENTE_FABRICACAO":
            self.add_history(process_id, process["proposta"], "PRODUCAO", old_production, "ITEM_PENDENTE_FABRICACAO", user, note)
        if old_galvanization:
            self.add_history(process_id, process["proposta"], "GALVANIZACAO", old_galvanization, "", user, "Remanejada para producao")
        if old_expedition:
            self.add_history(process_id, process["proposta"], "EXPEDICAO", old_expedition, "", user, "Remanejada para producao")
        self.add_audit("processos", process_id, "REMANEJAMENTO", "status_producao", old_production, "ITEM_PENDENTE_FABRICACAO", user)
        self.merge_partial_back_to_parent_production(process_id, user, note)
        self.conn.commit()

    def merge_partial_back_to_parent_production(self, process_id, user, observation):
        process = self.get_process(process_id)
        if not process or not self.is_partial_process(process):
            return False
        parent_id = process["processo_pai_id"]
        parent = self.get_process(parent_id)
        if not parent:
            return False
        parent_in_production = (parent["status_producao"] or "") in ("NAO_INICIADO", "INICIADO", "PARADO", "ITEM_PENDENTE_FABRICACAO", "FINALIZADO_PARCIAL")
        if not parent_in_production:
            return False
        parent_old = parent["status_producao"] or ""
        partial_old_general = process["status_geral"] or ""
        partial_old_production = process["status_producao"] or ""
        note = f"Parcial {process['proposta']} reagregada na principal {parent['proposta']} por remanejamento. {observation or ''}".strip()
        self.conn.execute(
            """
            UPDATE processos
            SET status_geral = ?, status_producao = ?, situacao_fluxo = ?,
                tem_pendencia_producao = ?, observacoes_producao = ?,
                atualizado_em = ?, atualizado_por = ?
            WHERE id = ?
            """,
            ("EM_PRODUCAO", "ITEM_PENDENTE_FABRICACAO", "PENDENTE_POR_REMANEJAMENTO", 1, note, now_br(), user["login"], parent_id),
        )
        self.conn.execute(
            """
            UPDATE processos
            SET status_geral = ?, status_producao = ?, status_galvanizacao = ?,
                status_expedicao = ?, situacao_fluxo = ?, tem_pendencia_producao = ?,
                observacoes_producao = ?, atualizado_em = ?, atualizado_por = ?
            WHERE id = ?
            """,
            ("ENTREGUE", "ITEM_PENDENTE_FABRICACAO", "", "UNIFICADA_PRINCIPAL", "UNIFICADA_NA_PRINCIPAL", 0, note, now_br(), user["login"], process_id),
        )
        if parent_old != "ITEM_PENDENTE_FABRICACAO":
            self.add_history(parent_id, parent["proposta"], "PRODUCAO", parent_old, "ITEM_PENDENTE_FABRICACAO", user, note)
        self.add_history(process_id, process["proposta"], "PRODUCAO", partial_old_production, "ITEM_PENDENTE_FABRICACAO", user, note)
        self.add_history(process_id, process["proposta"], "CONTROLE GERAL", partial_old_general, "ENTREGUE", user, note)
        self.add_history(process_id, process["proposta"], "EXPEDICAO", process["status_expedicao"] or "", "UNIFICADA_PRINCIPAL", user, note)
        return True

    def area_available(self, process, area):
        if process["status_geral"] == "CANCELADA" and area != "CONTROLE GERAL":
            return False
        if area == "CONTROLE GERAL":
            return True
        if area in ("PRODUCAO", "ALMOXARIFADO"):
            return process["status_geral"] in (
                "LIBERADO_PRODUCAO",
                "EM_PRODUCAO",
                "EM_GALVANIZACAO",
                "EM_EXPEDICAO",
                "ENTREGUE",
            )
        if area == "GALVANIZACAO":
            return process["status_producao"] in (CLOSED_PRODUCTION_STATUS | {"FINALIZADO_PARCIAL"}) or bool(process["status_galvanizacao"])
        if area == "EXPEDICAO":
            return process["status_galvanizacao"] in (CLOSED_GALVANIZATION_STATUS | {"RETORNOU_PARCIAL"}) or bool(process["status_expedicao"])
        return False

    def visible_for_area(self, process, area):
        if area == "CONTROLE GERAL":
            return True
        if area == "ALMOXARIFADO":
            need = normalize_stockroom_need(process["necessita_almoxarifado"] if "necessita_almoxarifado" in process.keys() else "")
            status = normalize_status(process["status_almoxarifado"] or "")
            if need == "NAO" or status in ("SEM_PARAFUSOS", "ALMOXARIFADO_ENTREGUE"):
                return False
            return self.area_available(process, area)
        if (
            (process["tipo_processo"] or "PRINCIPAL") == "PRINCIPAL"
            and self.list_active_child_partials(process["id"])
            and not (area == "PRODUCAO" and self.principal_still_in_production(process))
        ):
            return False
        if process["status_geral"] == "ENTREGUE":
            return False
        status = process[AREAS[area]["column"]] or ""
        if status in AREA_FINISHED_STATUS.get(area, set()):
            return False
        return self.area_available(process, area)

    def visible_area_count(self, area):
        if area not in AREAS:
            return 0
        return sum(1 for row in self.list_processes() if self.visible_for_area(row, area))

    def cascade_updates(self, area, status, process):
        updates = {}
        if area == "CONTROLE GERAL" and status == "LIBERADO_PRODUCAO":
            if not process["status_producao"]:
                updates["status_producao"] = "NAO_INICIADO"
            need = normalize_stockroom_need(process["necessita_almoxarifado"] if "necessita_almoxarifado" in process.keys() else "NAO_DEFINIDO")
            if need == "NAO":
                updates["status_almoxarifado"] = "SEM_PARAFUSOS"
            elif not process["status_almoxarifado"]:
                updates["status_almoxarifado"] = "AGUARDANDO_CONFIRMACAO"
        elif area == "CONTROLE GERAL" and status == "NAO_LIBERADO":
            updates.update(
                {
                    "status_producao": "",
                    "status_galvanizacao": "",
                    "status_expedicao": "",
                    "status_almoxarifado": "",
                }
            )
        elif area == "PRODUCAO" and status in CLOSED_PRODUCTION_STATUS:
            if not process["status_galvanizacao"]:
                updates["status_galvanizacao"] = "AGUARDANDO_ENVIO"
            elif process["status_galvanizacao"] == "DISPONIVEL_PARCIAL":
                updates["status_galvanizacao"] = "AGUARDANDO_ENVIO"
        elif area == "PRODUCAO" and status == "FINALIZADO_PARCIAL":
            if self.is_partial_process(process) and not process["status_galvanizacao"]:
                updates["status_galvanizacao"] = "DISPONIVEL_PARCIAL"
        elif area == "GALVANIZACAO" and status in CLOSED_GALVANIZATION_STATUS:
            if not process["status_expedicao"]:
                updates["status_expedicao"] = "EM_SEPARACAO"
        elif area == "GALVANIZACAO" and status == "RETORNOU_PARCIAL":
            if not process["status_expedicao"]:
                updates["status_expedicao"] = "AGUARDANDO_SEPARACAO_PARCIAL"
        return updates

    def flow_state_updates(self, process):
        status_geral = process.get("status_geral", "")
        status_producao = process.get("status_producao", "")
        status_galvanizacao = process.get("status_galvanizacao", "")
        status_expedicao = process.get("status_expedicao", "")
        if status_geral == "CANCELADA":
            situacao = "CANCELADA_FLUXO"
            pending = 0
        elif status_expedicao == "UNIFICADA_PRINCIPAL":
            situacao = "UNIFICADA_NA_PRINCIPAL"
            pending = 0
        elif status_expedicao == "ENTREGUE":
            situacao = "CONCLUIDA"
            pending = 0
        elif status_producao == "ITEM_PENDENTE_FABRICACAO":
            situacao = "PENDENTE_POR_REMANEJAMENTO"
            pending = 1
        elif status_producao == "FINALIZADO_PARCIAL":
            situacao = "PARCIAL_COM_PENDENCIA"
            pending = 1
        elif status_galvanizacao in ("DISPONIVEL_PARCIAL", "RETORNOU_PARCIAL") or status_expedicao in ("AGUARDANDO_SEPARACAO_PARCIAL", "ENTREGUE_PARCIAL"):
            situacao = "PARCIAL_EM_ANDAMENTO"
            pending = 0
        else:
            situacao = "NORMAL"
            pending = 0
        return {"situacao_fluxo": situacao, "tem_pendencia_producao": pending}

    def general_status_for(self, area, status, process=None):
        process = process or {}
        if process.get("status_producao") in ("FINALIZADO_PARCIAL", "ITEM_PENDENTE_FABRICACAO"):
            return "EM_PRODUCAO"
        if area == "PRODUCAO" and status == "FINALIZADO":
            return "EM_GALVANIZACAO"
        if area == "PRODUCAO" and status in ("NAO_INICIADO", "ITEM_PENDENTE_FABRICACAO", "INICIADO", "PARADO", "FINALIZADO_PARCIAL"):
            return "EM_PRODUCAO"
        if area == "GALVANIZACAO" and status in CLOSED_GALVANIZATION_STATUS:
            return "EM_EXPEDICAO"
        if area == "GALVANIZACAO" and status not in ("",):
            return "EM_GALVANIZACAO"
        if area == "EXPEDICAO" and status in ("EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARACAO_INICIADA", "SEPARADO", "ENTREGUE_PARCIAL"):
            return "EM_EXPEDICAO"
        if area == "EXPEDICAO" and status == "ENTREGUE":
            return "ENTREGUE"
        return None

    def add_history(self, process_id, proposal, area, old_status, new_status, user, observation=""):
        self.conn.execute(
            """
            INSERT INTO historico_status(
                processo_id, proposta, area, status_anterior, status_novo,
                data_hora, usuario, computador, observacao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                process_id,
                proposal,
                area,
                old_status,
                new_status,
                now_br(),
                user["login"],
                socket.gethostname(),
                observation or "",
            ),
        )

    def add_audit(self, entity, entity_id, action, field, old_value, new_value, user):
        self.conn.execute(
            """
            INSERT INTO auditoria(
                entidade, entidade_id, acao, campo, valor_anterior, valor_novo,
                data_hora, usuario, computador
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity,
                entity_id,
                action,
                field or "",
                "" if old_value is None else str(old_value),
                "" if new_value is None else str(new_value),
                now_br(),
                user["login"],
                self.computer,
            ),
        )

    def audit_process_update(self, process_id, previous, values, user):
        if not previous:
            return
        for field, new_value in values.items():
            if field in ("atualizado_em", "atualizado_por"):
                continue
            old_value = previous[field]
            if ("" if old_value is None else str(old_value)) != ("" if new_value is None else str(new_value)):
                self.add_audit("processos", process_id, "ALTERACAO", field, old_value, new_value, user)

    def history(self, process_id=None):
        if process_id:
            return self.conn.execute(
                "SELECT * FROM historico_status WHERE processo_id = ? ORDER BY id DESC",
                (process_id,),
            ).fetchall()
        return self.conn.execute("SELECT * FROM historico_status ORDER BY id DESC LIMIT 300").fetchall()

    def audit(self):
        return self.conn.execute("SELECT * FROM auditoria ORDER BY id DESC LIMIT 300").fetchall()

    def dashboard(self):
        today = date.today().isoformat()
        next_week = (date.today() + timedelta(days=7)).isoformat()
        due_expr = "date(substr(prazo_entrega, 7, 4) || '-' || substr(prazo_entrega, 4, 2) || '-' || substr(prazo_entrega, 1, 2))"
        total = self.conn.execute("SELECT COUNT(*) FROM processos").fetchone()[0]
        active = self.conn.execute(
            "SELECT COUNT(*) FROM processos WHERE COALESCE(status_geral, '') NOT IN ('ENTREGUE', 'CANCELADA', 'FINALIZADO')"
        ).fetchone()[0]
        overdue = self.conn.execute(
            f"""
            SELECT COUNT(*) FROM processos
            WHERE prazo_entrega <> ''
              AND COALESCE(status_geral, '') NOT IN ('ENTREGUE', 'CANCELADA', 'FINALIZADO')
              AND {due_expr} < ?
            """,
            (today,),
        ).fetchone()[0]
        upcoming = self.conn.execute(
            f"""
            SELECT COUNT(*) FROM processos
            WHERE prazo_entrega <> ''
              AND COALESCE(status_geral, '') NOT IN ('ENTREGUE', 'CANCELADA', 'FINALIZADO')
              AND {due_expr} BETWEEN ? AND ?
            """,
            (today, next_week),
        ).fetchone()[0]
        production = self.conn.execute(
            "SELECT COUNT(*) FROM processos WHERE status_producao IN ('NAO_INICIADO', 'ITEM_PENDENTE_FABRICACAO', 'INICIADO', 'PARADO', 'FINALIZADO_PARCIAL')"
        ).fetchone()[0]
        production_partial = self.conn.execute(
            "SELECT COUNT(*) FROM processos WHERE status_producao = 'FINALIZADO_PARCIAL'"
        ).fetchone()[0]
        galvanization = self.conn.execute(
            "SELECT COUNT(*) FROM processos WHERE status_galvanizacao IN ('AGUARDANDO_ENVIO', 'DISPONIVEL_PARCIAL', 'EM_CARGA', 'ENVIADO_GALVANIZACAO', 'RETORNOU_PARCIAL')"
        ).fetchone()[0]
        galvanization_partial = self.conn.execute(
            "SELECT COUNT(*) FROM processos WHERE status_galvanizacao IN ('DISPONIVEL_PARCIAL', 'RETORNOU_PARCIAL')"
        ).fetchone()[0]
        expedition = self.conn.execute(
            "SELECT COUNT(*) FROM processos WHERE status_expedicao IN ('EM_SEPARACAO', 'AGUARDANDO_SEPARACAO_PARCIAL', 'SEPARACAO_INICIADA', 'SEPARADO', 'ENTREGUE_PARCIAL')"
        ).fetchone()[0]
        delivered_partial = self.conn.execute(
            "SELECT COUNT(*) FROM processos WHERE status_expedicao = 'ENTREGUE_PARCIAL'"
        ).fetchone()[0]
        pending_remanagement = self.conn.execute(
            "SELECT COUNT(*) FROM processos WHERE status_producao = 'ITEM_PENDENTE_FABRICACAO'"
        ).fetchone()[0]
        stockroom = self.visible_area_count("ALMOXARIFADO")
        delivered = self.conn.execute(
            "SELECT COUNT(*) FROM processos WHERE status_geral = 'ENTREGUE' OR status_expedicao = 'ENTREGUE'"
        ).fetchone()[0]
        return {
            "Total": total,
            "Ativas": active,
            "Vencidos": overdue,
            "Prox. 7 dias": upcoming,
            "Producao": production,
            "Prod. parcial": production_partial,
            "Galvanizacao": galvanization,
            "Galv. parcial": galvanization_partial,
            "Expedicao": expedition,
            "Entregues parc.": delivered_partial,
            "Pend. remanej.": pending_remanagement,
            "Almox.": stockroom,
            "Entregues": delivered,
        }

    def dashboard_charts(self):
        due_expr = "date(substr(prazo_entrega, 7, 4) || '-' || substr(prazo_entrega, 4, 2) || '-' || substr(prazo_entrega, 1, 2))"
        today = date.today().isoformat()
        next_week = (date.today() + timedelta(days=7)).isoformat()
        status_rows = self.conn.execute(
            """
            SELECT COALESCE(NULLIF(status_geral, ''), 'SEM_STATUS') AS label, COUNT(*) AS total
            FROM processos
            WHERE COALESCE(status_geral, '') NOT IN ('ENTREGUE', 'CANCELADA', 'FINALIZADO')
            GROUP BY COALESCE(NULLIF(status_geral, ''), 'SEM_STATUS')
            ORDER BY total DESC, label
            """
        ).fetchall()
        area_data = [
            ("Producao", self.conn.execute("SELECT COUNT(*) FROM processos WHERE status_producao IN ('NAO_INICIADO', 'ITEM_PENDENTE_FABRICACAO', 'INICIADO', 'PARADO', 'FINALIZADO_PARCIAL')").fetchone()[0]),
            ("Galvanizacao", self.conn.execute("SELECT COUNT(*) FROM processos WHERE status_galvanizacao IN ('AGUARDANDO_ENVIO', 'DISPONIVEL_PARCIAL', 'EM_CARGA', 'ENVIADO_GALVANIZACAO', 'RETORNOU_PARCIAL')").fetchone()[0]),
            ("Expedicao", self.conn.execute("SELECT COUNT(*) FROM processos WHERE status_expedicao IN ('EM_SEPARACAO', 'AGUARDANDO_SEPARACAO_PARCIAL', 'SEPARACAO_INICIADA', 'SEPARADO', 'ENTREGUE_PARCIAL')").fetchone()[0]),
            ("Almox.", self.visible_area_count("ALMOXARIFADO")),
            ("Pend. remanej.", self.conn.execute("SELECT COUNT(*) FROM processos WHERE status_producao = 'ITEM_PENDENTE_FABRICACAO'").fetchone()[0]),
        ]
        overdue = self.conn.execute(
            f"""
            SELECT COUNT(*) FROM processos
            WHERE prazo_entrega <> ''
              AND COALESCE(status_geral, '') NOT IN ('ENTREGUE', 'CANCELADA', 'FINALIZADO')
              AND {due_expr} < ?
            """,
            (today,),
        ).fetchone()[0]
        upcoming = self.conn.execute(
            f"""
            SELECT COUNT(*) FROM processos
            WHERE prazo_entrega <> ''
              AND COALESCE(status_geral, '') NOT IN ('ENTREGUE', 'CANCELADA', 'FINALIZADO')
              AND {due_expr} BETWEEN ? AND ?
            """,
            (today, next_week),
        ).fetchone()[0]
        on_time = self.conn.execute(
            f"""
            SELECT COUNT(*) FROM processos
            WHERE prazo_entrega <> ''
              AND COALESCE(status_geral, '') NOT IN ('ENTREGUE', 'CANCELADA', 'FINALIZADO')
              AND {due_expr} > ?
            """,
            (next_week,),
        ).fetchone()[0]
        delivered = self.conn.execute(
            "SELECT COUNT(*) FROM processos WHERE status_geral = 'ENTREGUE' OR status_expedicao = 'ENTREGUE'"
        ).fetchone()[0]
        return {
            "status": [(row["label"], row["total"]) for row in status_rows],
            "areas": area_data,
            "prazos": [("Vencidos", overdue), ("7 dias", upcoming), ("No prazo", on_time), ("Entregues", delivered)],
        }

    def dashboard_focus_text(self):
        values = self.dashboard()
        area_counts = {
            "Producao": values.get("Producao", 0),
            "Galvanizacao": values.get("Galvanizacao", 0),
            "Expedicao": values.get("Expedicao", 0),
            "Almox.": values.get("Almox.", 0),
            "Pend. remanej.": values.get("Pend. remanej.", 0),
        }
        bottleneck = max(area_counts.items(), key=lambda item: item[1]) if area_counts else ("-", 0)
        alerts = []
        if values.get("Vencidos", 0):
            alerts.append(f"{values['Vencidos']} vencida(s)")
        if values.get("Prox. 7 dias", 0):
            alerts.append(f"{values['Prox. 7 dias']} vencendo em 7 dias")
        if not alerts:
            alerts.append("sem atrasos criticos")
        if bottleneck[1] == 0:
            return f"Foco operacional: sem filas operacionais. Alertas: {', '.join(alerts)}."
        return f"Foco operacional: maior fila em {bottleneck[0]} ({bottleneck[1]}). Alertas: {', '.join(alerts)}."

    def dashboard_metric_rows(self, metric):
        rows = self.list_processes()
        today = date.today()
        next_week = today + timedelta(days=7)

        def active(row):
            return (row["status_geral"] or "") not in ("ENTREGUE", "CANCELADA", "FINALIZADO")

        def due_date(row):
            try:
                return parse_date(row["prazo_entrega"])
            except AppError:
                return None

        filters = {
            "Total": lambda row: True,
            "Ativas": active,
            "Vencidos": lambda row: active(row) and due_date(row) and due_date(row) < today,
            "Prox. 7 dias": lambda row: active(row) and due_date(row) and today <= due_date(row) <= next_week,
            "Producao": lambda row: (row["status_producao"] or "") in ("NAO_INICIADO", "ITEM_PENDENTE_FABRICACAO", "INICIADO", "PARADO", "FINALIZADO_PARCIAL"),
            "Prod. parcial": lambda row: (row["status_producao"] or "") == "FINALIZADO_PARCIAL",
            "Galvanizacao": lambda row: (row["status_galvanizacao"] or "") in ("AGUARDANDO_ENVIO", "DISPONIVEL_PARCIAL", "EM_CARGA", "ENVIADO_GALVANIZACAO", "RETORNOU_PARCIAL"),
            "Galv. parcial": lambda row: (row["status_galvanizacao"] or "") in ("DISPONIVEL_PARCIAL", "RETORNOU_PARCIAL"),
            "Expedicao": lambda row: (row["status_expedicao"] or "") in ("EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARACAO_INICIADA", "SEPARADO", "ENTREGUE_PARCIAL"),
            "Entregues parc.": lambda row: (row["status_expedicao"] or "") == "ENTREGUE_PARCIAL",
            "Pend. remanej.": lambda row: (row["status_producao"] or "") == "ITEM_PENDENTE_FABRICACAO",
            "Almox.": lambda row: self.visible_for_area(row, "ALMOXARIFADO"),
            "Entregues": lambda row: (row["status_geral"] or "") == "ENTREGUE" or (row["status_expedicao"] or "") == "ENTREGUE",
        }
        matcher = filters.get(metric, lambda _row: False)
        return sorted([row for row in rows if matcher(row)], key=lambda row: (row["cliente"] or "", row["proposta"] or ""))

    def dashboard_chart_rows(self, chart_key, label):
        rows = self.list_processes()
        today = date.today()
        next_week = today + timedelta(days=7)

        def active(row):
            return (row["status_geral"] or "") not in ("ENTREGUE", "CANCELADA", "FINALIZADO")

        if chart_key == "status":
            return sorted(
                [
                    row for row in rows
                    if active(row) and ((row["status_geral"] or "SEM_STATUS") == label)
                ],
                key=lambda row: (row["cliente"] or "", row["proposta"] or ""),
            )
        if chart_key == "areas":
            return self.dashboard_metric_rows(label)
        if chart_key == "prazos":
            def due_date(row):
                try:
                    return parse_date(row["prazo_entrega"])
                except AppError:
                    return None
            if label == "Vencidos":
                matcher = lambda row: active(row) and due_date(row) and due_date(row) < today
            elif label == "7 dias":
                matcher = lambda row: active(row) and due_date(row) and today <= due_date(row) <= next_week
            elif label == "No prazo":
                matcher = lambda row: active(row) and due_date(row) and due_date(row) > next_week
            elif label == "Entregues":
                matcher = lambda row: (row["status_geral"] or "") == "ENTREGUE" or (row["status_expedicao"] or "") == "ENTREGUE"
            else:
                matcher = lambda _row: False
            return sorted([row for row in rows if matcher(row)], key=lambda row: (due_date(row) or date.max, row["cliente"] or ""))
        return []

    def report_rows(self, report_name, filters=None):
        source_by_name = {
            "Processos em andamento": "ANDAMENTO",
            "Vencidos ou proximos": "VENCIMENTOS",
            "Producao por status": "PRODUCAO_STATUS",
            "Galvanizacao enviada/retorno": "GALVANIZACAO",
            "Entregas por cliente": "ENTREGAS",
            "Parciais e pendencias": "PARCIAIS",
            "Remanejamentos": "REMANEJAMENTOS",
            "Listagem filtrada": "LISTAGEM",
        }
        return self.report_rows_by_source(source_by_name.get(report_name, "LISTAGEM"), filters)

    def report_rows_by_source(self, source, filters=None):
        filters = filters or {}
        if source == "ANDAMENTO":
            filters["status"] = ""
            rows = self.conn.execute(
                """
                SELECT * FROM processos
                WHERE COALESCE(status_geral, '') NOT IN ('ENTREGUE', 'FINALIZADO', 'CANCELADA')
                ORDER BY prazo_entrega, id DESC
                """
            ).fetchall()
        elif source == "VENCIMENTOS":
            today = date.today().isoformat()
            end = (date.today() + timedelta(days=7)).isoformat()
            rows = self.conn.execute(
                """
                SELECT * FROM processos
                WHERE prazo_entrega <> ''
                  AND COALESCE(status_geral, '') NOT IN ('ENTREGUE', 'FINALIZADO', 'CANCELADA')
                  AND date(substr(prazo_entrega, 7, 4) || '-' || substr(prazo_entrega, 4, 2) || '-' || substr(prazo_entrega, 1, 2)) <= ?
                ORDER BY date(substr(prazo_entrega, 7, 4) || '-' || substr(prazo_entrega, 4, 2) || '-' || substr(prazo_entrega, 1, 2)), cliente
                """,
                (end,),
            ).fetchall()
        elif source == "PRODUCAO_STATUS":
            rows = self.conn.execute(
                """
                SELECT COALESCE(NULLIF(status_producao, ''), 'SEM_STATUS') AS status_producao, COUNT(*) AS total
                FROM processos
                GROUP BY status_producao
                ORDER BY total DESC, status_producao
                """
            ).fetchall()
        elif source == "ENTREGAS":
            rows = self.conn.execute(
                """
                SELECT cliente, proposta, pedido_compra, obra_site, prazo_entrega, data_retirada,
                       status_expedicao, status_geral
                FROM processos
                WHERE status_geral = 'ENTREGUE' OR status_expedicao IN ('ENTREGUE', 'ENTREGUE_PARCIAL')
                ORDER BY cliente, prazo_entrega
                """
            ).fetchall()
        elif source == "PARCIAIS":
            rows = self.list_partial_pending_processes(filters)
        elif source == "GALVANIZACAO":
            rows = self.conn.execute(
                """
                SELECT proposta, cliente, obra_site, lote, peso, data_envio_galv,
                       data_prevista_retorno_galv, data_retorno_galv, status_galvanizacao,
                       status_expedicao, situacao_fluxo
                FROM processos
                WHERE COALESCE(status_galvanizacao, '') <> ''
                ORDER BY data_envio_galv DESC, data_prevista_retorno_galv, cliente
                """
            ).fetchall()
        elif source == "REMANEJAMENTOS":
            rows = self.conn.execute(
                """
                SELECT proposta, cliente, obra_site, lote, peso, origem_remanejamento,
                       observacao_remanejamento, status_producao, status_expedicao,
                       situacao_fluxo, atualizado_em, atualizado_por
                FROM processos
                WHERE COALESCE(origem_remanejamento, '') <> ''
                   OR status_producao = 'ITEM_PENDENTE_FABRICACAO'
                ORDER BY atualizado_em DESC, cliente
                """
            ).fetchall()
        else:
            rows = self.list_processes(filters)
        return rows

    def history_summary(self):
        return self.conn.execute(
            """
            SELECT area, COUNT(*) AS total, MAX(data_hora) AS ultima_alteracao
            FROM historico_status
            GROUP BY area
            ORDER BY total DESC, area
            """
        ).fetchall()

    def audit_summary(self):
        return self.conn.execute(
            """
            SELECT acao, COUNT(*) AS total, MAX(data_hora) AS ultima_alteracao
            FROM auditoria
            GROUP BY acao
            ORDER BY total DESC, acao
            """
        ).fetchall()



def rows_to_table(rows, columns=None):
    if not rows:
        columns = columns or []
        return [export_label(col) for col in columns], []
    columns = columns or list(rows[0].keys())
    columns = [col for col in columns if col in rows[0].keys()]
    labels = [export_label(col) for col in columns]
    data = [[display_cell(col, row[col]) for col in columns] for row in rows]
    return labels, data


def write_xlsx(path, rows, columns=None, title="Relatorio"):
    columns, data = rows_to_table(rows, columns)
    if not columns:
        columns = ["Mensagem"]
        data = [["Nenhum registro"]]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", XLSX_CONTENT_TYPES)
        zf.writestr("_rels/.rels", XLSX_RELS)
        zf.writestr("xl/workbook.xml", XLSX_WORKBOOK)
        zf.writestr("xl/_rels/workbook.xml.rels", XLSX_WORKBOOK_RELS)
        zf.writestr("xl/styles.xml", XLSX_STYLES)
        zf.writestr("xl/worksheets/sheet1.xml", build_sheet_xml(columns, data, title))


def cell_ref(row, col):
    letters = ""
    while col:
        col, remainder = divmod(col - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row}"


def build_sheet_xml(columns, data, title="Relatorio"):
    rows_xml = []
    title_cells = f'<c r="A1" s="3" t="inlineStr"><is><t>{escape(APP_NAME)}</t></is></c>'
    subtitle_cells = f'<c r="A2" s="4" t="inlineStr"><is><t>{escape(title)} | Gerado em {escape(now_br())} | {len(data)} registro(s)</t></is></c>'
    rows_xml.append(f'<row r="1" ht="26" customHeight="1">{title_cells}</row>')
    rows_xml.append(f'<row r="2" ht="22" customHeight="1">{subtitle_cells}</row>')
    all_rows = [columns] + data
    for r_idx, row in enumerate(all_rows, start=1):
        cells = []
        max_lines = 1
        sheet_row = r_idx + 3
        for c_idx, value in enumerate(row, start=1):
            value = "" if value is None else str(value)
            wrapped_lines = max(1, len(textwrap.wrap(value, width=38)) if len(value) > 38 else value.count("\n") + 1)
            max_lines = max(max_lines, min(wrapped_lines, 6))
            style = ' s="1"' if r_idx == 1 else (' s="5"' if r_idx % 2 == 0 else ' s="2"')
            cells.append(f'<c r="{cell_ref(sheet_row, c_idx)}"{style} t="inlineStr"><is><t>{escape(value)}</t></is></c>')
        height = 22 if r_idx == 1 else min(18 * max_lines, 96)
        rows_xml.append(f'<row r="{sheet_row}" ht="{height}" customHeight="1">{"".join(cells)}</row>')
    widths = []
    for idx, col in enumerate(columns, start=1):
        samples = [str(col)] + [str(row[idx - 1]) for row in data[:200] if idx - 1 < len(row)]
        longest = max((len(part) for value in samples for part in str(value).splitlines()), default=len(str(col)))
        width = min(max(longest + 4, 12), 42)
        widths.append(f'<col min="{idx}" max="{idx}" width="{width}" customWidth="1"/>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<cols>{"".join(widths)}</cols><sheetData>{"".join(rows_xml)}</sheetData><autoFilter ref="A4:{cell_ref(max(len(data) + 4, 4), len(columns))}"/></worksheet>'
    )


def write_pdf(path, rows, title, columns=None):
    columns, data = rows_to_table(rows, columns)
    if not columns:
        columns = ["Mensagem"]
        data = [["Nenhum registro"]]
    make_table_pdf(path, title.replace("_", " ").title(), columns, data, len(rows))


def pdf_escape(text):
    return str(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_simple_pdf(path, lines):
    wrapped = []
    for line in lines:
        wrapped.extend(textwrap.wrap(str(line), width=105) or [""])
    pages = [wrapped[i : i + 42] for i in range(0, len(wrapped), 42)] or [[]]
    objects = []
    objects.append("<< /Type /Catalog /Pages 2 0 R >>")
    page_ids = []
    content_ids = []
    next_id = 3
    for _page in pages:
        page_ids.append(next_id)
        content_ids.append(next_id + 1)
        next_id += 2
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>")
    for page, page_id, content_id in zip(pages, page_ids, content_ids):
        stream_lines = ["BT", "/F1 10 Tf", "50 790 Td", "14 TL"]
        for line in page:
            stream_lines.append(f"({pdf_escape(line)}) Tj")
            stream_lines.append("T*")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> "
            f"/Contents {content_id} 0 R >>"
        )
        objects.append(f"<< /Length {len(stream.encode('latin-1', 'replace'))} >>\nstream\n{stream}\nendstream")
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n{obj}\nendobj\n".encode("latin-1", "replace"))
    xref = len(output)
    output.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode("ascii")
    )
    Path(path).write_bytes(output)


def make_table_pdf(path, title, columns, data, total_rows):
    max_cols = min(len(columns), 7)
    columns = columns[:max_cols]
    data = [row[:max_cols] for row in data]
    page_w, page_h = 842, 595
    margin = 34
    usable_w = page_w - margin * 2
    col_w = usable_w / max(len(columns), 1)
    row_h = 24
    pages = [data[i : i + 16] for i in range(0, len(data), 16)] or [[]]
    objects = ["<< /Type /Catalog /Pages 2 0 R >>"]
    page_ids = []
    content_ids = []
    next_id = 3
    for _page in pages:
        page_ids.append(next_id)
        content_ids.append(next_id + 1)
        next_id += 2
    objects.append(f"<< /Type /Pages /Kids [{' '.join(f'{pid} 0 R' for pid in page_ids)}] /Count {len(page_ids)} >>")
    for page_index, (page, page_id, content_id) in enumerate(zip(pages, page_ids, content_ids), start=1):
        ops = []
        ops.append("0.06 0.09 0.16 rg")
        ops.append(f"0 {page_h - 70} {page_w} 70 re f")
        ops.append("BT /F2 18 Tf 34 552 Td 1 1 1 rg")
        ops.append(f"({pdf_escape(APP_NAME)}) Tj ET")
        ops.append("BT /F1 11 Tf 34 530 Td 1 1 1 rg")
        ops.append(f"({pdf_escape(title)} | Gerado em {pdf_escape(now_br())} | {total_rows} registro(s)) Tj ET")
        y = page_h - 105
        ops.append("0.08 0.45 0.72 rg")
        ops.append(f"{margin} {y - 4} {usable_w} {row_h} re f")
        for idx, col in enumerate(columns):
            x = margin + idx * col_w + 5
            ops.append(f"BT /F2 8 Tf {x:.2f} {y + 3:.2f} Td 1 1 1 rg ({pdf_escape(str(col)[:18])}) Tj ET")
        y -= row_h
        for row_idx, row in enumerate(page):
            if row_idx % 2 == 0:
                ops.append("0.95 0.98 1 rg")
            else:
                ops.append("1 1 1 rg")
            ops.append(f"{margin} {y - 4} {usable_w} {row_h} re f")
            ops.append("0.82 0.87 0.94 RG")
            ops.append(f"{margin} {y - 4} {usable_w} {row_h} re S")
            for idx, value in enumerate(row):
                x = margin + idx * col_w + 5
                text = str(value or "")
                text = " ".join(text.split())
                ops.append(f"BT /F1 7 Tf {x:.2f} {y + 4:.2f} Td 0.05 0.09 0.16 rg ({pdf_escape(text[:24])}) Tj ET")
            y -= row_h
        ops.append(f"BT /F1 8 Tf {page_w - 95} 24 Td 0.35 0.39 0.47 rg (Pagina {page_index}/{len(pages)}) Tj ET")
        stream = "\n".join(ops)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w} {page_h}] "
            f"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> "
            f"/F2 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >> >> >> "
            f"/Contents {content_id} 0 R >>"
        )
        objects.append(f"<< /Length {len(stream.encode('latin-1', 'replace'))} >>\nstream\n{stream}\nendstream")
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n{obj}\nendobj\n".encode("latin-1", "replace"))
    xref = len(output)
    output.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode("ascii"))
    Path(path).write_bytes(output)


XLSX_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

XLSX_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

XLSX_WORKBOOK = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="Relatorio" sheetId="1" r:id="rId1"/></sheets></workbook>"""

XLSX_WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

XLSX_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="3">
<font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
<font><b/><sz val="14"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
</fonts>
<fills count="5">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF1F6F5B"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFEFF6FF"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF0F172A"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFE2E8F0"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="2">
<border><left/><right/><top/><bottom/><diagonal/></border>
<border><left style="thin"><color rgb="FFCBD5E1"/></left><right style="thin"><color rgb="FFCBD5E1"/></right><top style="thin"><color rgb="FFCBD5E1"/></top><bottom style="thin"><color rgb="FFCBD5E1"/></bottom><diagonal/></border>
</borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="6">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="1" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="0" fontId="2" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>
<xf numFmtId="0" fontId="0" fillId="4" borderId="0" xfId="0" applyFill="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>
<xf numFmtId="0" fontId="0" fillId="2" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
</cellXfs>
</styleSheet>"""

