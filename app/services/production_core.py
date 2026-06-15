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
import tkinter as tk
import traceback
import unicodedata
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
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
    ("GALVANIZACAO", "RETORNOU_PARCIAL", "GALVANIZACAO", "EXPEDICAO", 50),
    ("EXPEDICAO", "EM_SEPARACAO", "EXPEDICAO", "EXPEDICAO", 10),
    ("EXPEDICAO", "AGUARDANDO_SEPARACAO_PARCIAL", "EXPEDICAO", "EXPEDICAO", 15),
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
    "GALVANIZACAO": ["AGUARDANDO_ENVIO", "DISPONIVEL_PARCIAL", "EM_CARGA", "ENVIADO_GALVANIZACAO", "RETORNOU_PARCIAL", "RETORNOU_GALVANIZACAO"],
    "EXPEDICAO": ["EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARADO", "ENTREGUE_PARCIAL", "ENTREGUE"],
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
    "dashboard": "▦",
    "general": "◎",
    "production": "⚙",
    "galvanization": "◆",
    "expedition": "▣",
    "stock": "▤",
    "history": "◷",
    "audit": "⌕",
    "reports": "▧",
    "settings": "⚙",
    "new": "+",
    "search": "⌕",
    "clear": "×",
    "load": "⇄",
    "batch": "☑",
    "early": "↪",
    "pdf": "◫",
    "excel": "▦",
    "save": "✓",
    "cancel": "×",
    "refresh": "↻",
    "edit": "✎",
    "delete": "−",
    "users": "♙",
    "backup": "⤓",
    "restore": "⤒",
    "database": "▣",
    "status": "●",
}

AREA_ICONS = {
    "CONTROLE GERAL": "◎",
    "PRODUCAO": "⚙",
    "GALVANIZACAO": "◆",
    "EXPEDICAO": "▣",
    "ALMOXARIFADO": "▤",
}

STATUS_ICONS = {
    "NAO_LIBERADO": "○",
    "LIBERADO_PRODUCAO": "▶",
    "NAO_INICIADO": "○",
    "ITEM_PENDENTE_FABRICACAO": "!",
    "INICIADO": "▶",
    "PARADO": "■",
    "FINALIZADO": "✓",
    "FINALIZADO_PARCIAL": "◐",
    "AGUARDANDO_ENVIO": "◷",
    "DISPONIVEL_PARCIAL": "◐",
    "EM_CARGA": "▣",
    "ENVIADO_GALVANIZACAO": "➜",
    "RETORNOU_GALVANIZACAO": "✓",
    "RETORNOU_PARCIAL": "◐",
    "EM_SEPARACAO": "▤",
    "AGUARDANDO_SEPARACAO_PARCIAL": "◐",
    "SEPARADO": "✓",
    "ENTREGUE": "✓",
    "ENTREGUE_PARCIAL": "◐",
    "CANCELADA": "×",
    "AGUARDANDO_CONFIRMACAO": "○",
    "EM_ANDAMENTO": "▶",
    "SEM_PARAFUSOS": "−",
    "ALMOXARIFADO_ENTREGUE": "✓",
    "ALMOXARIFADO_ENTREGUE_PARCIAL": "◐",
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
        "Ã‡": "C",
        "Ç": "C",
        "ç": "C",
        "Ã": "A",
        "Á": "A",
        "À": "A",
        "Â": "A",
        "Ã": "A",
        "É": "E",
        "Ê": "E",
        "Í": "I",
        "Ó": "O",
        "Ô": "O",
        "Õ": "O",
        "Ú": "U",
        "Não": "NAO",
        "NÃO": "NAO",
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


class RoundedButton(tk.Canvas):
    def __init__(self, parent, text="", image=None, command=None, style="TButton", width=None, **kwargs):
        self.palette = widget_palette(parent)
        self.text = text or ""
        self.image = image
        self.command = command
        self.style_name = style or "TButton"
        self.disabled = False
        self._hover = False
        self._pressed = False
        self._explicit_width = width
        self._font = self.button_font()
        self._drawing = False
        w, h = self.measure()
        self._last_actual_width = w
        super().__init__(
            parent,
            width=w,
            height=h,
            highlightthickness=0,
            bd=0,
            relief="flat",
            background=self.parent_bg(parent),
            cursor="hand2",
            takefocus=True,
        )
        self.bind("<Enter>", self.on_enter)
        self.bind("<Leave>", self.on_leave)
        self.bind("<ButtonPress-1>", self.on_press)
        self.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Key-space>", self.on_key_activate)
        self.bind("<Return>", self.on_key_activate)
        self.bind("<Configure>", self.on_configure)
        self._icon_image = image
        self.draw()

    def parent_bg(self, parent):
        try:
            return parent.cget("background")
        except tk.TclError:
            return self.palette["bg"]

    def button_font(self):
        if "Nav" in self.style_name:
            return (FONT_FAMILY, 9, "bold")
        if "Small" in self.style_name:
            return (FONT_FAMILY, 7, "bold" if "Accent" in self.style_name else "normal")
        return (FONT_FAMILY, 9, "bold" if "Accent" in self.style_name else "normal")

    def measure(self):
        char_width = 6 if "Small" in self.style_name else 7
        text_width = max(0, len(self.text) * char_width)
        icon_width = 0
        if self.image:
            try:
                icon_width = self.image.width() + (5 if self.text else 0)
            except tk.TclError:
                icon_width = 14
        horizontal = 14 if "Small" in self.style_name else 18
        width = max(24 if not self.text else 0, text_width + icon_width + horizontal)
        if self._explicit_width:
            width = max(width, int(self._explicit_width) * char_width + horizontal)
        height = 22 if "Small" in self.style_name else 26
        if "Nav" in self.style_name:
            height = 28
        return int(width), height

    def colors(self):
        self.palette = widget_palette(self)
        if self.disabled:
            return self.palette["surface_alt"], self.palette["muted"], self.palette["surface_alt"]
        accent = "Accent" in self.style_name or "NavActive" in self.style_name
        if accent:
            bg = self.palette["accent_hover"] if self._hover or self._pressed else self.palette["accent"]
            return bg, self.palette["accent_text"], bg
        bg = self.palette["border"] if self._hover or self._pressed else self.palette["surface_alt"]
        return bg, self.palette["text"], bg

    def rounded_rect(self, x1, y1, x2, y2, radius, fill, outline=None):
        radius = max(1, min(radius, int((x2 - x1) / 2), int((y2 - y1) / 2)))
        outline = outline or fill
        self.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=fill, outline=fill)
        self.create_rectangle(x1, y1 + radius, x2, y2 - radius, fill=fill, outline=fill)
        self.create_oval(x1, y1, x1 + radius * 2, y1 + radius * 2, fill=fill, outline=fill)
        self.create_oval(x2 - radius * 2, y1, x2, y1 + radius * 2, fill=fill, outline=fill)
        self.create_oval(x1, y2 - radius * 2, x1 + radius * 2, y2, fill=fill, outline=fill)
        self.create_oval(x2 - radius * 2, y2 - radius * 2, x2, y2, fill=fill, outline=fill)
        if outline != fill:
            self.create_arc(x1, y1, x1 + radius * 2, y1 + radius * 2, start=90, extent=90, outline=outline, style="arc")
            self.create_arc(x2 - radius * 2, y1, x2, y1 + radius * 2, start=0, extent=90, outline=outline, style="arc")
            self.create_arc(x1, y2 - radius * 2, x1 + radius * 2, y2, start=180, extent=90, outline=outline, style="arc")
            self.create_arc(x2 - radius * 2, y2 - radius * 2, x2, y2, start=270, extent=90, outline=outline, style="arc")
            self.create_line(x1 + radius, y1, x2 - radius, y1, fill=outline)
            self.create_line(x1 + radius, y2, x2 - radius, y2, fill=outline)
            self.create_line(x1, y1 + radius, x1, y2 - radius, fill=outline)
            self.create_line(x2, y1 + radius, x2, y2 - radius, fill=outline)

    def on_configure(self, event=None):
        if not self._drawing and event:
            self._last_actual_width = max(event.width, self.measure()[0])
            self.draw(event.width)

    def draw(self, actual_width=None):
        if self._drawing:
            return
        self._drawing = True
        self.delete("all")
        width, height = self.measure()
        if actual_width is not None:
            self._last_actual_width = max(width, int(actual_width))
        else:
            try:
                current_width = self.winfo_width()
            except tk.TclError:
                current_width = width
            self._last_actual_width = max(width, self._last_actual_width, current_width)
        draw_width = self._last_actual_width
        if actual_width is None:
            super().configure(height=height, background=self.parent_bg(self.master))
        bg, fg, outline = self.colors()
        radius = 8 if "Nav" in self.style_name else min(10, height // 2)
        x1 = 0
        y1 = 0
        x2 = max(1, draw_width - 1)
        y2 = max(1, height - 1)
        self.rounded_rect(x1, y1, x2, y2, radius, fill=bg, outline=outline)
        char_width = 6 if "Small" in self.style_name else 7
        text_width = len(self.text) * char_width
        icon_width = self.image.width() if self.image else 0
        gap = 5 if self.image and self.text else 0
        x = max(8, (draw_width - icon_width - gap - text_width) / 2)
        if "Nav" in self.style_name:
            x = max(14, min(x, 18))
        if self.image:
            self.create_image(x, height / 2, image=self.image, anchor="w")
            x += icon_width + gap
        if self.text:
            self.create_text(x, height / 2, text=self.text, fill=fg, font=self._font, anchor="w")
        self._drawing = False

    def on_enter(self, _event=None):
        if not self.disabled:
            self._hover = True
            self.draw()

    def on_leave(self, _event=None):
        self._hover = False
        self._pressed = False
        self.draw()

    def on_press(self, _event=None):
        if not self.disabled:
            self._pressed = True
            self.draw()

    def on_release(self, _event=None):
        if self.disabled:
            return
        was_pressed = self._pressed
        self._pressed = False
        self.draw()
        if was_pressed and self.command:
            self.command()

    def on_key_activate(self, _event=None):
        if not self.disabled and self.command:
            self.command()
        return "break"

    def state(self, states=None):
        if states is None:
            return ("disabled",) if self.disabled else ()
        self.disabled = "disabled" in states
        super().configure(cursor="" if self.disabled else "hand2")
        self.draw()
        return self.state()

    def configure(self, cnf=None, **kwargs):
        options = {}
        if cnf:
            options.update(cnf)
        options.update(kwargs)
        redraw = False
        for key in ("text", "image", "command", "style", "width", "state"):
            if key not in options:
                continue
            value = options.pop(key)
            if key == "text":
                self.text = value or ""
                redraw = True
            elif key == "image":
                self.image = value
                self._icon_image = value
                redraw = True
            elif key == "command":
                self.command = value
            elif key == "style":
                self.style_name = value or "TButton"
                self._font = self.button_font()
                redraw = True
            elif key == "width":
                self._explicit_width = value
                redraw = True
            elif key == "state":
                self.disabled = value == "disabled"
                redraw = True
        if options:
            super().configure(**options)
        if redraw:
            self.draw()

    config = configure


def icon_button(parent, icon_key, text, **kwargs):
    image = icon_image(parent, icon_key)
    style = kwargs.pop("style", "TButton")
    command = kwargs.pop("command", None)
    width = kwargs.pop("width", None)
    kwargs.pop("compound", None)
    label = text if image else icon_text(icon_key, text)
    button = RoundedButton(parent, text=label, image=image, command=command, style=style, width=width, **kwargs)
    button._icon_image = image
    return button


def status_display(status):
    status = normalize_status(status)
    label = status_label(status)
    if not label:
        return ""
    return f"{STATUS_ICONS.get(status, ICONS['status'])} {label}"


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
    }
    for column, ddl in process_column_defaults.items():
        if column not in process_columns:
            conn.execute(f"ALTER TABLE processos ADD COLUMN {column} {ddl}")
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
                "NAO_INICIADO": {"INICIADO", "PARADO"},
                "ITEM_PENDENTE_FABRICACAO": {"INICIADO", "PARADO", "FINALIZADO", "FINALIZADO_PARCIAL"},
                "INICIADO": {"PARADO", "FINALIZADO", "FINALIZADO_PARCIAL"},
                "PARADO": {"INICIADO", "FINALIZADO", "FINALIZADO_PARCIAL"},
                "FINALIZADO_PARCIAL": {"FINALIZADO"},
            },
            "GALVANIZACAO": {
                "": {"AGUARDANDO_ENVIO"},
                "AGUARDANDO_ENVIO": {"EM_CARGA"},
                "DISPONIVEL_PARCIAL": {"EM_CARGA"},
                "EM_CARGA": {"ENVIADO_GALVANIZACAO"},
                "ENVIADO_GALVANIZACAO": {"RETORNOU_GALVANIZACAO", "RETORNOU_PARCIAL"},
            },
            "EXPEDICAO": {
                "": {"EM_SEPARACAO"},
                "EM_SEPARACAO": {"SEPARADO"},
                "AGUARDANDO_SEPARACAO_PARCIAL": {"SEPARADO", "ENTREGUE_PARCIAL"},
                "SEPARADO": {"ENTREGUE", "ENTREGUE_PARCIAL"},
                "ENTREGUE_PARCIAL": {"ENTREGUE"},
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
                options = [status for status in options if status in ("SEPARADO", "ENTREGUE_PARCIAL")]
            elif current == "ENTREGUE_PARCIAL" and self.expedition_delivery_can_close_after_customer_partial(process):
                options = [status for status in options if status == "ENTREGUE"]
        if area == "GALVANIZACAO" and process["status_producao"] == "FINALIZADO_PARCIAL":
            options = [status for status in options if status != "RETORNOU_GALVANIZACAO"]
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

    def create_partial_subprocess(self, parent, user, description="", final_balance=False):
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
        values = {
            "cliente": parent["cliente"],
            "proposta": proposal,
            "pedido_compra": parent["pedido_compra"],
            "obra_site": parent["obra_site"],
            "peso": None,
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
            "peso_parcial": None,
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
        expedition_ready = {"EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARADO"}
        not_ready = [partial["proposta"] for partial in partials if (partial["status_expedicao"] or "") not in expedition_ready]
        if not_ready:
            raise AppError("Ainda existem parciais que nao chegaram ou ja sairam da Expedicao: " + ", ".join(not_ready))
        delivered = [partial["proposta"] for partial in partials if (partial["status_expedicao"] or "") in ("ENTREGUE", "ENTREGUE_PARCIAL")]
        if delivered:
            raise AppError("Nao e possivel juntar parciais que ja tiveram entrega: " + ", ".join(delivered))
        parent_old_expedition = parent["status_expedicao"] or ""
        parent_new_expedition = "SEPARADO" if all((partial["status_expedicao"] or "") == "SEPARADO" for partial in partials) else "EM_SEPARACAO"
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
        if (process["status_expedicao"] or "") not in ("EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARADO"):
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

    def deliver_by_material_remanagement(self, destination_id, source_id, user, observation):
        if not user_can_access_area(user, "EXPEDICAO"):
            raise AppError("Seu usuario nao tem permissao para fazer entrega por remanejamento.")
        if destination_id == source_id:
            raise AppError("A proposta entregue e a proposta origem devem ser diferentes.")
        observation = (observation or "").strip()
        if not observation:
            raise AppError("Informe quais itens foram remanejados.")
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
        self.confirm_stockroom_delivery(destination_id, user, "Confirmacao automatica pela entrega por remanejamento")

        note_source = f"{observation} | Material usado para entrega antecipada de {destination['proposta']}"
        note_destination = f"Entrega antecipada por remanejamento da proposta {source['proposta']} | {observation}"
        old_source_production = source["status_producao"] or ""
        old_source_galvanization = source["status_galvanizacao"] or ""
        old_source_expedition = source["status_expedicao"] or ""
        old_destination_general = destination["status_geral"] or ""
        old_destination_production = destination["status_producao"] or ""
        old_destination_expedition = destination["status_expedicao"] or ""

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

        self.add_history(source_id, source["proposta"], "PRODUCAO", old_source_production, "ITEM_PENDENTE_FABRICACAO", user, note_source)
        if old_source_galvanization:
            self.add_history(source_id, source["proposta"], "GALVANIZACAO", old_source_galvanization, "", user, "Remanejada para repor material entregue antecipadamente")
        if old_source_expedition:
            self.add_history(source_id, source["proposta"], "EXPEDICAO", old_source_expedition, "", user, "Remanejada para repor material entregue antecipadamente")
        if old_destination_production != "FINALIZADO":
            self.add_history(destination_id, destination["proposta"], "PRODUCAO", old_destination_production, "FINALIZADO", user, "Atendida por material remanejado")
        self.add_history(destination_id, destination["proposta"], "EXPEDICAO", old_destination_expedition, "ENTREGUE", user, note_destination)
        self.add_history(destination_id, destination["proposta"], "CONTROLE GERAL", old_destination_general, "ENTREGUE", user, "Entrega antecipada por remanejamento")
        self.absorb_destination_partials_after_delivery(destination_id, user, "Principal entregue por remanejamento")
        self.add_audit("processos", source_id, "REMANEJAMENTO_ENTREGA_ANTECIPADA", "status_producao", old_source_production, "ITEM_PENDENTE_FABRICACAO", user)
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

    def save_process(self, data, user, process_id=None):
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
        self.conn.commit()
        return saved_id

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

    def update_status(self, process_id, area, new_status, observation, user, allow_partial_delivery_completion=False):
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
        if area == "GALVANIZACAO" and process["status_producao"] == "FINALIZADO_PARCIAL" and new_status == "RETORNOU_GALVANIZACAO":
            raise AppError("Proposta parcial na galvanizacao deve retornar como Retornou parcialmente.")
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
            partial_id = self.create_partial_subprocess(process, user, observation)
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
        elif area == "PRODUCAO" and new_status == "FINALIZADO" and not self.is_partial_process(process):
            has_partials = self.conn.execute(
                "SELECT COUNT(*) FROM processos WHERE processo_pai_id = ?",
                (process_id,),
            ).fetchone()[0]
            if has_partials:
                partial_id = self.create_partial_subprocess(process, user, observation or "Saldo final liberado.", final_balance=True)
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
        elif area == "EXPEDICAO" and new_status == "ENTREGUE" and self.is_partial_process(process):
            self.refresh_parent_completion(process["processo_pai_id"], user)
        if area in ("GALVANIZACAO", "EXPEDICAO") or "status_expedicao" in updates:
            self.try_auto_merge_expedition_partials(process_id, user)
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
            is_subprocess_partial = self.is_partial_process(process)
            is_partial = (not is_subprocess_partial) and (
                bool(item["parcial"])
                or old_status == "DISPONIVEL_PARCIAL"
                or process["situacao_fluxo"] == "PARCIAL_EM_ANDAMENTO"
            )
            new_status = "RETORNOU_PARCIAL" if is_partial else "RETORNOU_GALVANIZACAO"
            expedition_status = "AGUARDANDO_SEPARACAO_PARCIAL" if new_status == "RETORNOU_PARCIAL" else "EM_SEPARACAO"
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
            if old_status != new_status:
                self.add_history(process["id"], process["proposta"], "GALVANIZACAO", old_status, new_status, user, observation)
            if not process["status_expedicao"]:
                self.add_history(process["id"], process["proposta"], "EXPEDICAO", "", expedition_status, user, "Liberacao automatica pelo retorno da carga")
        for process_id in returned_process_ids:
            self.try_auto_merge_expedition_partials(process_id, user)
        self.conn.execute(
            "UPDATE cargas_galvanizacao SET status = ?, data_retorno = ?, observacao = ? WHERE id = ?",
            ("RETORNADA_GALVANIZACAO", today_br(), f"Retornada em {now_br()} por {user['login']}", load_id),
        )
        self.conn.commit()

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
        if area == "EXPEDICAO" and status in ("EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARADO", "ENTREGUE_PARCIAL"):
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
            "SELECT COUNT(*) FROM processos WHERE status_expedicao IN ('EM_SEPARACAO', 'AGUARDANDO_SEPARACAO_PARCIAL', 'SEPARADO', 'ENTREGUE_PARCIAL')"
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
            ("Expedicao", self.conn.execute("SELECT COUNT(*) FROM processos WHERE status_expedicao IN ('EM_SEPARACAO', 'AGUARDANDO_SEPARACAO_PARCIAL', 'SEPARADO', 'ENTREGUE_PARCIAL')").fetchone()[0]),
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
            "Expedicao": lambda row: (row["status_expedicao"] or "") in ("EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARADO", "ENTREGUE_PARCIAL"),
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


class LoginDialog(tk.Toplevel):
    def __init__(self, master, repo):
        super().__init__(master)
        self.repo = repo
        self.user = None
        self.configure(background=COLOR_PALETTES[master.config_data.get("color_palette", "aurora")]["bg"])
        self.title("Login")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.grab_set()
        frame = ttk.Frame(self, padding=22)
        frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(frame, text=APP_NAME, font=(FONT_FAMILY, 14, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 16))
        ttk.Label(frame, text="Usuario").grid(row=1, column=0, sticky="w")
        ttk.Label(frame, text="Senha").grid(row=2, column=0, sticky="w")
        self.login_var = tk.StringVar(value="admin")
        self.password_var = tk.StringVar()
        login = ttk.Entry(frame, textvariable=self.login_var, width=26)
        password = ttk.Entry(frame, textvariable=self.password_var, show="*", width=26)
        login.grid(row=1, column=1, pady=4)
        password.grid(row=2, column=1, pady=4)
        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, columnspan=2, pady=(14, 0), sticky="e")
        icon_button(buttons, "save", "Entrar", command=self.login).pack(side="left", padx=(0, 8))
        icon_button(buttons, "cancel", "Cancelar", command=self.cancel).pack(side="left")
        ttk.Label(frame, text="Primeiro acesso: admin / admin", style="Muted.TLabel").grid(
            row=4, column=0, columnspan=2, pady=(12, 0)
        )
        self.bind("<Return>", lambda _e: self.login())
        password.focus_set()
        master.apply_non_ttk_colors(self)
        self.update_idletasks()
        self.geometry(f"+{master.winfo_rootx()+120}+{master.winfo_rooty()+120}")

    def login(self):
        user = self.repo.authenticate(self.login_var.get(), self.password_var.get())
        if not user:
            messagebox.showerror("Login", "Usuario ou senha invalidos.")
            return
        self.user = user
        self.destroy()

    def cancel(self):
        self.user = None
        self.destroy()


class ProcessForm(tk.Toplevel):
    def __init__(self, master, repo, user, process=None):
        super().__init__(master)
        self.repo = repo
        self.user = user
        self.process = process
        self.saved = False
        self.configure(background=COLOR_PALETTES[master.config_data.get("color_palette", "aurora")]["bg"])
        self.title("Editar processo" if process else "Novo processo")
        self.geometry("760x450")
        self.transient(master)
        self.grab_set()
        self.vars = {}
        self.texts = {}
        container = ttk.Frame(self, padding=14)
        container.pack(fill="both", expand=True)
        left = ttk.LabelFrame(container, text="Dados principais", padding=12)
        left.pack(fill="x")
        for idx, (name, label, required) in enumerate(FORM_FIELDS):
            ttk.Label(left, text=label + (" *" if required else "")).grid(row=idx // 2, column=(idx % 2) * 2, sticky="w", pady=5)
            var = tk.StringVar(value=self.value(name))
            self.vars[name] = var
            ttk.Entry(left, textvariable=var, width=28).grid(row=idx // 2, column=(idx % 2) * 2 + 1, sticky="ew", padx=(6, 20), pady=5)
        left.columnconfigure(1, weight=1)
        left.columnconfigure(3, weight=1)
        note_fields = self.note_fields()
        if note_fields:
            notes = ttk.LabelFrame(container, text="Observacao geral da proposta", padding=12)
            notes.pack(fill="both", expand=True, pady=(12, 0))
            for idx, (name, label) in enumerate(note_fields):
                ttk.Label(notes, text=label).grid(row=idx, column=0, sticky="nw", pady=4, padx=(0, 8))
                text = tk.Text(notes, height=6, width=64, wrap="word")
                text.insert("1.0", self.value(name))
                text.grid(row=idx, column=1, sticky="ew", pady=4)
                self.texts[name] = text
            notes.columnconfigure(1, weight=1)
        buttons = ttk.Frame(container)
        buttons.pack(fill="x", pady=(12, 0))
        icon_button(buttons, "save", "Salvar", command=self.save, style="Accent.TButton").pack(side="right", padx=(8, 0))
        icon_button(buttons, "cancel", "Cancelar", command=self.destroy).pack(side="right")
        master.apply_non_ttk_colors(self)

    def value(self, name):
        if not self.process:
            if name == "data_entrada":
                return today_br()
            return ""
        value = self.process[name]
        return "" if value is None else str(value)

    def note_fields(self):
        return [("observacoes_gerais", "Observacao")]

    def save(self):
        data = {name: var.get() for name, var in self.vars.items()}
        data.update({name: text.get("1.0", "end").strip() for name, text in self.texts.items()})
        try:
            self.repo.save_process(data, self.user, self.process["id"] if self.process else None)
        except AppError as exc:
            messagebox.showerror("Validacao", str(exc), parent=self)
            return
        self.saved = True
        self.destroy()


class StatusDialog(tk.Toplevel):
    def __init__(self, master, repo, user, process, area):
        super().__init__(master)
        self.repo = repo
        self.user = user
        self.process = process
        self.area = area
        self.saved = False
        self.configure(background=COLOR_PALETTES[master.config_data.get("color_palette", "aurora")]["bg"])
        self.title(f"Alterar status - {area}")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        frame = ttk.Frame(self, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(frame, text=f"{process['proposta']} - {process['cliente']}", font=(FONT_FAMILY, 11, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )
        current = process[AREAS[area]["column"]] or ""
        ttk.Label(frame, text="Status atual").grid(row=1, column=0, sticky="w")
        ttk.Label(frame, text=area_status_label(area, current) if current else "-", style="Muted.TLabel").grid(row=1, column=1, sticky="w")
        ttk.Label(frame, text="Novo status").grid(row=2, column=0, sticky="w", pady=(8, 0))
        statuses = self.repo.next_status_options(area, process)
        self.status_choices = {area_status_label(area, status): status for status in statuses}
        labels = list(self.status_choices.keys())
        self.status_var = tk.StringVar(value=labels[0] if labels else "")
        combo = ttk.Combobox(frame, textvariable=self.status_var, values=list(self.status_choices.keys()), state="readonly", width=34)
        combo.grid(row=2, column=1, sticky="ew", pady=(8, 0))
        if not labels:
            ttk.Label(frame, text="Nao ha proximo status disponivel para esta proposta.", style="Muted.TLabel").grid(
                row=3, column=0, columnspan=2, sticky="w", pady=(8, 0)
            )
        detail_row = 4 if not labels else 3
        ttk.Label(frame, text="Observacao").grid(row=detail_row, column=0, sticky="nw", pady=(8, 0))
        self.observation = tk.Text(frame, width=42, height=5, wrap="word")
        self.observation.grid(row=detail_row, column=1, pady=(8, 0))
        buttons = ttk.Frame(frame)
        buttons.grid(row=detail_row + 1, column=0, columnspan=2, sticky="e", pady=(14, 0))
        icon_button(buttons, "save", "Aplicar", command=self.save, style="Accent.TButton").pack(side="left", padx=(0, 8))
        icon_button(buttons, "cancel", "Cancelar", command=self.destroy).pack(side="left")
        master.apply_non_ttk_colors(self)

    def save(self):
        if not self.status_var.get():
            messagebox.showwarning("Status", "Nao ha proximo status disponivel para esta proposta.", parent=self)
            return
        new_status = self.status_choices.get(self.status_var.get(), self.status_var.get())
        remanagement_source_id = None
        remanagement_note = ""
        confirm_stockroom_delivery = False
        if (
            self.area == "EXPEDICAO"
            and (self.process["status_expedicao"] or "") == "ENTREGUE_PARCIAL"
            and normalize_status(new_status) == "ENTREGUE"
            and self.repo.expedition_completion_requires_remanagement(self.process)
        ):
            if not messagebox.askyesno(
                "Entrega parcial",
                "Proposta produzida parcialmente. Deseja remanejar material de outra proposta?",
                parent=self,
            ):
                return
            selector = RemanagementSourceDialog(self.master, self.repo, self.process)
            self.wait_window(selector)
            if not selector.selected_process_id:
                return
            remanagement_note = simpledialog.askstring(
                "Itens remanejados",
                "Descreva quais itens foram remanejados:",
                parent=self,
            )
            if remanagement_note is None:
                return
            if not remanagement_note.strip():
                messagebox.showwarning("Itens remanejados", "Informe quais itens foram remanejados.", parent=self)
                return
            remanagement_source_id = selector.selected_process_id
        if (
            self.area == "EXPEDICAO"
            and normalize_status(new_status) == "ENTREGUE"
            and self.repo.stockroom_delivery_required(self.process)
        ):
            if not messagebox.askyesno(
                "Almoxarifado",
                "Tem parafusos no Almoxarifado. Confirmar entrega dos parafusos?",
                parent=self,
            ):
                return
            confirm_stockroom_delivery = True
        try:
            if remanagement_source_id:
                self.repo.remanage_material_to_production(remanagement_source_id, self.user, remanagement_note, self.process)
            self.repo.update_status(
                self.process["id"],
                self.area,
                new_status,
                self.observation.get("1.0", "end").strip(),
                self.user,
                allow_partial_delivery_completion=bool(remanagement_source_id),
            )
            if confirm_stockroom_delivery:
                self.repo.confirm_stockroom_delivery(self.process["id"], self.user)
        except AppError as exc:
            messagebox.showerror("Status", str(exc), parent=self)
            return
        self.saved = True
        self.destroy()


class BatchStatusDialog(tk.Toplevel):
    def __init__(self, master, repo, process_count, default_area, allowed_areas=None, process_ids=None):
        super().__init__(master)
        self.repo = repo
        self.allowed_areas = allowed_areas or list(AREAS.keys())
        self.process_ids = process_ids or []
        self.saved = False
        self.configure(background=COLOR_PALETTES[master.config_data.get("color_palette", "aurora")]["bg"])
        self.title("Alterar status em lote")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        frame = ttk.Frame(self, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(
            frame,
            text=f"{process_count} proposta(s) selecionada(s)",
            font=(FONT_FAMILY, 11, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        ttk.Label(frame, text="Area").grid(row=1, column=0, sticky="w")
        self.area_var = tk.StringVar(value=default_area if default_area in self.allowed_areas else self.allowed_areas[0])
        area_combo = ttk.Combobox(frame, textvariable=self.area_var, values=self.allowed_areas, state="readonly", width=34)
        area_combo.grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Label(frame, text="Novo status").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.status_var = tk.StringVar()
        self.status_combo = ttk.Combobox(frame, textvariable=self.status_var, state="readonly", width=34)
        self.status_combo.grid(row=2, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(frame, text="Observacao").grid(row=3, column=0, sticky="nw", pady=(8, 0))
        self.observation = tk.Text(frame, width=42, height=5, wrap="word")
        self.observation.grid(row=3, column=1, pady=(8, 0))
        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(14, 0))
        icon_button(buttons, "save", "Aplicar", command=self.save, style="Accent.TButton").pack(side="left", padx=(0, 8))
        icon_button(buttons, "cancel", "Cancelar", command=self.destroy).pack(side="left")
        area_combo.bind("<<ComboboxSelected>>", lambda _e: self.load_statuses())
        self.load_statuses()
        master.apply_non_ttk_colors(self)

    def load_statuses(self):
        area = self.area_var.get()
        statuses = self.repo.list_status(area)
        if self.process_ids and area in AREAS:
            common = None
            for process_id in self.process_ids:
                process = self.repo.get_process(process_id)
                if not process:
                    continue
                options = set(self.repo.next_status_options(area, process))
                common = options if common is None else common & options
            if common is not None:
                statuses = [status for status in STATUS_FLOW_ORDER.get(area, statuses) if status in common]
        self.status_choices = {area_status_label(area, status): status for status in statuses}
        labels = list(self.status_choices.keys())
        self.status_combo["values"] = labels
        self.status_var.set(labels[0] if labels else "")

    def save(self):
        if not self.status_var.get():
            messagebox.showwarning("Alterar status", "Selecione um status.", parent=self)
            return
        self.saved = True
        self.destroy()


class DualTreeDragController:
    def __init__(self, dialog, source_tree, target_tree, move_callback, action_text):
        self.dialog = dialog
        self.source_tree = source_tree
        self.target_tree = target_tree
        self.move_callback = move_callback
        self.action_text = action_text
        self.start_x = 0
        self.start_y = 0
        self.dragging = False
        self.ghost = None
        source_tree.bind("<ButtonPress-1>", self.on_press, add="+")
        source_tree.bind("<B1-Motion>", self.on_motion, add="+")
        source_tree.bind("<ButtonRelease-1>", self.on_release, add="+")

    def on_press(self, event):
        item_id = self.source_tree.identify_row(event.y)
        if not item_id:
            self.dragging = False
            return
        if item_id not in self.source_tree.selection():
            self.source_tree.selection_set(item_id)
        self.start_x = event.x_root
        self.start_y = event.y_root
        self.dragging = False

    def on_motion(self, event):
        if not self.source_tree.selection():
            return
        if not self.dragging and abs(event.x_root - self.start_x) + abs(event.y_root - self.start_y) < 6:
            return
        if not self.dragging:
            self.dragging = True
            self.show_ghost()
        self.move_ghost(event.x_root, event.y_root)

    def on_release(self, event):
        if not self.dragging:
            return
        self.hide_ghost()
        self.dragging = False
        if self.pointer_over_target(event.x_root, event.y_root):
            self.move_callback()

    def show_ghost(self):
        lines = self.drag_lines()
        if not lines:
            lines = [f"{self.action_text}: {len(self.source_tree.selection())} proposta(s)"]
        if len(lines) > 8:
            remaining = len(lines) - 8
            lines = lines[:8] + [f"+ {remaining} proposta(s)"]
        text = "\n".join(lines)
        self.ghost = tk.Label(
            self.dialog,
            text=text,
            background="#38bdf8",
            foreground="#0f172a",
            borderwidth=1,
            relief="solid",
            padx=10,
            pady=5,
            font=(FONT_FAMILY, 9, "bold"),
            justify="left",
            anchor="w",
        )
        self.ghost.lift()

    def drag_lines(self):
        lines = []
        columns = list(self.source_tree["columns"])
        for item_id in self.source_tree.selection():
            values = list(self.source_tree.item(item_id, "values"))
            data = {column: values[index] for index, column in enumerate(columns) if index < len(values)}
            proposal = str(data.get("proposta") or "").strip()
            client = str(data.get("cliente") or "").strip()
            if proposal and client:
                lines.append(f"{client.upper()} - {proposal}")
            elif proposal:
                lines.append(proposal)
            elif client:
                lines.append(client.upper())
        return lines

    def move_ghost(self, root_x, root_y):
        if not self.ghost:
            return
        x = root_x - self.dialog.winfo_rootx() + 12
        y = root_y - self.dialog.winfo_rooty() + 12
        self.ghost.place(x=x, y=y)

    def hide_ghost(self):
        if self.ghost:
            self.ghost.destroy()
            self.ghost = None

    def pointer_over_target(self, root_x, root_y):
        widget = self.dialog.winfo_containing(root_x, root_y)
        target_path = str(self.target_tree)
        while widget is not None:
            if str(widget) == target_path:
                return True
            widget = widget.master
        return False


class BatchStatusSelectionDialog(tk.Toplevel):
    def __init__(self, master, repo, user, default_area, initial_process_ids=None):
        super().__init__(master)
        self.repo = repo
        self.user = user
        self.selected_ids = []
        self.process_cache = {}
        self.changed = False
        self.allowed_areas = visible_area_names(user)
        self.configure(background=COLOR_PALETTES[master.config_data.get("color_palette", "aurora")]["bg"])
        self.title("Alterar status em lote")
        self.geometry("1040x620")
        self.transient(master)
        self.grab_set()

        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)
        top = ttk.Frame(frame)
        top.pack(fill="x")
        ttk.Label(top, text="Buscar proposta, cliente, site ou lote").pack(side="left")
        self.search_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.search_var, width=36).pack(side="left", padx=(8, 8))
        ttk.Label(top, text="Area").pack(side="left", padx=(8, 4))
        self.area_var = tk.StringVar(value=default_area if default_area in self.allowed_areas else (self.allowed_areas[0] if self.allowed_areas else ""))
        self.area_combo = ttk.Combobox(top, textvariable=self.area_var, values=self.allowed_areas, width=22, state="readonly")
        self.area_combo.pack(side="left", padx=(0, 8))
        icon_button(top, "search", "Pesquisar", command=self.load_candidates, style="SmallAccent.TButton").pack(side="left")

        body = ttk.Frame(frame)
        body.pack(fill="both", expand=True, pady=(12, 0))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(2, weight=1)
        body.rowconfigure(1, weight=1)

        ttk.Label(body, text="Propostas encontradas").grid(row=0, column=0, sticky="w")
        ttk.Label(body, text="Propostas para alterar").grid(row=0, column=2, sticky="w")
        self.candidate_tree = ttk.Treeview(
            body,
            columns=("proposta", "cliente", "obra_site", "lote", "status"),
            show="headings",
            selectmode="extended",
            height=14,
        )
        self.selected_tree = ttk.Treeview(
            body,
            columns=("proposta", "cliente", "obra_site", "lote", "status"),
            show="headings",
            selectmode="extended",
            height=14,
        )
        for tree in (self.candidate_tree, self.selected_tree):
            for col, label, width in (
                ("proposta", "Proposta", 115),
                ("cliente", "Cliente", 170),
                ("obra_site", "Site/Obra", 150),
                ("lote", "Lote", 90),
                ("status", "Status atual", 170),
            ):
                tree.heading(col, text=label)
                tree.column(col, width=width, anchor="center", stretch=True)
        self.candidate_tree.grid(row=1, column=0, sticky="nsew")
        self.selected_tree.grid(row=1, column=2, sticky="nsew")
        self.candidate_tree.bind("<Double-1>", lambda _e: self.add_candidates())
        self.selected_tree.bind("<Double-1>", lambda _e: self.remove_selected())
        self.drag_to_selected = DualTreeDragController(self, self.candidate_tree, self.selected_tree, self.add_candidates, "Adicionar")
        self.drag_to_candidates = DualTreeDragController(self, self.selected_tree, self.candidate_tree, self.remove_selected, "Remover")
        actions = ttk.Frame(body)
        actions.grid(row=1, column=1, sticky="ns", padx=10)
        icon_button(actions, "new", "Adicionar", command=self.add_candidates, style="SmallAccent.TButton").pack(fill="x", pady=(34, 8))
        icon_button(actions, "delete", "Remover", command=self.remove_selected, style="Small.TButton").pack(fill="x")

        bottom = ttk.Frame(frame)
        bottom.pack(fill="x", pady=(12, 0))
        ttk.Label(bottom, text="Novo status").pack(side="left")
        self.status_var = tk.StringVar()
        self.status_combo = ttk.Combobox(bottom, textvariable=self.status_var, width=34, state="readonly")
        self.status_combo.pack(side="left", padx=(8, 12))
        ttk.Label(bottom, text="Observacao").pack(side="left")
        self.observation_var = tk.StringVar()
        ttk.Entry(bottom, textvariable=self.observation_var, width=42).pack(side="left", padx=(8, 0), fill="x", expand=True)

        footer = ttk.Frame(frame)
        footer.pack(fill="x", pady=(12, 0))
        self.summary_var = tk.StringVar(value="Nenhuma proposta adicionada.")
        ttk.Label(footer, textvariable=self.summary_var, style="Muted.TLabel").pack(side="left")
        icon_button(footer, "batch", "Aplicar lote", command=self.apply, style="Accent.TButton").pack(side="right", padx=(8, 0))
        icon_button(footer, "cancel", "Cancelar", command=self.destroy).pack(side="right")

        self.area_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_area_changed())
        self.search_var.trace_add("write", lambda *_args: self.load_candidates())
        for process_id in initial_process_ids or []:
            process = self.repo.get_process(process_id)
            if process:
                self.add_process(process)
        self.load_candidates()
        self.refresh_selected()
        master.apply_non_ttk_colors(self)

    def current_area(self):
        return self.area_var.get()

    def on_area_changed(self):
        self.load_candidates()
        self.refresh_selected()

    def status_for_area(self, process):
        area = self.current_area()
        if area in AREAS:
            return process[AREAS[area]["column"]] or process["status_geral"] or ""
        return process["status_geral"] or ""

    def process_visible_in_selected_area(self, process, area=None):
        area = area or self.current_area()
        if area == "CONTROLE GERAL":
            return True
        if area not in AREAS:
            return False
        area_status = process[AREAS[area]["column"]] or ""
        return bool(area_status) and self.repo.visible_for_area(process, area)

    def load_candidates(self):
        if not getattr(self, "candidate_tree", None):
            return
        self.candidate_tree.delete(*self.candidate_tree.get_children())
        area = self.current_area()
        if not area:
            return
        text = self.search_var.get().strip()
        rows = self.repo.list_processes({"text": text} if text else {})
        count = 0
        for row in rows:
            if row["id"] in self.selected_ids:
                continue
            if not self.process_visible_in_selected_area(row, area):
                continue
            options = set(self.repo.next_status_options(area, row))
            if area == "EXPEDICAO" and (row["status_expedicao"] or "") == "ENTREGUE_PARCIAL" and self.repo.expedition_completion_requires_remanagement(row):
                options.discard("ENTREGUE")
            if not options:
                continue
            self.process_cache[row["id"]] = row
            self.candidate_tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    row["proposta"],
                    row["cliente"],
                    row["obra_site"],
                    row["lote"],
                    area_status_label(area, self.status_for_area(row)),
                ),
            )
            count += 1
            if count >= 300:
                break

    def add_candidates(self):
        ids = [int(item) for item in self.candidate_tree.selection()]
        if not ids:
            messagebox.showwarning("Alterar status em lote", "Selecione uma ou mais propostas encontradas.", parent=self)
            return
        for process_id in ids:
            process = self.repo.get_process(process_id)
            if process:
                self.add_process(process)
        self.load_candidates()
        self.refresh_selected()

    def add_process(self, process):
        if process["id"] not in self.selected_ids:
            self.selected_ids.append(process["id"])
        self.process_cache[process["id"]] = process

    def remove_selected(self):
        ids = {int(item) for item in self.selected_tree.selection()}
        if not ids:
            return
        self.selected_ids = [process_id for process_id in self.selected_ids if process_id not in ids]
        self.load_candidates()
        self.refresh_selected()

    def refresh_selected(self):
        self.selected_tree.delete(*self.selected_tree.get_children())
        area = self.current_area()
        common = None
        valid_selected = []
        for process_id in self.selected_ids:
            process = self.repo.get_process(process_id)
            if not process:
                continue
            if not self.process_visible_in_selected_area(process, area):
                continue
            self.process_cache[process_id] = process
            options = set(self.repo.next_status_options(area, process)) if area else set()
            if area == "EXPEDICAO" and (process["status_expedicao"] or "") == "ENTREGUE_PARCIAL" and self.repo.expedition_completion_requires_remanagement(process):
                options.discard("ENTREGUE")
            if not options:
                continue
            common = options if common is None else common & options
            valid_selected.append(process_id)
            self.selected_tree.insert(
                "",
                "end",
                iid=str(process_id),
                values=(
                    process["proposta"],
                    process["cliente"],
                    process["obra_site"],
                    process["lote"],
                    area_status_label(area, self.status_for_area(process)),
                ),
            )
        self.selected_ids = valid_selected
        ordered = [status for status in STATUS_FLOW_ORDER.get(area, self.repo.list_status(area)) if common and status in common]
        self.status_choices = {area_status_label(area, status): status for status in ordered}
        labels = list(self.status_choices.keys())
        self.status_combo["values"] = labels
        self.status_var.set(labels[0] if labels else "")
        if self.selected_ids and not labels:
            self.summary_var.set(f"{len(self.selected_ids)} proposta(s), mas sem proximo status comum para a area escolhida.")
        else:
            self.summary_var.set(f"{len(self.selected_ids)} proposta(s) adicionada(s).")

    def apply(self):
        if not self.selected_ids:
            messagebox.showwarning("Alterar status em lote", "Adicione pelo menos uma proposta na lista.", parent=self)
            return
        if not self.status_var.get():
            messagebox.showwarning("Alterar status em lote", "Nao existe status comum para as propostas selecionadas.", parent=self)
            return
        area = self.current_area()
        status = self.status_choices.get(self.status_var.get(), self.status_var.get())
        if not messagebox.askyesno(
            "Alterar status em lote",
            f"Aplicar {area_status_label(area, status)} em {len(self.selected_ids)} proposta(s)?",
            parent=self,
        ):
            return
        changed = 0
        failures = []
        locked = []
        for process_id in list(self.selected_ids):
            process = self.repo.get_process(process_id)
            proposal = process["proposta"] if process else str(process_id)
            try:
                self.repo.acquire_process_lock(process_id, self.user)
                locked.append(process_id)
                self.repo.update_status(process_id, area, status, self.observation_var.get().strip(), self.user)
                changed += 1
            except AppError as exc:
                failures.append(f"{proposal}: {exc}")
        for process_id in locked:
            try:
                self.repo.release_process_lock(process_id, self.user)
            except Exception:
                pass
        self.changed = changed > 0
        if failures:
            message = f"{changed} proposta(s) alterada(s).\n\nNao alteradas:\n" + "\n".join(failures[:12])
            if len(failures) > 12:
                message += f"\n... e mais {len(failures) - 12}."
            messagebox.showwarning("Alterar status em lote", message, parent=self)
        else:
            messagebox.showinfo("Alterar status em lote", f"{changed} proposta(s) alterada(s) com sucesso.", parent=self)
        self.destroy()


class RemanagementSourceDialog(tk.Toplevel):
    def __init__(self, master, repo, target_process):
        super().__init__(master)
        self.repo = repo
        self.target_process = target_process
        self.selected_process_id = None
        self.configure(background=COLOR_PALETTES[master.config_data.get("color_palette", "aurora")]["bg"])
        self.title("Selecionar proposta origem")
        self.geometry("820x430")
        self.transient(master)
        self.grab_set()

        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text=f"Selecione a proposta de onde o material sera retirado para completar {target_process['proposta']}.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 10))

        self.search_var = tk.StringVar()
        search = ttk.Frame(frame)
        search.pack(fill="x", pady=(0, 8))
        ttk.Label(search, text="Buscar proposta").pack(side="left")
        ttk.Entry(search, textvariable=self.search_var, width=22).pack(side="left", padx=(6, 8))
        icon_button(search, "search", "Filtrar", command=self.load, style="Small.TButton").pack(side="left")

        self.tree = ttk.Treeview(
            frame,
            columns=("proposta", "cliente", "obra_site", "peso", "status"),
            show="headings",
            selectmode="browse",
        )
        for col, label, width in (
            ("proposta", "Proposta", 110),
            ("cliente", "Cliente", 190),
            ("obra_site", "Obra/Site", 170),
            ("peso", "Peso", 80),
            ("status", "Status producao", 150),
        ):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.confirm())

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        icon_button(buttons, "save", "Selecionar", command=self.confirm, style="Accent.TButton").pack(side="right", padx=(8, 0))
        icon_button(buttons, "cancel", "Cancelar", command=self.destroy).pack(side="right")

        self.search_var.trace_add("write", lambda *_args: self.load())
        self.load()
        master.apply_non_ttk_colors(self)

    def display_weight(self, value):
        if value is None:
            return ""
        if float(value).is_integer():
            return str(int(value))
        return f"{float(value):.2f}"

    def load(self):
        self.tree.delete(*self.tree.get_children())
        search = self.search_var.get().strip().upper()
        for row in self.repo.list_remanagement_source_candidates(self.target_process["id"]):
            if search and search not in (row["proposta"] or "").upper() and search not in (row["cliente"] or "").upper():
                continue
            self.tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    row["proposta"],
                    row["cliente"],
                    row["obra_site"] or "",
                    self.display_weight(row["peso"]),
                    status_label(row["status_producao"]),
                ),
            )

    def confirm(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Remanejamento", "Selecione uma proposta origem.", parent=self)
            return
        self.selected_process_id = int(selection[0])
        self.destroy()


class EarlyRemanagementDeliveryDialog(tk.Toplevel):
    def __init__(self, master, repo, user):
        super().__init__(master)
        self.repo = repo
        self.user = user
        self.destination_id = None
        self.source_id = None
        self.changed = False
        self.configure(background=COLOR_PALETTES[master.config_data.get("color_palette", "aurora")]["bg"])
        self.title("Entrega por remanejamento")
        self.geometry("1080x650")
        self.transient(master)
        self.grab_set()

        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Entrega por remanejamento", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text="Use quando uma proposta sera entregue ao cliente com material retirado de outra proposta pronta. A proposta origem volta para Producao como item pendente.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 12))

        body = ttk.Frame(frame)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)

        destination_box = ttk.LabelFrame(body, text="Proposta que sera entregue ao cliente", padding=10)
        source_box = ttk.LabelFrame(body, text="Proposta origem do material", padding=10)
        destination_box.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 8))
        source_box.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(8, 0))
        destination_box.rowconfigure(1, weight=1)
        destination_box.columnconfigure(0, weight=1)
        source_box.rowconfigure(1, weight=1)
        source_box.columnconfigure(0, weight=1)

        dest_search = ttk.Frame(destination_box)
        dest_search.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(dest_search, text="Buscar").pack(side="left")
        self.dest_search_var = tk.StringVar()
        ttk.Entry(dest_search, textvariable=self.dest_search_var, width=30).pack(side="left", padx=(6, 8), fill="x", expand=True)
        icon_button(dest_search, "search", "Pesquisar", command=self.load_destinations, style="Small.TButton").pack(side="left")

        source_search = ttk.Frame(source_box)
        source_search.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(source_search, text="Buscar").pack(side="left")
        self.source_search_var = tk.StringVar()
        ttk.Entry(source_search, textvariable=self.source_search_var, width=30).pack(side="left", padx=(6, 8), fill="x", expand=True)
        icon_button(source_search, "search", "Pesquisar", command=self.load_sources, style="Small.TButton").pack(side="left")

        self.dest_tree = ttk.Treeview(
            destination_box,
            columns=("proposta", "cliente", "obra_site", "status"),
            show="headings",
            selectmode="browse",
        )
        self.source_tree = ttk.Treeview(
            source_box,
            columns=("proposta", "cliente", "obra_site", "status"),
            show="headings",
            selectmode="browse",
        )
        for tree in (self.dest_tree, self.source_tree):
            for col, label, width in (
                ("proposta", "Proposta", 115),
                ("cliente", "Cliente", 185),
                ("obra_site", "Site/Obra", 155),
                ("status", "Status", 165),
            ):
                tree.heading(col, text=label)
                tree.column(col, width=width, anchor="center", stretch=True)
        self.dest_tree.grid(row=1, column=0, sticky="nsew")
        self.source_tree.grid(row=1, column=0, sticky="nsew")
        self.dest_tree.bind("<<TreeviewSelect>>", lambda _event: self.load_sources())
        self.dest_tree.bind("<Double-1>", lambda _event: self.note_text.focus_set())
        self.source_tree.bind("<Double-1>", lambda _event: self.note_text.focus_set())

        details = ttk.LabelFrame(frame, text="Itens remanejados", padding=10)
        details.pack(fill="x", pady=(12, 0))
        self.note_text = tk.Text(details, height=4, wrap="word")
        self.note_text.pack(fill="x", expand=True)

        footer = ttk.Frame(frame)
        footer.pack(fill="x", pady=(12, 0))
        icon_button(footer, "save", "Confirmar entrega", command=self.apply, style="Accent.TButton").pack(side="right", padx=(8, 0))
        icon_button(footer, "cancel", "Cancelar", command=self.destroy).pack(side="right")

        self.dest_search_var.trace_add("write", lambda *_args: self.load_destinations())
        self.source_search_var.trace_add("write", lambda *_args: self.load_sources())
        self.load_destinations()
        self.load_sources()
        master.apply_non_ttk_colors(self)

    def status_summary(self, row):
        if row["status_expedicao"]:
            return status_label(row["status_expedicao"])
        if row["status_galvanizacao"]:
            return status_label(row["status_galvanizacao"])
        if row["status_producao"]:
            return status_label(row["status_producao"])
        return status_label(row["status_geral"])

    def load_destinations(self):
        self.dest_tree.delete(*self.dest_tree.get_children())
        search = self.dest_search_var.get().strip()
        selected_source = self.selected_source_id(silent=True)
        for row in self.repo.list_early_delivery_destination_candidates(search):
            if selected_source and row["id"] == selected_source:
                continue
            self.dest_tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(row["proposta"], row["cliente"], row["obra_site"] or "", self.status_summary(row)),
            )

    def load_sources(self):
        self.source_tree.delete(*self.source_tree.get_children())
        search = self.source_search_var.get().strip().upper()
        selected_destination = self.selected_destination_id(silent=True)
        for row in self.repo.list_remanagement_source_candidates(selected_destination):
            if search and search not in (row["proposta"] or "").upper() and search not in (row["cliente"] or "").upper() and search not in (row["obra_site"] or "").upper():
                continue
            self.source_tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(row["proposta"], row["cliente"], row["obra_site"] or "", status_label(row["status_producao"])),
            )

    def selected_destination_id(self, silent=False):
        selection = self.dest_tree.selection()
        if not selection:
            if not silent:
                messagebox.showwarning("Entrega por remanejamento", "Selecione a proposta que sera entregue.", parent=self)
            return None
        return int(selection[0])

    def selected_source_id(self, silent=False):
        selection = self.source_tree.selection()
        if not selection:
            if not silent:
                messagebox.showwarning("Entrega por remanejamento", "Selecione a proposta origem do material.", parent=self)
            return None
        return int(selection[0])

    def apply(self):
        destination_id = self.selected_destination_id()
        source_id = self.selected_source_id()
        if not destination_id or not source_id:
            return
        note = self.note_text.get("1.0", "end").strip()
        if not note:
            messagebox.showwarning("Entrega por remanejamento", "Descreva quais itens foram remanejados.", parent=self)
            return
        destination = self.repo.get_process(destination_id)
        source = self.repo.get_process(source_id)
        if not messagebox.askyesno(
            "Confirmar entrega",
            f"Entregar {destination['proposta']} usando material da proposta {source['proposta']}?\n\nA proposta origem voltara para Producao como item pendente.",
            parent=self,
        ):
            return
        try:
            self.repo.deliver_by_material_remanagement(destination_id, source_id, self.user, note)
        except AppError as exc:
            messagebox.showerror("Entrega por remanejamento", str(exc), parent=self)
            return
        self.changed = True
        messagebox.showinfo("Entrega por remanejamento", "Entrega registrada e pendencia de reposicao criada.", parent=self)
        self.destroy()


class GalvanizationLoadDialog(tk.Toplevel):
    def __init__(self, master, repo, user, preselected_ids=None, load_id=None):
        super().__init__(master)
        self.repo = repo
        self.user = user
        self.preselected_ids = set(preselected_ids or [])
        self.items = {}
        self.saved = False
        self.load_id = load_id
        self.load_row = self.repo.get_galvanization_load(load_id) if load_id else None
        self.configure(background=COLOR_PALETTES[master.config_data.get("color_palette", "aurora")]["bg"])
        self.title("Editar carga de galvanizacao" if load_id else "Montar carga para galvanizacao")
        self.geometry("1060x640")
        self.transient(master)
        self.grab_set()

        container = ttk.Frame(self, padding=14)
        container.pack(fill="both", expand=True)

        top = ttk.LabelFrame(container, text="Dados da carga", padding=12)
        top.pack(fill="x")
        self.driver_var = tk.StringVar()
        self.max_weight_var = tk.StringVar()
        self.expected_return_var = tk.StringVar()
        self.search_proposal_var = tk.StringVar()
        self.search_client_var = tk.StringVar()
        self.total_var = tk.StringVar(value="Total da carga: 0")
        self.capacity_var = tk.StringVar(value="")
        ttk.Label(top, text="Motorista *").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.driver_var, width=34).grid(row=0, column=1, sticky="ew", padx=(6, 18))
        ttk.Label(top, text="Capacidade do caminhao").grid(row=0, column=2, sticky="w")
        ttk.Entry(top, textvariable=self.max_weight_var, width=16).grid(row=0, column=3, sticky="w", padx=(6, 18))
        ttk.Label(top, text="Prev. retorno").grid(row=0, column=4, sticky="w")
        ttk.Entry(top, textvariable=self.expected_return_var, width=14).grid(row=0, column=5, sticky="w", padx=(6, 18))
        ttk.Label(top, textvariable=self.total_var, style="KpiValue.TLabel").grid(row=0, column=6, sticky="w")
        ttk.Label(top, textvariable=self.capacity_var, style="Muted.TLabel").grid(row=1, column=1, columnspan=4, sticky="w", pady=(8, 0))
        top.columnconfigure(1, weight=1)

        body = ttk.Frame(container)
        body.pack(fill="both", expand=True, pady=(12, 0))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(2, weight=1)
        body.rowconfigure(1, weight=1)

        ttk.Label(body, text="Propostas liberadas para galvanizacao").grid(row=0, column=0, sticky="w")
        ttk.Label(body, text="Propostas na carga").grid(row=0, column=2, sticky="w")

        available = ttk.Frame(body)
        available.grid(row=1, column=0, sticky="nsew")
        selected = ttk.Frame(body)
        selected.grid(row=1, column=2, sticky="nsew")

        search = ttk.Frame(available)
        search.pack(fill="x", pady=(0, 8))
        ttk.Label(search, text="Proposta").pack(side="left")
        ttk.Entry(search, textvariable=self.search_proposal_var, width=18).pack(side="left", padx=(6, 10))
        ttk.Label(search, text="Cliente").pack(side="left")
        ttk.Entry(search, textvariable=self.search_client_var, width=20).pack(side="left", padx=(6, 10))
        icon_button(search, "search", "Pesquisar", command=self.load_candidates, style="SmallAccent.TButton").pack(side="left")

        self.available_tree = ttk.Treeview(
            available,
            columns=("proposta", "cliente", "peso", "status"),
            show="headings",
            selectmode="extended",
        )
        for col, label, width in (
            ("proposta", "Proposta", 120),
            ("cliente", "Cliente", 160),
            ("peso", "Peso", 90),
            ("status", "Status", 150),
        ):
            self.available_tree.heading(col, text=label)
            self.available_tree.column(col, width=width, anchor="center")
        self.available_tree.pack(fill="both", expand=True)

        self.load_tree = ttk.Treeview(
            selected,
            columns=("proposta", "cliente", "peso_total", "peso_enviado", "parcial"),
            show="headings",
            selectmode="extended",
        )
        for col, label, width in (
            ("proposta", "Proposta", 110),
            ("cliente", "Cliente", 140),
            ("peso_total", "Peso total", 90),
            ("peso_enviado", "Peso enviado", 100),
            ("parcial", "Parcial", 70),
        ):
            self.load_tree.heading(col, text=label)
            self.load_tree.column(col, width=width, anchor="center")
        self.load_tree.pack(fill="both", expand=True)
        self.load_tree.bind("<Double-1>", lambda _e: self.edit_selected_weight())

        self.drag_to_load = DualTreeDragController(self, self.available_tree, self.load_tree, self.add_selected, "Adicionar")
        self.drag_to_available = DualTreeDragController(self, self.load_tree, self.available_tree, self.remove_selected, "Remover")

        actions = ttk.Frame(body)
        actions.grid(row=1, column=1, sticky="ns", padx=10)
        icon_button(actions, "new", "Adicionar", command=self.add_selected, style="SmallAccent.TButton").pack(fill="x", pady=(34, 8))
        icon_button(actions, "delete", "Remover", command=self.remove_selected, style="Small.TButton").pack(fill="x", pady=(0, 8))
        icon_button(actions, "edit", "Editar peso", command=self.edit_selected_weight, style="Small.TButton").pack(fill="x")

        selected_buttons = ttk.Frame(selected)
        selected_buttons.pack(fill="x", pady=(8, 0))
        ttk.Label(
            selected_buttons,
            text="Arraste as propostas entre as listas ou use os botoes do meio.",
            style="Muted.TLabel",
        ).pack(side="left")

        footer = ttk.Frame(container)
        footer.pack(fill="x", pady=(12, 0))
        ttk.Label(
            footer,
            text="Dica: use peso menor que o total para enviar parcialmente uma proposta.",
            style="Muted.TLabel",
        ).pack(side="left")
        icon_button(footer, "save", "Salvar carga", command=self.save, style="Accent.TButton").pack(side="right", padx=(8, 0))
        icon_button(footer, "cancel", "Cancelar", command=self.destroy).pack(side="right")

        self.max_weight_var.trace_add("write", lambda *_args: self.update_totals())
        self.search_proposal_var.trace_add("write", lambda *_args: self.load_candidates())
        self.search_client_var.trace_add("write", lambda *_args: self.load_candidates())
        if self.load_row:
            self.driver_var.set(self.load_row["motorista"] or "")
            self.max_weight_var.set(self.display_weight(self.load_row["peso_maximo"]))
            self.expected_return_var.set(self.load_row["data_prevista_retorno"] or "")
            for row in self.repo.list_galvanization_load_items(load_id):
                self.items[row["processo_id"]] = {
                    "process_id": row["processo_id"],
                    "proposta": row["proposta"],
                    "cliente": row["cliente"],
                    "peso_total": row["peso_total_proposta"] or 0,
                    "peso_enviado": row["peso_enviado"] or 0,
                    "observacao": row["observacao"] or "",
                }
        self.load_candidates()
        for process_id in self.preselected_ids:
            if str(process_id) in self.available_tree.get_children():
                self.available_tree.selection_add(str(process_id))
        if self.available_tree.selection():
            self.add_selected(prompt_weight=False)
        self.refresh_load_tree()
        master.apply_non_ttk_colors(self)

    def load_candidates(self):
        self.available_tree.delete(*self.available_tree.get_children())
        proposal_filter = self.search_proposal_var.get().strip().upper()
        client_filter = self.search_client_var.get().strip().upper()
        for row in self.repo.list_galvanization_load_candidates():
            if row["id"] in self.items:
                continue
            if proposal_filter and proposal_filter not in (row["proposta"] or "").upper():
                continue
            if client_filter and client_filter not in (row["cliente"] or "").upper():
                continue
            self.available_tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(row["proposta"], row["cliente"], self.display_weight(row["peso"]), status_label(row["status_galvanizacao"])),
            )

    def display_weight(self, value):
        if value is None:
            return ""
        if float(value).is_integer():
            return str(int(value))
        return f"{float(value):.2f}"

    def add_selected(self, prompt_weight=True):
        selected_ids = self.available_tree.selection()
        if not selected_ids:
            messagebox.showwarning("Montar carga", "Selecione uma ou mais propostas.", parent=self)
            return
        for item_id in selected_ids:
            process_id = int(item_id)
            if process_id in self.items:
                continue
            process = self.repo.get_process(process_id)
            if not process:
                continue
            sent_weight = process["peso"] or 0
            if prompt_weight:
                value = simpledialog.askstring(
                    "Peso enviado",
                    f"Peso enviado da proposta {process['proposta']}:\nPeso total cadastrado: {self.display_weight(process['peso']) or 'sem peso'}",
                    parent=self,
                    initialvalue=self.display_weight(sent_weight),
                )
                if value is None:
                    continue
                try:
                    sent_weight = self.repo.to_float(value)
                except AppError as exc:
                    messagebox.showerror("Peso enviado", str(exc), parent=self)
                    continue
            self.items[process_id] = {
                "process_id": process_id,
                "proposta": process["proposta"],
                "cliente": process["cliente"],
                "peso_total": process["peso"] or 0,
                "peso_enviado": sent_weight or 0,
                "observacao": "",
            }
        self.load_candidates()
        self.refresh_load_tree()

    def edit_selected_weight(self):
        selection = self.load_tree.selection()
        if not selection:
            messagebox.showwarning("Montar carga", "Selecione uma proposta na carga.", parent=self)
            return
        for item_id in selection:
            process_id = int(item_id)
            item = self.items.get(process_id)
            if not item:
                continue
            value = simpledialog.askstring(
                "Peso enviado",
                f"Novo peso enviado da proposta {item['proposta']}:",
                parent=self,
                initialvalue=self.display_weight(item["peso_enviado"]),
            )
            if value is None:
                continue
            try:
                sent_weight = self.repo.to_float(value)
            except AppError as exc:
                messagebox.showerror("Peso enviado", str(exc), parent=self)
                continue
            item["peso_enviado"] = sent_weight or 0
        self.refresh_load_tree()

    def remove_selected(self):
        for item_id in self.load_tree.selection():
            self.items.pop(int(item_id), None)
        self.load_candidates()
        self.refresh_load_tree()

    def refresh_load_tree(self):
        self.load_tree.delete(*self.load_tree.get_children())
        for process_id, item in self.items.items():
            partial = bool(item["peso_total"] and item["peso_enviado"] < item["peso_total"])
            self.load_tree.insert(
                "",
                "end",
                iid=str(process_id),
                values=(
                    item["proposta"],
                    item["cliente"],
                    self.display_weight(item["peso_total"]),
                    self.display_weight(item["peso_enviado"]),
                    "Sim" if partial else "Nao",
                ),
            )
        self.update_totals()

    def update_totals(self):
        total = sum(float(item.get("peso_enviado") or 0) for item in self.items.values())
        self.total_var.set(f"Total da carga: {total:g}")
        try:
            max_weight = self.repo.to_float(self.max_weight_var.get())
        except AppError:
            self.capacity_var.set("Capacidade invalida.")
            return
        if max_weight:
            remaining = max_weight - total
            if remaining < 0:
                self.capacity_var.set(f"Excedeu a capacidade em {abs(remaining):g}.")
            else:
                self.capacity_var.set(f"Disponivel no caminhao: {remaining:g}.")
        else:
            self.capacity_var.set("")

    def save(self):
        try:
            self.load_id = self.repo.save_galvanization_load(
                self.driver_var.get(),
                self.max_weight_var.get(),
                self.expected_return_var.get(),
                list(self.items.values()),
                self.user,
                self.load_id,
            )
        except AppError as exc:
            messagebox.showerror("Montar carga", str(exc), parent=self)
            return
        self.saved = True
        messagebox.showinfo("Montar carga", f"Carga {self.load_id} salva aguardando liberacao.", parent=self)
        self.destroy()


class GalvanizationLoadManagerDialog(tk.Toplevel):
    def __init__(self, master, repo, user, preselected_ids=None):
        super().__init__(master)
        self.repo = repo
        self.user = user
        self.preselected_ids = preselected_ids or []
        self.changed = False
        self.configure(background=COLOR_PALETTES[master.config_data.get("color_palette", "aurora")]["bg"])
        self.title("Cargas de galvanizacao")
        self.geometry("920x520")
        self.transient(master)
        self.grab_set()

        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            frame,
            columns=("id", "status", "motorista", "peso", "itens", "prev_retorno", "retorno", "criado", "usuario"),
            show="headings",
            selectmode="browse",
        )
        for col, label, width in (
            ("id", "Carga", 70),
            ("status", "Status", 160),
            ("motorista", "Motorista", 170),
            ("peso", "Peso", 90),
            ("itens", "Propostas", 90),
            ("prev_retorno", "Prev. retorno", 110),
            ("retorno", "Retorno", 110),
            ("criado", "Criada em", 150),
            ("usuario", "Usuario", 100),
        ):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.edit_load())

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        icon_button(buttons, "new", "Nova carga", command=self.new_load, style="Accent.TButton").pack(side="left")
        icon_button(buttons, "edit", "Editar carga", command=self.edit_load).pack(side="left", padx=8)
        icon_button(buttons, "save", "Liberar carga", command=self.release_load).pack(side="left")
        icon_button(buttons, "load", "Marcar retorno", command=self.return_load).pack(side="left", padx=8)
        icon_button(buttons, "refresh", "Atualizar", command=self.load).pack(side="left", padx=8)
        icon_button(buttons, "cancel", "Fechar", command=self.destroy).pack(side="right")

        self.load()
        master.apply_non_ttk_colors(self)

    def display_weight(self, value):
        if value is None:
            return ""
        if float(value).is_integer():
            return str(int(value))
        return f"{float(value):.2f}"

    def load(self):
        self.tree.delete(*self.tree.get_children())
        for row in self.repo.list_galvanization_loads():
            self.tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    row["id"],
                    load_status_label(row["status"]),
                    row["motorista"],
                    self.display_weight(row["peso_total"]),
                    row["item_count"],
                    row["data_prevista_retorno"] or "",
                    row["data_retorno"] or "",
                    row["criado_em"],
                    row["criado_por"],
                ),
            )

    def selected_load_id(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Cargas", "Selecione uma carga.", parent=self)
            return None
        return int(selection[0])

    def new_load(self):
        dialog = GalvanizationLoadDialog(self.master, self.repo, self.user, self.preselected_ids)
        self.wait_window(dialog)
        if dialog.saved:
            self.changed = True
            self.preselected_ids = []
            self.load()

    def edit_load(self):
        load_id = self.selected_load_id()
        if not load_id:
            return
        load = self.repo.get_galvanization_load(load_id)
        if load and load["status"] != "AGUARDANDO_LIBERACAO":
            messagebox.showwarning("Cargas", "Apenas cargas aguardando liberacao podem ser editadas.", parent=self)
            return
        dialog = GalvanizationLoadDialog(self.master, self.repo, self.user, load_id=load_id)
        self.wait_window(dialog)
        if dialog.saved:
            self.changed = True
            self.load()

    def release_load(self):
        load_id = self.selected_load_id()
        if not load_id:
            return
        if not messagebox.askyesno("Liberar carga", f"Liberar a carga {load_id} para envio?", parent=self):
            return
        try:
            self.repo.release_galvanization_load(load_id, self.user)
        except AppError as exc:
            messagebox.showerror("Liberar carga", str(exc), parent=self)
            return
        self.changed = True
        self.load()
        messagebox.showinfo("Liberar carga", f"Carga {load_id} liberada para envio.", parent=self)

    def return_load(self):
        load_id = self.selected_load_id()
        if not load_id:
            return
        if not messagebox.askyesno(
            "Retorno da carga",
            f"Marcar a carga {load_id} como retornada da galvanizacao?\n\nAs propostas dessa carga serao marcadas como retornadas.",
            parent=self,
        ):
            return
        try:
            self.repo.mark_galvanization_load_returned(load_id, self.user)
        except AppError as exc:
            messagebox.showerror("Retorno da carga", str(exc), parent=self)
            return
        self.changed = True
        self.load()
        messagebox.showinfo("Retorno da carga", f"Carga {load_id} marcada como retornada.", parent=self)


class UserEditorDialog(tk.Toplevel):
    def __init__(self, master, repo, user_row=None):
        super().__init__(master)
        self.repo = repo
        self.user_row = user_row
        self.saved = False
        self.configure(background=COLOR_PALETTES[master.config_data.get("color_palette", "aurora")]["bg"])
        self.title("Editar usuario" if user_row else "Novo usuario")
        self.geometry("520x520")
        self.transient(master)
        self.grab_set()

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        self.nome_var = tk.StringVar(value=user_row["nome"] if user_row else "")
        self.login_var = tk.StringVar(value=user_row["login"] if user_row else "")
        self.password_var = tk.StringVar()
        self.active_var = tk.BooleanVar(value=bool(user_row["ativo"]) if user_row else True)
        current_profile = user_row["perfil"] if user_row else "consulta"
        self.profile_var = tk.StringVar(value=profile_label(current_profile))
        self.area_vars = {}

        ttk.Label(frame, text="Nome *").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self.nome_var).grid(row=0, column=1, sticky="ew", pady=6)
        ttk.Label(frame, text="Login *").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self.login_var).grid(row=1, column=1, sticky="ew", pady=6)
        ttk.Label(frame, text="Senha" + (" *" if not user_row else "")).grid(row=2, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self.password_var, show="*").grid(row=2, column=1, sticky="ew", pady=6)
        if user_row:
            ttk.Label(frame, text="Deixe em branco para manter a senha atual.", style="Muted.TLabel").grid(
                row=3, column=1, sticky="w"
            )

        ttk.Label(frame, text="Perfil").grid(row=4, column=0, sticky="w", pady=(12, 6))
        profile_combo = ttk.Combobox(
            frame,
            textvariable=self.profile_var,
            values=[label for _key, label in PROFILE_OPTIONS],
            state="readonly",
        )
        profile_combo.grid(row=4, column=1, sticky="ew", pady=(12, 6))
        profile_combo.bind("<<ComboboxSelected>>", lambda _e: self.apply_profile_defaults())

        areas_box = ttk.LabelFrame(frame, text="Areas que o usuario pode alterar", padding=10)
        areas_box.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(10, 6))
        selected_areas = user_areas(user_row) if user_row else set(PROFILE_DEFAULT_AREAS["consulta"])
        for idx, area in enumerate(AREAS):
            var = tk.BooleanVar(value=area in selected_areas)
            self.area_vars[area] = var
            ttk.Checkbutton(areas_box, text=area.title(), variable=var).grid(row=idx, column=0, sticky="w", pady=2)

        ttk.Checkbutton(frame, text="Usuario ativo", variable=self.active_var).grid(row=6, column=1, sticky="w", pady=8)
        ttk.Label(
            frame,
            text="Consulta visualiza o sistema, mas nao altera cadastros nem status.",
            style="Muted.TLabel",
            wraplength=420,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(4, 0))

        buttons = ttk.Frame(frame)
        buttons.grid(row=8, column=0, columnspan=2, sticky="e", pady=(16, 0))
        icon_button(buttons, "save", "Salvar", command=self.save, style="Accent.TButton").pack(side="left", padx=(0, 8))
        icon_button(buttons, "cancel", "Cancelar", command=self.destroy).pack(side="left")
        master.apply_non_ttk_colors(self)

    def selected_profile(self):
        label = self.profile_var.get()
        return next((key for key, text in PROFILE_OPTIONS if text == label), "consulta")

    def apply_profile_defaults(self):
        defaults = set(PROFILE_DEFAULT_AREAS.get(self.selected_profile(), []))
        for area, var in self.area_vars.items():
            var.set(area in defaults)

    def save(self):
        nome = self.nome_var.get().strip()
        login = self.login_var.get().strip()
        password = self.password_var.get()
        profile = self.selected_profile()
        areas = [area for area, var in self.area_vars.items() if var.get()]
        if profile == "admin":
            areas = list(AREAS.keys())
        if not nome:
            messagebox.showerror("Usuarios", "Informe o nome.", parent=self)
            return
        if not login:
            messagebox.showerror("Usuarios", "Informe o login.", parent=self)
            return
        if not self.user_row and not password:
            messagebox.showerror("Usuarios", "Informe a senha inicial.", parent=self)
            return
        if profile != "consulta" and not areas:
            messagebox.showerror("Usuarios", "Selecione pelo menos uma area de acesso.", parent=self)
            return
        try:
            if self.user_row:
                values = [nome, login, profile, 1 if self.active_var.get() else 0, area_csv(areas)]
                sql = "UPDATE usuarios SET nome = ?, login = ?, perfil = ?, ativo = ?, areas_acesso = ?"
                if password:
                    salt, digest = pbkdf2_hash(password)
                    sql += ", senha_salt = ?, senha_hash = ?"
                    values.extend([salt, digest])
                sql += " WHERE id = ?"
                values.append(self.user_row["id"])
                self.repo.conn.execute(sql, tuple(values))
            else:
                salt, digest = pbkdf2_hash(password)
                self.repo.conn.execute(
                    """
                    INSERT INTO usuarios(nome, login, senha_salt, senha_hash, perfil, ativo, criado_em, areas_acesso)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (nome, login, salt, digest, profile, 1 if self.active_var.get() else 0, now_br(), area_csv(areas)),
                )
            self.repo.conn.commit()
        except sqlite3.IntegrityError:
            messagebox.showerror("Usuarios", "Ja existe um usuario com esse login.", parent=self)
            return
        self.saved = True
        self.destroy()


class UserDialog(tk.Toplevel):
    def __init__(self, master, repo):
        super().__init__(master)
        self.repo = repo
        self.configure(background=COLOR_PALETTES[master.config_data.get("color_palette", "aurora")]["bg"])
        self.title("Usuarios e permissoes")
        self.geometry("900x500")
        self.transient(master)
        self.grab_set()
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Usuarios e controle de acesso", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text="Defina quem pode alterar cada area do fluxo. Usuarios de consulta apenas visualizam.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 10))
        self.tree = ttk.Treeview(frame, columns=("nome", "login", "perfil", "areas", "ativo"), show="headings")
        for col, text, width in [
            ("nome", "Nome", 180),
            ("login", "Login", 130),
            ("perfil", "Perfil", 150),
            ("areas", "Areas liberadas", 300),
            ("ativo", "Ativo", 80),
        ]:
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.edit_user())
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        icon_button(buttons, "new", "Novo usuario", command=self.add_user, style="Accent.TButton").pack(side="left")
        icon_button(buttons, "edit", "Editar usuario", command=self.edit_user).pack(side="left", padx=8)
        icon_button(buttons, "status", "Ativar/Inativar", command=self.toggle_user).pack(side="left")
        icon_button(buttons, "cancel", "Fechar", command=self.destroy).pack(side="right")
        master.apply_non_ttk_colors(self)
        self.load()

    def load(self):
        self.tree.delete(*self.tree.get_children())
        rows = self.repo.conn.execute(
            "SELECT id, nome, login, perfil, ativo, areas_acesso FROM usuarios ORDER BY nome"
        ).fetchall()
        for row in rows:
            areas = ", ".join(area.title() for area in user_areas(row)) or "Somente consulta"
            self.tree.insert(
                "",
                "end",
                iid=row["id"],
                values=(row["nome"], row["login"], profile_label(row["perfil"]), areas, "Sim" if row["ativo"] else "Nao"),
            )

    def selected_id(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Usuarios", "Selecione um usuario.", parent=self)
            return None
        return int(selection[0])

    def selected_user(self):
        user_id = self.selected_id()
        if not user_id:
            return None
        return self.repo.conn.execute("SELECT * FROM usuarios WHERE id = ?", (user_id,)).fetchone()

    def add_user(self):
        dialog = UserEditorDialog(self.master, self.repo)
        self.wait_window(dialog)
        if dialog.saved:
            self.load()

    def edit_user(self):
        user = self.selected_user()
        if not user:
            return
        dialog = UserEditorDialog(self.master, self.repo, user)
        self.wait_window(dialog)
        if dialog.saved:
            self.load()

    def toggle_user(self):
        user_id = self.selected_id()
        if not user_id:
            return
        self.repo.conn.execute("UPDATE usuarios SET ativo = CASE ativo WHEN 1 THEN 0 ELSE 1 END WHERE id = ?", (user_id,))
        self.repo.conn.commit()
        self.load()


class ProcessDetailDialog(tk.Toplevel):
    def __init__(self, master, repo, user, process_id):
        super().__init__(master)
        self.repo = repo
        self.user = user
        self.process_id = process_id
        self.changed = False
        self.configure(background=COLOR_PALETTES[master.config_data.get("color_palette", "aurora")]["bg"])
        self.title("Detalhes da proposta")
        self.geometry("1120x720")
        self.minsize(980, 620)
        self.transient(master)
        self.create_widgets()
        self.load()
        master.apply_non_ttk_colors(self)

    def create_widgets(self):
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        header = ttk.Frame(frame)
        header.pack(fill="x")
        self.title_var = tk.StringVar()
        self.subtitle_var = tk.StringVar()
        ttk.Label(header, textvariable=self.title_var, style="Title.TLabel").pack(side="left")
        actions = ttk.Frame(header)
        actions.pack(side="right")
        icon_button(actions, "edit", "Editar", command=self.edit_process).pack(side="left", padx=(0, 8))
        icon_button(actions, "status", "Alterar status", command=self.change_status).pack(side="left", padx=(0, 8))
        icon_button(actions, "cancel", "Fechar", command=self.destroy).pack(side="left")
        ttk.Label(frame, textvariable=self.subtitle_var, style="Muted.TLabel").pack(anchor="w", pady=(2, 10))

        body = ttk.Frame(frame)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=2)
        body.columnconfigure(1, weight=3)
        body.rowconfigure(1, weight=1)
        self.status_frame = ttk.LabelFrame(body, text="Status por area", padding=10)
        self.status_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
        self.info_frame = ttk.LabelFrame(body, text="Resumo operacional", padding=10)
        self.info_frame.grid(row=0, column=1, sticky="nsew", pady=(0, 8))
        self.timeline_frame = ttk.LabelFrame(body, text="Linha do tempo", padding=10)
        self.timeline_frame.grid(row=1, column=0, columnspan=2, sticky="nsew")
        self.timeline_frame.rowconfigure(0, weight=1)
        self.timeline_frame.columnconfigure(0, weight=1)
        columns = ("area", "anterior", "novo", "data", "usuario", "observacao")
        self.timeline = ttk.Treeview(self.timeline_frame, columns=columns, show="headings")
        for col, label, width in (
            ("area", "Area", 130),
            ("anterior", "Anterior", 160),
            ("novo", "Novo", 160),
            ("data", "Quando", 140),
            ("usuario", "Usuario", 110),
            ("observacao", "Observacao", 380),
        ):
            self.timeline.heading(col, text=label)
            self.timeline.column(col, width=width, anchor="center")
        vsb = ttk.Scrollbar(self.timeline_frame, orient="vertical", command=self.timeline.yview)
        self.timeline.configure(yscrollcommand=vsb.set)
        self.timeline.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

    def clear_frame(self, frame):
        for child in frame.winfo_children():
            child.destroy()

    def load(self):
        self.process = self.repo.get_process(self.process_id)
        if not self.process:
            self.destroy()
            return
        p = self.process
        self.title_var.set(f"{p['proposta']} | {p['cliente']}")
        self.subtitle_var.set(f"Obra/Site: {p['obra_site'] or '-'} | Lote: {p['lote'] or '-'} | Prazo: {p['prazo_entrega'] or '-'} | Situacao: {status_label(p['situacao_fluxo'])}")
        self.load_status_cards()
        self.load_info()
        self.load_timeline()

    def load_status_cards(self):
        self.clear_frame(self.status_frame)
        for idx, (area, meta) in enumerate(AREAS.items()):
            status = self.process[meta["column"]] or ""
            row = ttk.Frame(self.status_frame)
            row.grid(row=idx, column=0, sticky="ew", pady=3)
            image = icon_image(self, status_icon_key(status))
            if image:
                label = ttk.Label(row, image=image)
                label.image = image
                label.pack(side="left", padx=(0, 8))
            ttk.Label(row, text=area.title(), width=18, style="Muted.TLabel").pack(side="left")
            status_norm = normalize_status(status)
            label_text = area_status_label(area, status_norm)
            display = f"{STATUS_ICONS.get(status_norm, ICONS['status'])} {label_text}" if label_text else "-"
            ttk.Label(row, text=display, font=(FONT_FAMILY, 9, "bold")).pack(side="left")

    def load_info(self):
        self.clear_frame(self.info_frame)
        p = self.process
        rows = [
            ("Tipo", status_label(p["tipo_processo"])),
            ("Peso", self.master.display_value(p["peso"])),
            ("Peso parcial", self.master.display_value(p["peso_parcial"])),
            ("Saldo pendente", self.master.display_value(p["saldo_pendente"])),
            ("Origem remanejamento", p["origem_remanejamento"] or "-"),
            ("Obs. remanejamento", p["observacao_remanejamento"] or "-"),
            ("Atualizado por", p["atualizado_por"] or "-"),
            ("Atualizado em", p["atualizado_em"] or "-"),
        ]
        for idx, (label, value) in enumerate(rows):
            ttk.Label(self.info_frame, text=label, style="Muted.TLabel").grid(row=idx, column=0, sticky="w", pady=2, padx=(0, 8))
            ttk.Label(self.info_frame, text=value or "-", wraplength=560).grid(row=idx, column=1, sticky="w", pady=2)
        partials = self.repo.list_process_partials(p)
        loads = self.repo.list_process_loads(self.process_id)
        row_idx = len(rows) + 1
        ttk.Label(self.info_frame, text=f"Parciais vinculadas: {max(0, len(partials) - 1)}", style="Muted.TLabel").grid(row=row_idx, column=0, columnspan=2, sticky="w", pady=(10, 2))
        row_idx += 1
        for partial in partials[:5]:
            ttk.Label(self.info_frame, text=f"{partial['proposta']} | {status_label(partial['situacao_fluxo'])} | {status_label(partial['status_expedicao'] or partial['status_galvanizacao'] or partial['status_producao'])}", wraplength=640).grid(row=row_idx, column=0, columnspan=2, sticky="w")
            row_idx += 1
        ttk.Label(self.info_frame, text=f"Cargas vinculadas: {len(loads)}", style="Muted.TLabel").grid(row=row_idx, column=0, columnspan=2, sticky="w", pady=(10, 2))
        row_idx += 1
        for load in loads[:4]:
            ttk.Label(self.info_frame, text=f"Carga {load['id']} | {load_status_label(load['status'])} | Prev.: {load['data_prevista_retorno'] or '-'} | Retorno: {load['data_retorno'] or '-'}", wraplength=640).grid(row=row_idx, column=0, columnspan=2, sticky="w")
            row_idx += 1

    def load_timeline(self):
        self.timeline.delete(*self.timeline.get_children())
        for row in self.repo.history(self.process_id):
            self.timeline.insert(
                "",
                "end",
                values=(
                    row["area"],
                    area_status_label(row["area"], row["status_anterior"]),
                    area_status_label(row["area"], row["status_novo"]),
                    row["data_hora"],
                    row["usuario"],
                    row["observacao"],
                ),
            )

    def edit_process(self):
        if not user_can_edit_process(self.user):
            messagebox.showwarning("Permissao", "Seu usuario nao pode editar dados do processo.", parent=self)
            return
        try:
            self.repo.acquire_process_lock(self.process_id, self.user)
            form = ProcessForm(self.master, self.repo, self.user, self.repo.get_process(self.process_id))
            self.wait_window(form)
            if form.saved:
                self.changed = True
                self.load()
        except AppError as exc:
            messagebox.showerror("Editar processo", str(exc), parent=self)
        finally:
            self.repo.release_process_lock(self.process_id, self.user)

    def change_status(self):
        allowed = visible_area_names(self.user)
        if not allowed:
            messagebox.showwarning("Permissao", "Seu usuario nao tem area liberada para alterar status.", parent=self)
            return
        area = simpledialog.askstring("Area", "Informe a area: " + ", ".join(allowed), parent=self)
        if not area:
            return
        area = area.strip().upper()
        if area not in allowed:
            messagebox.showerror("Area", "Area invalida.", parent=self)
            return
        try:
            self.repo.acquire_process_lock(self.process_id, self.user)
            dialog = StatusDialog(self.master, self.repo, self.user, self.repo.get_process(self.process_id), area)
            self.wait_window(dialog)
            if dialog.saved:
                self.changed = True
                self.load()
        except AppError as exc:
            messagebox.showerror("Alterar status", str(exc), parent=self)
        finally:
            self.repo.release_process_lock(self.process_id, self.user)


class ReportBuilderDialog(tk.Toplevel):
    def __init__(self, master, report=None):
        super().__init__(master)
        self.saved_report = None
        self.report = report or {}
        self.configure(background=COLOR_PALETTES[master.config_data.get("color_palette", "aurora")]["bg"])
        self.title("Criar relatorio" if not report else "Editar relatorio")
        self.geometry("760x620")
        self.transient(master)
        self.grab_set()
        self.create_widgets()
        master.apply_non_ttk_colors(self)

    def create_widgets(self):
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="Modelo de relatorio", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(frame, text="Escolha a base de dados e os campos que devem aparecer no relatorio.", style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 14))

        self.name_var = tk.StringVar(value=self.report.get("name", ""))
        self.source_var = tk.StringVar(value=dict((key, label) for key, label in REPORT_SOURCE_OPTIONS).get(self.report.get("source", "LISTAGEM"), "Listagem filtrada"))
        ttk.Label(frame, text="Nome").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Entry(frame, textvariable=self.name_var).grid(row=2, column=1, sticky="ew", pady=6)
        ttk.Label(frame, text="Base").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Combobox(frame, textvariable=self.source_var, values=[label for _key, label in REPORT_SOURCE_OPTIONS], state="readonly").grid(row=3, column=1, sticky="ew", pady=6)

        fields = ttk.LabelFrame(frame, text="Campos do relatorio", padding=10)
        fields.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        frame.rowconfigure(4, weight=1)
        fields.columnconfigure(0, weight=1)
        fields.columnconfigure(1, weight=1)
        self.field_vars = {}
        selected = set(self.report.get("columns") or ["proposta", "cliente", "obra_site", "prazo_entrega", "status_geral", "situacao_fluxo"])
        for idx, field in enumerate(REPORT_FIELD_OPTIONS):
            var = tk.BooleanVar(value=field in selected)
            self.field_vars[field] = var
            ttk.Checkbutton(fields, text=export_label(field), variable=var).grid(row=idx // 2, column=idx % 2, sticky="w", pady=2, padx=(0, 18))

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e", pady=(14, 0))
        icon_button(buttons, "save", "Salvar modelo", command=self.save, style="Accent.TButton").pack(side="left", padx=(0, 8))
        icon_button(buttons, "cancel", "Cancelar", command=self.destroy).pack(side="left")

    def save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Relatorios", "Informe o nome do relatorio.", parent=self)
            return
        selected = [field for field, var in self.field_vars.items() if var.get()]
        if not selected:
            messagebox.showerror("Relatorios", "Selecione pelo menos um campo.", parent=self)
            return
        source = next((key for key, label in REPORT_SOURCE_OPTIONS if label == self.source_var.get()), "LISTAGEM")
        self.saved_report = {"name": name, "source": source, "columns": selected}
        self.destroy()


class MainApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.ready = False
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1320x780")
        self.minsize(1100, 650)
        app_icon = BASE_DIR / "assets" / "logo_programa.ico"
        if app_icon.exists():
            try:
                self.iconbitmap(str(app_icon))
            except tk.TclError:
                pass
        self.config_data = load_config()
        save_config(self.config_data)
        self.conn = db_connect(self.config_data["db_path"])
        initialize_database(self.conn)
        backup_database(self.config_data, "abrir")
        self.repo = Repository(self.conn)
        self.user = None
        self.current_rows = []
        self.current_all_rows = []
        self.tab_filters = {}
        self.tab_pages = {}
        self.palette_var = tk.StringVar(value=self.config_data["color_palette"])
        self.load_icon_images()
        self.style = ttk.Style(self)
        self.setup_style()
        self.withdraw()
        login = LoginDialog(self, self.repo)
        self.wait_window(login)
        if not login.user:
            self.destroy()
            return
        self.user = login.user
        self.deiconify()
        self.create_menu()
        self.create_widgets()
        self.refresh_all()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.ready = True

    def load_icon_images(self):
        self.icon_images = {}
        icons_dir = BASE_DIR / "assets" / "icons"
        for key, filename in ICON_IMAGE_FILES.items():
            path = icons_dir / filename
            if not path.exists():
                continue
            try:
                image = tk.PhotoImage(file=str(path))
                factor = 3
                self.icon_images[key] = image.subsample(factor, factor)
            except tk.TclError:
                continue

    def setup_style(self):
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        palette = COLOR_PALETTES[self.config_data.get("color_palette", "aurora")]
        table_bg = "#f8fafc" if palette["surface"].lower() == "#ffffff" else palette["surface"]
        self.configure(background=palette["bg"])
        self.option_add("*Font", f"{FONT_FAMILY} 10")
        self.option_add("*Text.Font", f"{FONT_FAMILY} 10")
        self.option_add("*Text.background", palette["surface"])
        self.option_add("*Text.foreground", palette["text"])
        self.option_add("*Text.insertBackground", palette["accent"])
        self.option_add("*Text.selectBackground", palette["accent"])
        self.option_add("*Text.selectForeground", palette["accent_text"])
        self.option_add("*Entry.background", palette["surface"])
        self.option_add("*Entry.foreground", palette["text"])
        self.option_add("*Entry.insertBackground", palette["accent"])
        self.option_add("*Listbox.background", palette["surface"])
        self.option_add("*Listbox.foreground", palette["text"])
        self.option_add("*Listbox.selectBackground", palette["accent"])
        self.option_add("*Listbox.selectForeground", palette["accent_text"])
        self.option_add("*Menu.background", palette["surface"])
        self.option_add("*Menu.foreground", palette["text"])
        self.option_add("*Menu.activeBackground", palette["accent"])
        self.option_add("*Menu.activeForeground", palette["accent_text"])
        self.safe_style_configure(".", background=palette["bg"], foreground=palette["text"], font=(FONT_FAMILY, 10))
        self.safe_style_configure("TFrame", background=palette["bg"])
        self.safe_style_configure("Surface.TFrame", background=palette["surface"])
        self.safe_style_configure("Panel.TFrame", background=palette["surface"], relief="solid", borderwidth=1, bordercolor=palette["border"])
        self.safe_style_configure("Kpi.TFrame", background=palette["surface"], relief="solid", borderwidth=1, bordercolor=palette["border"])
        self.safe_style_configure("TLabel", background=palette["bg"], foreground=palette["text"])
        self.safe_style_configure("Title.TLabel", background=palette["bg"], foreground=palette["text"], font=(FONT_FAMILY, 15, "bold"))
        self.safe_style_configure("Muted.TLabel", background=palette["bg"], foreground=palette["muted"])
        self.safe_style_configure("HeaderInfo.TLabel", background=palette["bg"], foreground=palette["muted"], font=(FONT_FAMILY, 7))
        self.safe_style_configure("MiniMuted.TLabel", background=palette["bg"], foreground=palette["muted"], font=(FONT_FAMILY, 7))
        self.safe_style_configure("Filter.TFrame", background=palette["surface"], relief="solid", borderwidth=1, bordercolor=palette["border"])
        self.safe_style_configure("Filter.TLabel", background=palette["surface"], foreground=palette["muted"], font=(FONT_FAMILY, 8))
        self.safe_style_configure("FilterTitle.TLabel", background=palette["surface"], foreground=palette["accent"], font=(FONT_FAMILY, 8, "bold"))
        self.safe_style_configure("FilterInfo.TLabel", background=palette["bg"], foreground=palette["muted"], font=(FONT_FAMILY, 7))
        self.safe_style_configure("MiniPager.TFrame", background=palette["surface"])
        self.safe_style_configure("FilterActions.TFrame", background=palette["surface"])
        self.safe_style_configure("PanelMuted.TLabel", background=palette["surface"], foreground=palette["muted"], font=(FONT_FAMILY, 9))
        self.safe_style_configure("KpiLabel.TLabel", background=palette["surface"], foreground=palette["muted"], font=(FONT_FAMILY, 8, "bold"))
        self.safe_style_configure("KpiValue.TLabel", background=palette["surface"], foreground=palette["accent"], font=(FONT_FAMILY, 16, "bold"))
        self.safe_style_configure(
            "TLabelframe",
            background=palette["bg"],
            bordercolor=palette["border"],
            relief="solid",
        )
        self.safe_style_configure(
            "TLabelframe.Label",
            background=palette["bg"],
            foreground=palette["accent"],
            font=(FONT_FAMILY, 10, "bold"),
        )
        self.safe_style_configure(
            "TButton",
            background=palette["surface_alt"],
            foreground=palette["text"],
            bordercolor=palette["border"],
            focusthickness=0,
            padding=(3, 0),
            relief="flat",
            font=(FONT_FAMILY, 9),
        )
        self.safe_style_map(
            "TButton",
            background=[("active", palette["border"]), ("pressed", palette["border"])],
            foreground=[("disabled", palette["muted"])],
        )
        self.safe_style_configure(
            "Accent.TButton",
            background=palette["accent"],
            foreground=palette["accent_text"],
            bordercolor=palette["accent"],
            padding=(4, 1),
            relief="flat",
            font=(FONT_FAMILY, 9, "bold"),
        )
        self.safe_style_map(
            "Accent.TButton",
            background=[("active", palette["accent_hover"]), ("pressed", palette["accent_hover"])],
            foreground=[("active", palette["accent_text"]), ("pressed", palette["accent_text"])],
        )
        self.safe_style_configure(
            "Small.TButton",
            background=palette["surface_alt"],
            foreground=palette["text"],
            bordercolor=palette["border"],
            padding=(3, 0),
            font=(FONT_FAMILY, 7),
        )
        self.safe_style_configure(
            "SmallAccent.TButton",
            background=palette["accent"],
            foreground=palette["accent_text"],
            bordercolor=palette["accent"],
            padding=(4, 0),
            font=(FONT_FAMILY, 7, "bold"),
        )
        self.safe_style_configure("TEntry", fieldbackground=palette["surface"], foreground=palette["text"], bordercolor=palette["border"], padding=(5, 2))
        self.safe_style_configure("TCombobox", fieldbackground=palette["surface"], foreground=palette["text"], bordercolor=palette["border"], padding=(4, 2))
        self.safe_style_map(
            "TEntry",
            fieldbackground=[("disabled", palette["surface_alt"]), ("readonly", palette["surface"])],
            foreground=[("disabled", palette["muted"]), ("readonly", palette["text"])],
        )
        self.safe_style_map(
            "TCombobox",
            fieldbackground=[("readonly", palette["surface"]), ("disabled", palette["surface_alt"])],
            foreground=[("readonly", palette["text"]), ("disabled", palette["muted"])],
            selectbackground=[("readonly", palette["surface"]), ("disabled", palette["surface_alt"])],
            selectforeground=[("readonly", palette["text"]), ("disabled", palette["muted"])],
            arrowcolor=[("disabled", palette["muted"]), ("readonly", palette["text"])],
        )
        self.safe_style_configure("TNotebook", background=palette["bg"], borderwidth=0)
        self.safe_style_configure("Hidden.TNotebook", background=palette["bg"], borderwidth=0)
        try:
            self.style.layout("Hidden.TNotebook.Tab", [])
        except tk.TclError:
            pass
        self.safe_style_configure(
            "TNotebook.Tab",
            background=palette["surface_alt"],
            foreground=palette["muted"],
            padding=(14, 8),
            font=(FONT_FAMILY, 10, "bold"),
        )
        self.safe_style_map(
            "TNotebook.Tab",
            background=[("selected", palette["accent"]), ("active", palette["border"])],
            foreground=[("selected", palette["accent_text"]), ("active", palette["text"])],
        )
        self.safe_style_configure(
            "Treeview",
            rowheight=26,
            background=table_bg,
            fieldbackground=table_bg,
            foreground=palette["text"],
            bordercolor=palette["border"],
            borderwidth=1,
            relief="solid",
            font=(FONT_FAMILY, 9, "bold"),
        )
        self.safe_style_configure(
            "Treeview.Heading",
            background="#1e293b",
            foreground="#ffffff",
            relief="flat",
            borderwidth=1,
            font=(FONT_FAMILY, 9, "bold"),
        )
        self.safe_style_map(
            "Treeview",
            background=[("selected", "#bae6fd")],
            foreground=[("selected", "#0f172a")],
        )
        self.safe_style_configure(
            "Nav.TButton",
            background=palette["surface_alt"],
            foreground=palette["text"],
            bordercolor=palette["border"],
            padding=(6, 4),
            relief="flat",
            font=(FONT_FAMILY, 9, "bold"),
        )
        self.safe_style_configure(
            "NavActive.TButton",
            background=palette["accent"],
            foreground=palette["accent_text"],
            bordercolor=palette["accent"],
            padding=(6, 4),
            relief="flat",
            font=(FONT_FAMILY, 9, "bold"),
        )

    def safe_style_configure(self, style_name, **options):
        try:
            self.style.configure(style_name, **options)
        except tk.TclError:
            fallback = {key: value for key, value in options.items() if key not in {"bordercolor", "focusthickness"}}
            try:
                self.style.configure(style_name, **fallback)
            except tk.TclError:
                pass

    def safe_style_map(self, style_name, **options):
        try:
            self.style.map(style_name, **options)
        except tk.TclError:
            pass

    def create_menu(self):
        palette = COLOR_PALETTES[self.config_data.get("color_palette", "aurora")]
        menu_options = {
            "background": palette["surface"],
            "foreground": palette["text"],
            "activebackground": palette["accent"],
            "activeforeground": palette["accent_text"],
            "relief": "flat",
        }
        menu = tk.Menu(self, **menu_options)
        file_menu = tk.Menu(menu, tearoff=False, **menu_options)
        file_menu.add_command(label="Sair", command=self.on_close)
        menu.add_cascade(label="Arquivo", menu=file_menu)
        self.config(menu=menu)

    def apply_palette(self, palette_name):
        if palette_name not in COLOR_PALETTES:
            palette_name = "aurora"
        self.config_data["color_palette"] = palette_name
        self.palette_var.set(palette_name)
        save_config(self.config_data)
        self.setup_style()
        self.create_menu()
        self.apply_non_ttk_colors()
        self.refresh_navigation_theme()
        self.refresh_tree_tags()
        if getattr(self, "ready", False):
            self.refresh_dashboard()

    def refresh_navigation_theme(self):
        palette = COLOR_PALETTES[self.config_data.get("color_palette", "aurora")]
        for frame_name in ("nav_area_frame", "nav_system_frame"):
            frame = getattr(self, frame_name, None)
            if frame:
                frame.configure(background=palette["bg"], bd=0, highlightthickness=0)
        for button in getattr(self, "nav_buttons", {}).values():
            button.palette = palette
            button.configure(background=button.parent_bg(button.master), highlightthickness=0, bd=0, relief="flat")
            button.draw()

    def apply_non_ttk_colors(self, widget=None):
        palette = COLOR_PALETTES[self.config_data.get("color_palette", "aurora")]
        widget = widget or self
        for child in widget.winfo_children():
            if isinstance(child, tk.Text):
                child.configure(
                    background=palette["surface"],
                    foreground=palette["text"],
                    insertbackground=palette["accent"],
                    selectbackground=palette["accent"],
                    selectforeground=palette["accent_text"],
                    relief="flat",
                    highlightthickness=1,
                    highlightbackground=palette["border"],
                    highlightcolor=palette["accent"],
                )
            elif child.winfo_class() == "Entry":
                child.configure(
                    background=palette["surface"],
                    foreground=palette["text"],
                    insertbackground=palette["accent"],
                    selectbackground=palette["accent"],
                    selectforeground=palette["accent_text"],
                    relief="flat",
                    highlightthickness=1,
                    highlightbackground=palette["border"],
                    highlightcolor=palette["accent"],
                )
            elif isinstance(child, tk.Listbox):
                child.configure(
                    background=palette["surface"],
                    foreground=palette["text"],
                    selectbackground=palette["accent"],
                    selectforeground=palette["accent_text"],
                    relief="flat",
                    highlightthickness=1,
                    highlightbackground=palette["border"],
                    highlightcolor=palette["accent"],
                )
            elif isinstance(child, RoundedButton):
                child.palette = palette
                child.configure(
                    background=child.parent_bg(child.master),
                    highlightthickness=0,
                    bd=0,
                    relief="flat",
                )
                child.draw()
            elif isinstance(child, tk.Canvas):
                child.configure(
                    background=palette["surface"],
                    highlightthickness=1,
                    highlightbackground=palette["border"],
                )
            self.apply_non_ttk_colors(child)

    def refresh_tree_tags(self):
        palette = COLOR_PALETTES[self.config_data.get("color_palette", "aurora")]
        trees = []
        if hasattr(self, "tree"):
            trees.append(self.tree)
        if hasattr(self, "area_trees"):
            trees.extend(self.area_trees.values())
        for attr in ("history_tree", "audit_tree", "report_tree"):
            if hasattr(self, attr):
                tree = getattr(self, attr)
                if tree:
                    trees.append(tree)
        for tree in trees:
            tree.tag_configure("overdue", foreground=palette["danger"])
            tree.tag_configure("soon", foreground=palette["warning"])
            tree.tag_configure("odd", background="#ffffff", foreground="#0f172a", font=(FONT_FAMILY, 9, "bold"))
            tree.tag_configure("even", background="#f8fafc", foreground="#0f172a", font=(FONT_FAMILY, 9, "bold"))
            for status, (background, foreground) in STATUS_TAG_COLORS.items():
                tree.tag_configure(f"status_{status}", background=background, foreground=foreground, font=(FONT_FAMILY, 9, "bold"))
            tree.tag_configure("finished", background="#e5e7eb", foreground="#0f172a", font=(FONT_FAMILY, 9, "bold"))

    def create_widgets(self):
        header = ttk.Frame(self, padding=(10, 0))
        header.pack(fill="x")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text=APP_NAME, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.session_info_var = tk.StringVar(
            value=f"Usuario: {self.user['nome']} | Perfil: {profile_label(self.user['perfil'])} | Banco: {self.config_data['db_path']}"
        )
        ttk.Label(
            header,
            textvariable=self.session_info_var,
            style="HeaderInfo.TLabel",
            anchor="e",
        ).grid(row=0, column=1, sticky="e", padx=(20, 88))
        main = ttk.Frame(self, padding=(6, 0, 6, 6))
        main.pack(fill="both", expand=True)
        self.nav_buttons = {}
        self.sidebar = ttk.Frame(main, width=176, padding=(0, 0, 6, 0))
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.content = ttk.Frame(main)
        self.content.pack(side="left", fill="both", expand=True)
        self.create_sidebar()

        self.filters_frame = ttk.Frame(self.content, style="Filter.TFrame", padding=(10, 6))
        self.filters_frame.pack(fill="x", padx=6, pady=(0, 6))
        filters = self.filters_frame
        self.filter_text = tk.StringVar()
        self.filter_cliente = tk.StringVar()
        self.filter_status = tk.StringVar()
        self.filter_area = tk.StringVar(value="TODAS")
        self.filter_prazo = tk.StringVar(value="TODOS")
        self.page_size_var = tk.StringVar(value="50")
        self.page_info_var = tk.StringVar(value="")
        for col in (2, 4, 6, 8):
            filters.columnconfigure(col, weight=1)
        ttk.Label(filters, text="Filtros", style="FilterTitle.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=(0, 4))
        ttk.Label(filters, text="Busca geral", style="Filter.TLabel").grid(row=0, column=1, sticky="w", padx=(0, 4), pady=(0, 4))
        ttk.Entry(filters, textvariable=self.filter_text, width=26).grid(row=0, column=2, sticky="ew", padx=(0, 12), pady=(0, 4))
        ttk.Label(filters, text="Cliente", style="Filter.TLabel").grid(row=0, column=3, sticky="w", padx=(0, 4), pady=(0, 4))
        ttk.Entry(filters, textvariable=self.filter_cliente, width=20).grid(row=0, column=4, sticky="ew", padx=(0, 12), pady=(0, 4))
        ttk.Label(filters, text="Status", style="Filter.TLabel").grid(row=0, column=5, sticky="w", padx=(0, 4), pady=(0, 4))
        self.status_filter = ttk.Combobox(filters, textvariable=self.filter_status, width=24, state="readonly")
        self.status_filter.grid(row=0, column=6, sticky="ew", padx=(0, 12), pady=(0, 4))
        self.area_filter_label = ttk.Label(filters, text="Area", style="Filter.TLabel")
        self.area_filter_label.grid(row=0, column=7, sticky="w", padx=(0, 4), pady=(0, 4))
        self.area_filter_combo = ttk.Combobox(filters, textvariable=self.filter_area, values=["TODAS"] + list(AREAS.keys()), width=18, state="readonly")
        self.area_filter_combo.grid(
            row=0, column=8, sticky="ew", padx=(0, 12), pady=(0, 4)
        )
        ttk.Label(filters, text="Prazo", style="Filter.TLabel").grid(row=0, column=9, sticky="w", padx=(0, 4), pady=(0, 4))
        ttk.Combobox(
            filters,
            textvariable=self.filter_prazo,
            values=["TODOS", "VENCIDOS", "PROXIMOS_7_DIAS"],
            width=13,
            state="readonly",
        ).grid(row=0, column=10, sticky="ew", padx=(0, 8), pady=(0, 4))
        self.filter_actions_frame = ttk.Frame(filters, style="FilterActions.TFrame")
        self.filter_actions_frame.grid(row=0, column=11, sticky="e", pady=(0, 4))
        icon_button(self.filter_actions_frame, "search", "Aplicar", command=self.apply_filters_current_tab, style="SmallAccent.TButton").pack(side="left", padx=(0, 4))
        icon_button(self.filter_actions_frame, "clear", "Limpar", command=self.clear_filters, style="Small.TButton").pack(side="left")
        self.pagination_frame = ttk.Frame(filters, style="MiniPager.TFrame")
        self.pagination_frame.grid(row=1, column=0, columnspan=5, sticky="w", pady=(3, 0))
        ttk.Label(self.pagination_frame, text="Reg.", style="Filter.TLabel").pack(side="left", padx=(0, 3))
        ttk.Combobox(
            self.pagination_frame,
            textvariable=self.page_size_var,
            values=PAGE_SIZE_OPTIONS,
            width=5,
            state="readonly",
        ).pack(side="left", padx=(0, 4))
        icon_button(self.pagination_frame, "previous", "", command=self.previous_page, style="Small.TButton", width=2).pack(side="left", padx=(0, 2))
        icon_button(self.pagination_frame, "next", "", command=self.next_page, style="Small.TButton", width=2).pack(side="left", padx=(0, 5))
        ttk.Label(self.pagination_frame, textvariable=self.page_info_var, style="MiniMuted.TLabel").pack(side="left")
        self.context_actions_frame = ttk.Frame(filters, style="FilterActions.TFrame")
        self.context_actions_frame.grid(row=1, column=5, columnspan=7, sticky="e", pady=(3, 0))
        self.new_button = icon_button(self.context_actions_frame, "new", "Novo processo", command=self.new_process, style="Accent.TButton")
        self.new_button.pack(side="right", padx=(5, 0))
        if not user_can_edit_process(self.user):
            self.new_button.state(["disabled"])
        self.new_button.pack_forget()
        self.load_button = icon_button(self.context_actions_frame, "load", "Cargas", command=self.mount_galvanization_load, style="Small.TButton")
        self.load_button.pack(side="right", padx=(5, 0))
        self.load_button.pack_forget()
        self.batch_status_button = icon_button(self.context_actions_frame, "batch", "Status em lote", command=self.open_batch_status_selection, style="SmallAccent.TButton")
        self.batch_status_button.pack(side="right", padx=(5, 0))
        self.batch_status_button.pack_forget()
        self.early_delivery_button = icon_button(self.context_actions_frame, "early", "Entrega rem", command=self.open_early_remanagement_delivery, style="SmallAccent.TButton")
        self.early_delivery_button.pack(side="right", padx=(5, 0))
        self.early_delivery_button.pack_forget()
        self.details_button = icon_button(self.context_actions_frame, "search", "Detalhes", command=self.show_process_details, style="Small.TButton")
        self.details_button.pack(side="right", padx=(5, 0))
        self.details_button.pack_forget()
        self.kpi_vars = {}
        self.chart_canvases = {}
        self.notebook = ttk.Notebook(self.content, style="Hidden.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self.footer_frame = ttk.Frame(self.content, padding=(6, 0, 6, 0))
        self.footer_frame.pack(fill="x", pady=(0, 4))
        self.export_frame = ttk.Frame(self.footer_frame)
        self.export_frame.pack(side="right")
        icon_button(self.export_frame, "pdf", "PDF", command=lambda: self.export_current("pdf"), style="Small.TButton").pack(side="left", padx=(0, 5))
        icon_button(self.export_frame, "excel", "Excel", command=lambda: self.export_current("xlsx"), style="Small.TButton").pack(side="left")
        self.tree = self.create_process_tree(self.notebook, with_dashboard=True)
        self.add_nav_tab(self.tree.master, "Painel geral", "PAINEL GERAL")
        self.area_trees = {}
        for area in visible_area_names(self.user):
            tree = self.create_process_tree(self.notebook, area=area)
            self.area_trees[area] = tree
            self.add_nav_tab(tree.master, area.title(), area)
        self.partial_tree = self.create_process_tree(self.notebook, area="PARCIAIS")
        self.add_nav_tab(self.partial_tree.master, "Parciais", "PARCIAIS")
        self.history_tree = self.create_history_tree(self.notebook)
        self.add_nav_tab(self.history_tree.master, "Historico", "HISTORICO")
        self.audit_tree = None
        if user_can_admin(self.user):
            self.audit_tree = self.create_audit_tree(self.notebook)
            self.add_nav_tab(self.audit_tree.master, "Auditoria", "AUDITORIA")
        self.report_frame = self.create_report_frame(self.notebook)
        self.add_nav_tab(self.report_frame, "Relatorios", "RELATORIOS")
        self.settings_frame = self.create_settings_frame(self.notebook)
        self.add_nav_tab(self.settings_frame, "Configuracoes", "CONFIGURACOES")
        self.status_filter["values"] = [""] + self.repo.list_status()
        self.initialize_tab_filters()
        self.update_status_filter_options("PAINEL GERAL")
        self.update_nav_buttons("PAINEL GERAL")
        self.update_context_actions("PAINEL GERAL")
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)
        self.bind("<Control-n>", lambda _e: self.new_process())
        self.bind("<F5>", lambda _e: self.apply_filters_current_tab())
        self.bind("<Return>", lambda _e: self.apply_filters_current_tab())
        self.apply_non_ttk_colors()
        self.refresh_navigation_theme()
        self.refresh_tree_tags()

    def create_sidebar(self):
        palette = COLOR_PALETTES[self.config_data.get("color_palette", "aurora")]
        logo = tk.Frame(self.sidebar, background=palette["surface"], height=76, highlightthickness=1, highlightbackground=palette["border"])
        logo.pack(fill="x", pady=(0, 6))
        logo.pack_propagate(False)
        logo_path = BASE_DIR / "assets" / "logo.png"
        if not logo_path.exists():
            logo_path = BASE_DIR / "logo.png"
        if logo_path.exists():
            try:
                image = tk.PhotoImage(file=str(logo_path))
                factor = max(1, int(max(image.width() / 134, image.height() / 58)))
                self.logo_image = image.subsample(factor, factor)
                tk.Label(logo, image=self.logo_image, background=palette["surface"]).pack(expand=True)
            except tk.TclError:
                self.create_text_logo(logo, palette)
        else:
            self.create_text_logo(logo, palette)
        ttk.Label(self.sidebar, text="Areas", style="Muted.TLabel").pack(anchor="w", pady=(0, 2))
        self.nav_area_frame = tk.Frame(self.sidebar, background=palette["bg"], bd=0, highlightthickness=0)
        self.nav_area_frame.pack(fill="x", pady=(0, 7))
        ttk.Label(self.sidebar, text="Sistema", style="Muted.TLabel").pack(anchor="w", pady=(0, 2))
        self.nav_system_frame = tk.Frame(self.sidebar, background=palette["bg"], bd=0, highlightthickness=0)
        self.nav_system_frame.pack(fill="x")

    def create_text_logo(self, parent, palette):
        tk.Label(
            parent,
            text=self.config_data.get("company", "Industel").upper(),
            background=palette["surface"],
            foreground=palette["accent"],
            font=(FONT_FAMILY, 15, "bold"),
        ).pack(expand=True)
        tk.Label(
            parent,
            text="Espaco para logo",
            background=palette["surface"],
            foreground=palette["muted"],
            font=(FONT_FAMILY, 9),
        ).pack(pady=(0, 12))

    def add_nav_tab(self, frame, text, key):
        self.notebook.add(frame, text=text)
        parent = self.nav_area_frame if key == "PAINEL GERAL" or key in AREAS or key == "PARCIAIS" else self.nav_system_frame
        button = icon_button(parent, self.nav_icon_key(key), text, style="Nav.TButton", command=lambda tab_key=key: self.select_nav_tab(tab_key))
        button.pack(fill="x", padx=(0, 0), pady=(0, 3))
        self.nav_buttons[key] = button

    def nav_icon_key(self, key):
        if key == "PAINEL GERAL":
            return "dashboard"
        if key in AREAS:
            return AREA_ICON_KEYS.get(key, "status")
        system_icons = {
            "PARCIAIS": "partial",
            "HISTORICO": "history",
            "AUDITORIA": "audit",
            "RELATORIOS": "reports",
            "CONFIGURACOES": "settings",
        }
        return system_icons.get(key, "status")

    def select_nav_tab(self, key):
        for tab_id in self.notebook.tabs():
            if self.tab_key_for_id(tab_id) == key:
                self.notebook.select(tab_id)
                self.on_tab_changed()
                return

    def tab_key_for_id(self, tab_id):
        tab_text = self.notebook.tab(tab_id, "text").upper()
        if tab_text == "PAINEL GERAL":
            return "PAINEL GERAL"
        if tab_text in ("CONFIGURACOES", "CONFIGURAÇÕES"):
            return "CONFIGURACOES"
        return next((area for area in AREAS if area == tab_text), tab_text)

    def update_nav_buttons(self, active_key=None):
        active_key = active_key or self.active_tab_key()
        for key, button in self.nav_buttons.items():
            button.configure(style="NavActive.TButton" if key == active_key else "Nav.TButton")

    def create_process_tree(self, parent, with_dashboard=False, area=None):
        frame = ttk.Frame(parent)
        tree_row = 1 if with_dashboard else 0
        if with_dashboard:
            self.create_dashboard_panel(frame)
            frame.rowconfigure(0, weight=1)
            frame.columnconfigure(0, weight=1)
        columns = self.process_columns_for_area(area)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="tree headings", selectmode="extended")
        tree.process_columns = columns
        tree.area_key = area or "PAINEL GERAL"
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.heading("#0", text="", anchor="center")
        tree.column("#0", width=38, minwidth=38, stretch=False, anchor="center")
        for key, label, width in columns:
            anchor = "center" if key.startswith("status_") else "center"
            tree.heading(key, text=label, anchor="center")
            tree.column(key, width=width, minwidth=60, stretch=True, anchor=anchor)
        if not with_dashboard:
            tree.grid(row=tree_row, column=0, sticky="nsew")
            vsb.grid(row=tree_row, column=1, sticky="ns")
            hsb.grid(row=tree_row + 1, column=0, sticky="ew")
        frame.rowconfigure(tree_row, weight=1)
        frame.columnconfigure(0, weight=1)
        tree.bind("<Double-1>", lambda _e: self.show_process_details())
        tree.bind("<ButtonRelease-1>", self.open_status_from_row_icon, add="+")
        tree.bind("<Motion>", self.update_row_icon_cursor, add="+")
        tree.bind("<Button-3>", self.show_process_menu)
        tree.bind("<Button-2>", self.show_process_menu)
        tree.bind("<Configure>", lambda _e, target=tree: self.resize_tree_columns(target))
        palette = COLOR_PALETTES[self.config_data.get("color_palette", "aurora")]
        tree.tag_configure("overdue", foreground=palette["danger"])
        tree.tag_configure("soon", foreground=palette["warning"])
        tree.tag_configure("odd", background="#ffffff", foreground="#0f172a", font=(FONT_FAMILY, 9, "bold"))
        tree.tag_configure("even", background="#f8fafc", foreground="#0f172a", font=(FONT_FAMILY, 9, "bold"))
        for status, (background, foreground) in STATUS_TAG_COLORS.items():
            tree.tag_configure(f"status_{status}", background=background, foreground=foreground, font=(FONT_FAMILY, 9, "bold"))
        tree.tag_configure("finished", background="#e5e7eb", foreground="#0f172a", font=(FONT_FAMILY, 9, "bold"))
        self.after_idle(lambda target=tree: self.resize_tree_columns(target))
        return tree

    def resize_tree_columns(self, tree):
        columns = getattr(tree, "process_columns", PROCESS_COLUMNS)
        if not columns:
            return
        total_weight = sum(width for _key, _label, width in columns) or 1
        available = max(tree.winfo_width() - 24, total_weight)
        for key, _label, width in columns:
            min_width = 90 if key.startswith("status_") else 55
            new_width = max(min_width, int(available * width / total_weight))
            tree.column(key, width=new_width, stretch=True)

    def process_columns_for_area(self, area=None):
        if area == "PARCIAIS":
            return [
                ("tipo_processo", "Tipo", 80),
                ("proposta", "Proposta", 120),
                ("cliente", "Cliente", 180),
                ("obra_site", "Obra/Site", 170),
                ("lote", "Lote", 90),
                ("peso", "Peso", 80),
                ("peso_parcial", "Peso Parcial", 105),
                ("saldo_pendente", "Saldo", 90),
                ("prazo_entrega", "Prazo", 95),
                ("status_producao", "Producao", 165),
                ("status_galvanizacao", "Galvanizacao", 170),
                ("status_expedicao", "Expedicao", 165),
                ("situacao_fluxo", "Situacao", 180),
                ("origem_remanejamento", "Origem", 130),
            ]
        if area not in AREAS:
            return PROCESS_COLUMNS
        status_column = AREAS[area]["column"]
        status_label = AREA_STATUS_LABELS.get(area, "Status")
        base_columns = BASE_AREA_PROCESS_COLUMNS
        if area == "CONTROLE GERAL":
            return base_columns + [("status_localizacao", "Status", 190), ("localizacao_atual", "Localizacao", 130)]
        if area == "GALVANIZACAO":
            base_columns = [
                column for column in BASE_AREA_PROCESS_COLUMNS if column[0] not in ("data_entrada", "prazo_entrega")
            ]
            base_columns = base_columns + [
                ("data_envio_galv", "Envio Galv.", 115),
                ("data_prevista_retorno_galv", "Prev. Retorno", 125),
                ("data_retorno_galv", "Retorno Galv.", 115),
            ]
        if area == "EXPEDICAO":
            base_columns = [
                column for column in BASE_AREA_PROCESS_COLUMNS if column[0] != "data_entrada"
            ]
            base_columns = base_columns + [
                ("almoxarifado_info", "Almox.", 110),
            ]
        return base_columns + [(status_column, status_label, 180), ("situacao_fluxo", "Situacao", 170)]

    def create_dashboard_panel(self, parent):
        panel = ttk.Frame(parent, padding=(4, 2, 4, 10))
        panel.grid(row=0, column=0, columnspan=2, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)

        heading = ttk.Frame(panel)
        heading.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        heading.columnconfigure(0, weight=1)
        ttk.Label(heading, text="Painel geral", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.dashboard_focus_var = tk.StringVar(value="")
        ttk.Label(heading, textvariable=self.dashboard_focus_var, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 0))

        kpis = ttk.Frame(panel)
        kpis.grid(row=1, column=0, sticky="ew")
        self.dashboard_metric_frames = {}
        dashboard_labels = [
            "Ativas",
            "Vencidos",
            "Prox. 7 dias",
            "Producao",
            "Galvanizacao",
            "Galv. parcial",
            "Expedicao",
            "Entregues parc.",
            "Pend. remanej.",
            "Entregues",
        ]
        for idx, label in enumerate(dashboard_labels):
            row_idx = idx // 5
            col_idx = idx % 5
            box = ttk.Frame(kpis, padding=(14, 12), style="Kpi.TFrame")
            box.grid(row=row_idx, column=col_idx, sticky="ew", padx=5, pady=5)
            title = ttk.Label(box, text=label, style="KpiLabel.TLabel")
            title.pack(anchor="center")
            var = tk.StringVar(value="0")
            self.kpi_vars[label] = var
            value_label = ttk.Label(box, textvariable=var, style="KpiValue.TLabel")
            value_label.pack(anchor="center")
            self.bind_dashboard_widget(box, "metric", label)
            self.bind_dashboard_widget(title, "metric", label)
            self.bind_dashboard_widget(value_label, "metric", label)
            self.dashboard_metric_frames[label] = box
            kpis.columnconfigure(col_idx, weight=1)

        charts = ttk.Frame(panel)
        charts.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        charts.columnconfigure(0, weight=1)
        charts.columnconfigure(1, weight=1)
        charts.rowconfigure(0, weight=1)
        charts.rowconfigure(1, weight=1)
        self.chart_regions = {}
        for idx, (key, title) in enumerate(
            [
                ("areas", "Fila operacional por area"),
                ("status", "Distribuicao por status"),
                ("prazos", "Controle de prazos"),
            ]
        ):
            chart_box = ttk.Frame(charts, padding=12, style="Kpi.TFrame")
            columnspan = 2 if key == "prazos" else 1
            chart_box.grid(row=idx // 2, column=idx % 2, columnspan=columnspan, sticky="nsew", padx=5, pady=5)
            ttk.Label(chart_box, text=title, style="KpiLabel.TLabel").pack(anchor="w")
            canvas = tk.Canvas(chart_box, height=230, bd=0, highlightthickness=0, cursor="hand2")
            canvas.pack(fill="both", expand=True, pady=(8, 0))
            canvas.bind("<Button-1>", lambda event, chart_key=key: self.on_dashboard_chart_click(event, chart_key))
            self.chart_canvases[key] = canvas

    def bind_dashboard_widget(self, widget, source, key):
        try:
            widget.configure(cursor="hand2")
        except tk.TclError:
            pass
        widget.bind("<Button-1>", lambda _event, source=source, key=key: self.show_dashboard_details(source, key))

    def create_history_tree(self, parent):
        frame = ttk.Frame(parent, padding=12)
        ttk.Label(frame, text="Historico de movimentacoes", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.history_summary_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.history_summary_var, style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 10))
        columns = ("proposta", "area", "status_anterior", "status_novo", "data_hora", "usuario", "computador", "observacao")
        labels = ("Proposta", "Area", "De", "Para", "Quando", "Usuario", "Computador", "Observacao")
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        for col, label in zip(columns, labels):
            tree.heading(col, text=label)
            width = 120
            if col == "observacao":
                width = 360
            elif col in ("status_anterior", "status_novo"):
                width = 170
            tree.column(col, width=width, anchor="center" if col != "observacao" else "w")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=2, column=0, sticky="nsew")
        vsb.grid(row=2, column=1, sticky="ns")
        hsb.grid(row=3, column=0, sticky="ew")
        frame.rowconfigure(2, weight=1)
        frame.columnconfigure(0, weight=1)
        return tree

    def create_audit_tree(self, parent):
        frame = ttk.Frame(parent, padding=12)
        ttk.Label(frame, text="Auditoria de alteracoes", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.audit_summary_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.audit_summary_var, style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 10))
        columns = ("acao", "entidade", "entidade_id", "campo", "valor_anterior", "valor_novo", "data_hora", "usuario")
        labels = ("Acao", "Modulo", "Registro", "Campo", "Antes", "Depois", "Quando", "Usuario")
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        for col, label in zip(columns, labels):
            tree.heading(col, text=label)
            tree.column(col, width=130 if col not in ("valor_anterior", "valor_novo") else 260)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=2, column=0, sticky="nsew")
        vsb.grid(row=2, column=1, sticky="ns")
        hsb.grid(row=3, column=0, sticky="ew")
        frame.rowconfigure(2, weight=1)
        frame.columnconfigure(0, weight=1)
        return tree

    def create_report_frame(self, parent):
        frame = ttk.Frame(parent, padding=12)
        top = ttk.Frame(frame)
        top.pack(fill="x")
        self.report_name = tk.StringVar(value="")
        ttk.Label(top, text="Relatorios criados", style="Title.TLabel").pack(side="left")
        icon_button(top, "new", "Criar relatorio", command=self.open_report_builder, style="Accent.TButton").pack(side="left", padx=(12, 8))
        icon_button(top, "refresh", "Atualizar", command=self.refresh_report_list, style="Small.TButton").pack(side="left")
        icon_button(top, "excel", "Exportar Excel", command=lambda: self.export_report("xlsx")).pack(side="right")
        icon_button(top, "pdf", "Exportar PDF", command=lambda: self.export_report("pdf")).pack(side="right", padx=8)
        self.report_summary_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.report_summary_var, style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
        list_box = ttk.LabelFrame(frame, text="Modelos salvos", padding=8)
        list_box.pack(fill="both", expand=True, pady=(8, 0))
        list_box.rowconfigure(0, weight=1)
        list_box.columnconfigure(0, weight=1)
        self.saved_reports_tree = ttk.Treeview(list_box, columns=("name", "source", "fields", "preview"), show="headings", selectmode="browse")
        for col, label, width in (("name", "Nome", 260), ("source", "Base", 220), ("fields", "Campos", 90), ("preview", "Previa", 110)):
            self.saved_reports_tree.heading(col, text=label)
            self.saved_reports_tree.column(col, width=width, anchor="center")
        self.saved_reports_tree.grid(row=0, column=0, sticky="nsew")
        self.saved_reports_tree.bind("<Double-1>", lambda _event: self.open_report_preview())
        report_list_buttons = ttk.Frame(list_box)
        report_list_buttons.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        icon_button(report_list_buttons, "search", "Visualizar previa", command=self.open_report_preview, style="Accent.TButton").pack(side="left")
        icon_button(report_list_buttons, "edit", "Editar", command=self.edit_saved_report, style="Small.TButton").pack(side="left")
        icon_button(report_list_buttons, "delete", "Remover", command=self.delete_saved_report, style="Small.TButton").pack(side="left", padx=(8, 0))
        self.report_rows_cache = []
        self.report_columns_cache = []
        self.refresh_report_list()
        return frame

    def create_settings_frame(self, parent):
        frame = ttk.Frame(parent, padding=16)
        ttk.Label(frame, text="Configuracoes", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text="Ajustes do sistema, aparencia, usuarios, backup e banco de dados.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 14))

        visual = ttk.LabelFrame(frame, text="Visual do sistema", padding=12)
        visual.pack(fill="x", pady=(0, 12))
        self.palette_label_var = tk.StringVar(value=COLOR_PALETTES[self.config_data.get("color_palette", "aurora")]["label"])
        ttk.Label(visual, text="Paleta de cores").grid(row=0, column=0, sticky="w")
        palette_combo = ttk.Combobox(
            visual,
            textvariable=self.palette_label_var,
            values=[palette["label"] for palette in COLOR_PALETTES.values()],
            state="readonly",
            width=28,
        )
        palette_combo.grid(row=0, column=1, sticky="w", padx=(8, 8))
        icon_button(visual, "save", "Aplicar visual", command=self.apply_palette_from_settings, style="Accent.TButton").grid(row=0, column=2, sticky="w")

        access = ttk.LabelFrame(frame, text="Usuarios e acesso", padding=12)
        access.pack(fill="x", pady=(0, 12))
        ttk.Label(access, text="Cadastre usuarios, perfis e areas que cada pessoa pode alterar.", style="Muted.TLabel").pack(side="left")
        icon_button(
            access,
            "users",
            "Usuarios e permissoes",
            command=self.open_users,
            state="normal" if user_can_admin(self.user) else "disabled",
        ).pack(side="right")

        data = ttk.LabelFrame(frame, text="Banco de dados e backup", padding=12)
        data.pack(fill="x", pady=(0, 12))
        ttk.Label(data, text=f"Banco atual: {self.config_data['db_path']}", style="Muted.TLabel", wraplength=820).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10)
        )
        icon_button(data, "backup", "Backup agora", command=self.manual_backup).grid(row=1, column=0, sticky="w", padx=(0, 8))
        icon_button(data, "restore", "Restaurar backup", command=self.restore_backup).grid(row=1, column=1, sticky="w", padx=(0, 8))
        icon_button(data, "database", "Escolher banco SQLite", command=self.choose_database).grid(row=1, column=2, sticky="w")

        company = ttk.LabelFrame(frame, text="Identidade", padding=12)
        company.pack(fill="x")
        ttk.Label(
            company,
            text="O espaco de logo fica no topo do painel lateral. Por enquanto ele usa o nome da empresa configurado.",
            style="Muted.TLabel",
        ).pack(anchor="w")
        return frame

    def apply_palette_from_settings(self):
        label = self.palette_label_var.get()
        palette_name = next((key for key, palette in COLOR_PALETTES.items() if palette["label"] == label), "aurora")
        self.apply_palette(palette_name)

    def saved_reports(self):
        reports = self.config_data.get("saved_reports") or []
        if not reports:
            reports = DEFAULT_REPORT_DEFINITIONS
            self.config_data["saved_reports"] = reports
            save_config(self.config_data)
        return reports

    def source_label(self, source):
        return dict(REPORT_SOURCE_OPTIONS).get(source, source)

    def refresh_report_list(self):
        if not hasattr(self, "saved_reports_tree"):
            return
        current = self.selected_report_index()
        self.saved_reports_tree.delete(*self.saved_reports_tree.get_children())
        for idx, report in enumerate(self.saved_reports()):
            self.saved_reports_tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(report.get("name", "Relatorio"), self.source_label(report.get("source", "LISTAGEM")), len(report.get("columns", [])), "Abrir"),
            )
        reports = self.saved_reports()
        if reports:
            index = min(current if current is not None else 0, len(reports) - 1)
            self.saved_reports_tree.selection_set(str(index))
            self.saved_reports_tree.focus(str(index))
            self.generate_report()

    def selected_report_index(self):
        if not hasattr(self, "saved_reports_tree"):
            return None
        selection = self.saved_reports_tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except ValueError:
            return None

    def selected_report_definition(self):
        index = self.selected_report_index()
        reports = self.saved_reports()
        if index is None or index < 0 or index >= len(reports):
            return None
        return reports[index]

    def open_report_builder(self):
        dialog = ReportBuilderDialog(self, None)
        self.wait_window(dialog)
        if dialog.saved_report:
            reports = list(self.saved_reports())
            reports.append(dialog.saved_report)
            self.config_data["saved_reports"] = reports
            save_config(self.config_data)
            self.refresh_report_list()

    def edit_saved_report(self):
        index = self.selected_report_index()
        report = self.selected_report_definition()
        if report is None:
            messagebox.showwarning("Relatorios", "Selecione um relatorio.", parent=self)
            return
        dialog = ReportBuilderDialog(self, report)
        self.wait_window(dialog)
        if dialog.saved_report:
            reports = list(self.saved_reports())
            reports[index] = dialog.saved_report
            self.config_data["saved_reports"] = reports
            save_config(self.config_data)
            self.refresh_report_list()

    def delete_saved_report(self):
        index = self.selected_report_index()
        if index is None:
            messagebox.showwarning("Relatorios", "Selecione um relatorio.", parent=self)
            return
        if not messagebox.askyesno("Relatorios", "Remover este modelo de relatorio?", parent=self):
            return
        reports = list(self.saved_reports())
        reports.pop(index)
        self.config_data["saved_reports"] = reports
        save_config(self.config_data)
        self.refresh_report_list()

    def open_report_preview(self):
        definition = self.selected_report_definition()
        if not definition:
            messagebox.showwarning("Relatorios", "Selecione um relatorio.", parent=self)
            return
        rows, columns = self.report_data_for_definition(definition)
        dialog = tk.Toplevel(self)
        dialog.title(f"Previa - {definition.get('name', 'Relatorio')}")
        dialog.geometry("1120x680")
        dialog.transient(self)
        dialog.configure(background=COLOR_PALETTES[self.config_data.get("color_palette", "aurora")]["bg"])
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        top = ttk.Frame(frame)
        top.pack(fill="x")
        ttk.Label(top, text=definition.get("name", "Relatorio"), style="Title.TLabel").pack(side="left")
        icon_button(top, "pdf", "Exportar PDF", command=lambda: self.export_rows(rows, definition.get("name", "relatorio").lower().replace(" ", "_"), "pdf", columns, definition.get("name", "Relatorio"))).pack(side="right", padx=(8, 0))
        icon_button(top, "excel", "Exportar Excel", command=lambda: self.export_rows(rows, definition.get("name", "relatorio").lower().replace(" ", "_"), "xlsx", columns, definition.get("name", "Relatorio"))).pack(side="right")
        ttk.Label(frame, text=f"{len(rows)} registro(s) | Gerado em {now_br()}", style="Muted.TLabel").pack(anchor="w", pady=(2, 10))
        table_frame = ttk.Frame(frame)
        table_frame.pack(fill="both", expand=True)
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        for col in columns:
            tree.heading(col, text=export_label(col))
            width = 130
            if col in ("cliente", "obra_site", "observacao_remanejamento"):
                width = 240
            elif col.startswith("status_") or col == "situacao_fluxo":
                width = 180
            tree.column(col, width=width, anchor="center")
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        for idx, row in enumerate(rows, start=1):
            tree.insert("", "end", values=tuple(display_cell(col, row[col]) if col in row.keys() else "" for col in columns), tags=("even" if idx % 2 == 0 else "odd",))
        tree.tag_configure("odd", background="#ffffff", foreground="#0f172a", font=(FONT_FAMILY, 9, "bold"))
        tree.tag_configure("even", background="#f8fafc", foreground="#0f172a", font=(FONT_FAMILY, 9, "bold"))
        self.apply_non_ttk_colors(dialog)

    def report_data_for_definition(self, definition):
        rows = self.repo.report_rows_by_source(definition.get("source", "LISTAGEM"), self.filters("RELATORIOS"))
        selected = definition.get("columns", [])
        columns = [col for col in selected if rows and col in rows[0].keys()]
        if not rows and selected:
            columns = selected
        if not columns:
            columns = self.report_columns(rows, definition.get("name", "Relatorio"))
        return rows, columns

    def default_filters(self):
        return {
            "text": "",
            "cliente": "",
            "status": "",
            "area": "TODAS",
            "prazo": "TODOS",
            "page_size": "50",
        }

    def read_filter_controls(self):
        return {
            "text": self.filter_text.get(),
            "cliente": self.filter_cliente.get(),
            "status": self.filter_status.get(),
            "area": self.filter_area.get(),
            "prazo": self.filter_prazo.get(),
            "page_size": self.page_size_var.get(),
        }

    def write_filter_controls(self, filters):
        filters = {**self.default_filters(), **(filters or {})}
        self.filter_text.set(filters["text"])
        self.filter_cliente.set(filters["cliente"])
        self.filter_status.set(filters["status"])
        self.filter_area.set(filters["area"])
        self.filter_prazo.set(filters["prazo"])
        self.page_size_var.set(filters.get("page_size", "50"))

    def initialize_tab_filters(self):
        self.tab_filters = {"PAINEL GERAL": self.default_filters()}
        self.tab_pages = {"PAINEL GERAL": 1}
        for area in AREAS:
            filters = self.default_filters()
            filters["area"] = area
            self.tab_filters[area] = filters
            self.tab_pages[area] = 1
        self.tab_filters["HISTORICO"] = self.default_filters()
        self.tab_filters["PARCIAIS"] = self.default_filters()
        self.tab_filters["AUDITORIA"] = self.default_filters()
        self.tab_filters["RELATORIOS"] = self.default_filters()
        self.tab_filters["CONFIGURACOES"] = self.default_filters()
        self.tab_pages["HISTORICO"] = 1
        self.tab_pages["PARCIAIS"] = 1
        self.tab_pages["AUDITORIA"] = 1
        self.tab_pages["RELATORIOS"] = 1
        self.tab_pages["CONFIGURACOES"] = 1
        self.write_filter_controls(self.tab_filters["PAINEL GERAL"])

    def active_tab_key(self):
        if not hasattr(self, "notebook"):
            return "PAINEL GERAL"
        return self.tab_key_for_id(self.notebook.select())

    def filters(self, tab_key=None):
        tab_key = tab_key or self.active_tab_key()
        filters = {**self.default_filters(), **self.tab_filters.get(tab_key, self.default_filters())}
        if tab_key in AREAS:
            filters["area"] = tab_key
            filters["status_area"] = tab_key
        return filters

    def store_active_filters(self):
        tab_key = self.active_tab_key()
        self.tab_filters[tab_key] = self.read_filter_controls()
        return tab_key

    def on_tab_changed(self, _event=None):
        tab_key = self.active_tab_key()
        self.update_nav_buttons(tab_key)
        self.update_context_actions(tab_key)
        self.update_status_filter_options(tab_key)
        self.write_filter_controls(self.filters(tab_key))
        self.update_current_rows_for_active_tab()
        if tab_key in AREAS or tab_key in ("PAINEL GERAL", "PARCIAIS"):
            self.update_page_info(tab_key)
        else:
            self.page_info_var.set("")

    def update_context_actions(self, tab_key=None):
        tab_key = tab_key or self.active_tab_key()
        process_tab = tab_key == "PAINEL GERAL" or tab_key in AREAS or tab_key == "PARCIAIS"
        table_tab = tab_key in AREAS or tab_key == "PARCIAIS"
        if hasattr(self, "filters_frame"):
            if table_tab:
                self.filters_frame.pack(fill="x", padx=4, pady=(0, 4), before=self.notebook)
            else:
                self.filters_frame.pack_forget()
        if hasattr(self, "footer_frame"):
            if table_tab:
                self.footer_frame.pack(fill="x", pady=(0, 4), after=self.notebook)
            else:
                self.footer_frame.pack_forget()
        if hasattr(self, "pagination_frame"):
            if table_tab:
                self.pagination_frame.grid()
            else:
                self.pagination_frame.grid_remove()
        if hasattr(self, "export_frame"):
            if table_tab:
                self.export_frame.pack(side="right")
            else:
                self.export_frame.pack_forget()
        if hasattr(self, "area_filter_label"):
            if tab_key == "PAINEL GERAL":
                self.area_filter_label.grid()
                self.area_filter_combo.grid()
            else:
                self.area_filter_label.grid_remove()
                self.area_filter_combo.grid_remove()
        if hasattr(self, "new_button"):
            if tab_key == "CONTROLE GERAL" and user_can_edit_process(self.user):
                self.new_button.pack(side="right", padx=(5, 0))
            else:
                self.new_button.pack_forget()
        if hasattr(self, "load_button"):
            if tab_key == "GALVANIZACAO" and user_can_mount_galvanization_load(self.user):
                self.load_button.pack(side="right", padx=(5, 0))
            else:
                self.load_button.pack_forget()
        if hasattr(self, "batch_status_button"):
            if process_tab and visible_area_names(self.user):
                self.batch_status_button.pack(side="right", padx=(5, 0))
            else:
                self.batch_status_button.pack_forget()
        if hasattr(self, "early_delivery_button"):
            if tab_key == "EXPEDICAO" and user_can_access_area(self.user, "EXPEDICAO"):
                self.early_delivery_button.pack(side="right", padx=(5, 0))
            else:
                self.early_delivery_button.pack_forget()
        if hasattr(self, "details_button"):
            if process_tab:
                self.details_button.pack(side="right", padx=(5, 0))
            else:
                self.details_button.pack_forget()

    def update_status_filter_options(self, tab_key=None):
        tab_key = tab_key or self.active_tab_key()
        if tab_key in AREAS:
            values = [""] + self.repo.list_status(tab_key)
        else:
            values = [""] + self.repo.list_status()
        self.status_filter["values"] = values
        if self.filter_status.get() not in values:
            self.filter_status.set("")

    def clear_filters(self):
        tab_key = self.active_tab_key()
        filters = self.default_filters()
        if tab_key in AREAS:
            filters["area"] = tab_key
        self.tab_filters[tab_key] = filters
        self.tab_pages[tab_key] = 1
        self.write_filter_controls(filters)
        self.refresh_tab(tab_key)

    def refresh_all(self):
        self.refresh_dashboard()
        rows = self.sorted_rows(self.repo.list_processes(self.filters("PAINEL GERAL")), "PAINEL GERAL")
        self.fill_paged_tree("PAINEL GERAL", self.tree, rows)
        for area, tree in self.area_trees.items():
            area_rows = self.repo.list_processes(self.filters(area))
            area_rows = [row for row in area_rows if self.repo.visible_for_area(row, area)]
            area_rows = self.sorted_rows(area_rows, area)
            self.fill_paged_tree(area, tree, area_rows)
        partial_rows = self.sorted_rows(self.repo.list_partial_pending_processes(self.filters("PARCIAIS")), "PARCIAIS")
        self.fill_paged_tree("PARCIAIS", self.partial_tree, partial_rows)
        self.fill_history()
        self.fill_audit()
        self.generate_report()
        self.update_current_rows_for_active_tab()

    def apply_filters_current_tab(self):
        if self.active_tab_key() not in AREAS and self.active_tab_key() not in ("PAINEL GERAL", "PARCIAIS"):
            self.refresh_tab(self.active_tab_key())
            return
        tab_key = self.store_active_filters()
        self.tab_pages[tab_key] = 1
        self.refresh_tab(tab_key)

    def refresh_tab(self, tab_key):
        if tab_key == "PAINEL GERAL":
            self.refresh_dashboard()
            rows = self.sorted_rows(self.repo.list_processes(self.filters(tab_key)), tab_key)
            self.fill_paged_tree(tab_key, self.tree, rows)
            return
        if tab_key in AREAS:
            rows = self.repo.list_processes(self.filters(tab_key))
            rows = [row for row in rows if self.repo.visible_for_area(row, tab_key)]
            rows = self.sorted_rows(rows, tab_key)
            self.fill_paged_tree(tab_key, self.area_trees[tab_key], rows)
            return
        if tab_key == "PARCIAIS":
            rows = self.sorted_rows(self.repo.list_partial_pending_processes(self.filters(tab_key)), tab_key)
            self.fill_paged_tree(tab_key, self.partial_tree, rows)
            return
        if tab_key == "HISTORICO":
            self.fill_history()
            return
        if tab_key == "AUDITORIA":
            self.fill_audit()
            return
        if tab_key == "RELATORIOS":
            self.generate_report()
            return
        if tab_key == "CONFIGURACOES":
            self.page_info_var.set("")
            return

    def update_current_rows_for_active_tab(self):
        tab_key = self.active_tab_key()
        if tab_key == "PAINEL GERAL":
            rows = self.sorted_rows(self.repo.list_processes(self.filters(tab_key)), tab_key)
            self.current_all_rows = rows
            self.current_rows = self.page_rows(tab_key, rows)
            self.update_page_info(tab_key)
        elif tab_key in AREAS:
            rows = self.repo.list_processes(self.filters(tab_key))
            rows = [row for row in rows if self.repo.visible_for_area(row, tab_key)]
            rows = self.sorted_rows(rows, tab_key)
            self.current_all_rows = rows
            self.current_rows = self.page_rows(tab_key, rows)
            self.update_page_info(tab_key)
        elif tab_key == "PARCIAIS":
            rows = self.sorted_rows(self.repo.list_partial_pending_processes(self.filters(tab_key)), tab_key)
            self.current_all_rows = rows
            self.current_rows = self.page_rows(tab_key, rows)
            self.update_page_info(tab_key)
        else:
            self.current_all_rows = []
            self.current_rows = []
            self.page_info_var.set("")

    def page_size_for(self, tab_key):
        value = self.filters(tab_key).get("page_size", "50")
        if value == "Todos":
            return None
        try:
            return max(1, int(value))
        except ValueError:
            return 50

    def page_rows(self, tab_key, rows):
        page_size = self.page_size_for(tab_key)
        if not page_size:
            self.tab_pages[tab_key] = 1
            return rows
        total_pages = max(1, (len(rows) + page_size - 1) // page_size)
        page = min(max(1, self.tab_pages.get(tab_key, 1)), total_pages)
        self.tab_pages[tab_key] = page
        start = (page - 1) * page_size
        return rows[start : start + page_size]

    def fill_paged_tree(self, tab_key, tree, rows):
        page_rows = self.page_rows(tab_key, rows)
        self.fill_tree(tree, page_rows)
        if tab_key == self.active_tab_key():
            self.current_all_rows = rows
            self.current_rows = page_rows
            self.update_page_info(tab_key, len(rows), len(page_rows))

    def update_page_info(self, tab_key=None, total=None, shown=None):
        tab_key = tab_key or self.active_tab_key()
        if total is None:
            total = len(self.current_all_rows)
        if shown is None:
            shown = len(self.current_rows)
        page_size = self.page_size_for(tab_key)
        if not page_size:
            self.page_info_var.set(f"1/1 | {total} reg.")
            return
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(max(1, self.tab_pages.get(tab_key, 1)), total_pages)
        start = 0 if total == 0 else (page - 1) * page_size + 1
        end = min(total, start + shown - 1) if total else 0
        self.page_info_var.set(f"{page}/{total_pages} | {total} reg.")

    def previous_page(self):
        tab_key = self.active_tab_key()
        self.store_active_filters()
        self.tab_pages[tab_key] = max(1, self.tab_pages.get(tab_key, 1) - 1)
        self.refresh_tab(tab_key)

    def next_page(self):
        tab_key = self.active_tab_key()
        self.store_active_filters()
        total = len(self.current_all_rows)
        page_size = self.page_size_for(tab_key)
        if not page_size:
            return
        total_pages = max(1, (total + page_size - 1) // page_size)
        self.tab_pages[tab_key] = min(total_pages, self.tab_pages.get(tab_key, 1) + 1)
        self.refresh_tab(tab_key)

    def status_order(self, area, status):
        status = status or ""
        for option_area, option_status, _current, _next, order in STATUS_OPTIONS:
            if option_area == area and option_status == status:
                return order
        return 999

    def sorted_rows(self, rows, area):
        if area == "PARCIAIS":
            return sorted(
                rows,
                key=lambda row: (
                    0 if int(row["tem_pendencia_producao"] or 0) else 1,
                    0 if (row["status_expedicao"] or "") == "ENTREGUE_PARCIAL" else 1,
                    self.sort_date_value(row["prazo_entrega"]),
                    row["cliente"] or "",
                    row["proposta"] or "",
                ),
            )
        if area not in AREAS:
            return sorted(
                rows,
                key=lambda row: (
                    1 if (row["status_geral"] or "") in AREA_FINISHED_STATUS["CONTROLE GERAL"] else 0,
                    row["id"],
                ),
            )
        status_column = AREAS[area]["column"]
        finished = AREA_FINISHED_STATUS.get(area, set())
        return sorted(
            rows,
            key=lambda row: (
                1 if (row[status_column] or "") in finished else 0,
                self.status_order(area, row[status_column]),
                self.sort_date_value(row["prazo_entrega"]),
                row["id"],
            ),
        )

    def sort_date_value(self, value):
        try:
            parsed = parse_date(value)
        except AppError:
            return date.max
        return parsed or date.max

    def dashboard_row_area_status(self, row):
        for area, column in (
            ("Expedicao", "status_expedicao"),
            ("Galvanizacao", "status_galvanizacao"),
            ("Producao", "status_producao"),
            ("Almox.", "status_almoxarifado"),
        ):
            if row[column]:
                return area, status_label(row[column])
        return "Controle", status_label(row["status_geral"])

    def show_dashboard_details(self, source, key):
        if source == "metric":
            rows = self.repo.dashboard_metric_rows(key)
            title = key
        else:
            rows = self.repo.dashboard_chart_rows(source, key)
            title = status_label(key) if source == "status" else key
        self.show_dashboard_popup(title, rows)

    def show_dashboard_popup(self, title, rows):
        dialog = tk.Toplevel(self)
        dialog.configure(background=COLOR_PALETTES[self.config_data.get("color_palette", "aurora")]["bg"])
        dialog.title(f"{title} - {len(rows)} proposta(s)")
        dialog.geometry("980x520")
        dialog.transient(self)
        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=f"{title}", style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame, text=f"{len(rows)} proposta(s) encontradas. Duplo clique para abrir a proposta.", style="Muted.TLabel").pack(anchor="w", pady=(2, 10))
        table_frame = ttk.Frame(frame)
        table_frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(
            table_frame,
            columns=("cliente", "proposta", "tipo", "area", "status", "prazo"),
            show="headings",
            height=15,
        )
        for col, label, width in (
            ("cliente", "Cliente", 260),
            ("proposta", "Proposta", 130),
            ("tipo", "Tipo", 90),
            ("area", "Area", 130),
            ("status", "Status atual", 210),
            ("prazo", "Prazo", 100),
        ):
            tree.heading(col, text=label)
            tree.column(col, width=width, anchor="center", stretch=True)
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        for idx, row in enumerate(rows[:500]):
            area, status = self.dashboard_row_area_status(row)
            tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    row["cliente"],
                    row["proposta"],
                    status_label(row["tipo_processo"] if "tipo_processo" in row.keys() else ""),
                    area,
                    status,
                    row["prazo_entrega"] or "",
                ),
                tags=("even" if idx % 2 else "odd",),
            )
        tree.tag_configure("odd", background="#ffffff", foreground="#0f172a", font=(FONT_FAMILY, 9, "bold"))
        tree.tag_configure("even", background="#f8fafc", foreground="#0f172a", font=(FONT_FAMILY, 9, "bold"))
        tree.bind("<Double-1>", lambda _event, target=tree, popup=dialog: self.open_dashboard_popup_process(target, popup))
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(10, 0))
        icon_button(buttons, "cancel", "Fechar", command=dialog.destroy).pack(side="right")
        self.apply_non_ttk_colors(dialog)

    def on_dashboard_chart_click(self, event, chart_key):
        if chart_key == "prazos":
            for cx, cy, radius, start_angle, end_angle, label in getattr(self, "deadline_segments", []):
                distance = math.hypot(event.x - cx, event.y - cy)
                if radius * 0.55 <= distance <= radius:
                    angle = (math.degrees(math.atan2(event.x - cx, cy - event.y)) + 360) % 360
                    if start_angle <= angle <= end_angle:
                        self.show_dashboard_details(chart_key, label)
                        return
        for region in self.chart_regions.get(chart_key, []):
            x1, y1, x2, y2, label = region
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self.show_dashboard_details(chart_key, label)
                return

    def open_dashboard_popup_process(self, tree, popup):
        selection = tree.selection()
        if not selection:
            return
        process_id = int(selection[0])
        try:
            self.repo.acquire_process_lock(process_id, self.user)
            process = self.repo.get_process(process_id)
            form = ProcessForm(self, self.repo, self.user, process)
            self.wait_window(form)
            if form.saved:
                self.refresh_all()
        except AppError as exc:
            messagebox.showerror("Editar processo", str(exc), parent=self)
        finally:
            self.repo.release_process_lock(process_id, self.user)

    def refresh_dashboard(self):
        values = self.repo.dashboard()
        for label, value in values.items():
            if label in self.kpi_vars:
                self.kpi_vars[label].set(str(value))
        if hasattr(self, "dashboard_focus_var"):
            self.dashboard_focus_var.set(self.repo.dashboard_focus_text())
        if getattr(self, "chart_canvases", None):
            self.draw_dashboard_charts(self.repo.dashboard_charts())

    def draw_dashboard_charts(self, charts):
        self.chart_regions = {"status": [], "areas": [], "prazos": []}
        self.draw_horizontal_chart(self.chart_canvases.get("status"), charts.get("status", [])[:5])
        self.draw_vertical_chart(self.chart_canvases.get("areas"), charts.get("areas", []))
        self.draw_deadline_chart(self.chart_canvases.get("prazos"), charts.get("prazos", []))

    def canvas_palette(self):
        palette = COLOR_PALETTES[self.config_data.get("color_palette", "aurora")]
        return {
            "bg": palette["surface"],
            "text": palette["text"],
            "muted": palette["muted"],
            "accent": palette["accent"],
            "secondary": palette["secondary"],
            "success": palette["success"],
            "warning": palette["warning"],
            "danger": palette["danger"],
            "border": palette["border"],
        }

    def clear_chart(self, canvas):
        if not canvas:
            return None
        colors = self.canvas_palette()
        canvas.delete("all")
        canvas.configure(background=colors["bg"])
        width = max(canvas.winfo_width(), 260)
        height = max(canvas.winfo_height(), 140)
        return colors, width, height

    def draw_empty_chart(self, canvas, message="Sem dados"):
        result = self.clear_chart(canvas)
        if not result:
            return
        colors, width, height = result
        canvas.create_text(width / 2, height / 2, text=message, fill=colors["muted"], font=(FONT_FAMILY, 10, "bold"))

    def draw_horizontal_chart(self, canvas, data):
        chart_key = "status"
        self.chart_regions[chart_key] = []
        data = [(label, total) for label, total in data if total]
        if not data:
            self.draw_empty_chart(canvas)
            return
        colors, width, height = self.clear_chart(canvas)
        max_value = max(total for _label, total in data) or 1
        top = 16
        row_h = max(30, (height - 30) // max(len(data), 1))
        palette_colors = ["#2563eb", "#0f766e", "#d97706", "#7c3aed", "#dc2626"]
        for idx, (label, total) in enumerate(data):
            y = top + idx * row_h
            bar_w = max(8, int((width - 150) * total / max_value))
            color = palette_colors[idx % len(palette_colors)]
            label_text = status_label(label)[:18]
            canvas.create_text(10, y + 12, text=label_text, anchor="w", fill=colors["text"], font=(FONT_FAMILY, 9, "bold"))
            canvas.create_rectangle(128, y + 3, width - 34, y + 23, fill="#e5e7eb", outline="")
            canvas.create_rectangle(128, y + 3, 128 + bar_w, y + 23, fill=color, outline="")
            self.chart_regions[chart_key].append((6, y - 2, width - 8, y + 28, label))
            canvas.create_text(width - 12, y + 13, text=str(total), anchor="e", fill=colors["text"], font=(FONT_FAMILY, 10, "bold"))

    def draw_vertical_chart(self, canvas, data):
        chart_key = "areas"
        self.chart_regions[chart_key] = []
        data = [(label, total) for label, total in data if total]
        if not data:
            self.draw_empty_chart(canvas)
            return
        colors, width, height = self.clear_chart(canvas)
        max_value = max(total for _label, total in data) or 1
        left = 22
        bottom = height - 34
        usable_h = max(70, height - 64)
        gap = 12
        bar_w = max(24, (width - 2 * left - gap * (len(data) - 1)) // len(data))
        palette_colors = ["#0891b2", "#7c3aed", "#16a34a", "#f59e0b", "#e11d48"]
        for idx, (label, total) in enumerate(data):
            x = left + idx * (bar_w + gap)
            bar_h = max(4, int(usable_h * total / max_value))
            color = palette_colors[idx % len(palette_colors)]
            canvas.create_rectangle(x, bottom - usable_h, x + bar_w, bottom, fill="#e5e7eb", outline="")
            canvas.create_rectangle(x, bottom - bar_h, x + bar_w, bottom, fill=color, outline="")
            self.chart_regions[chart_key].append((x, bottom - usable_h - 18, x + bar_w, bottom + 24, label))
            canvas.create_text(x + bar_w / 2, bottom - bar_h - 12, text=str(total), fill=colors["text"], font=(FONT_FAMILY, 10, "bold"))
            canvas.create_text(x + bar_w / 2, bottom + 12, text=label[:10], fill=colors["muted"], font=(FONT_FAMILY, 8, "bold"))

    def draw_deadline_chart(self, canvas, data):
        chart_key = "prazos"
        self.chart_regions[chart_key] = []
        data = [(label, total) for label, total in data if total]
        if not data:
            self.draw_empty_chart(canvas)
            return
        colors, width, height = self.clear_chart(canvas)
        total_sum = sum(total for _label, total in data) or 1
        color_map = {
            "Vencidos": colors["danger"],
            "7 dias": colors["warning"],
            "No prazo": colors["success"],
            "Entregues": colors["accent"],
        }
        cx = min(width * 0.32, 150)
        cy = height / 2
        radius = min(78, height / 2 - 18)
        start = 90
        clockwise_start = 0
        self.deadline_segments = []
        for label, total in data:
            extent = 360 * total / total_sum
            canvas.create_arc(cx - radius, cy - radius, cx + radius, cy + radius, start=start, extent=-extent, fill=color_map.get(label, colors["secondary"]), outline=colors["bg"], width=2)
            start -= extent
            self.deadline_segments.append((cx, cy, radius, clockwise_start, clockwise_start + extent, label))
            clockwise_start += extent
        canvas.create_oval(cx - radius * 0.55, cy - radius * 0.55, cx + radius * 0.55, cy + radius * 0.55, fill=colors["bg"], outline=colors["bg"])
        canvas.create_text(cx, cy - 8, text=str(total_sum), fill=colors["text"], font=(FONT_FAMILY, 18, "bold"))
        canvas.create_text(cx, cy + 14, text="total", fill=colors["muted"], font=(FONT_FAMILY, 9, "bold"))
        legend_y = max(28, cy - 66)
        legend_x = int(width * 0.56)
        for label, total in data:
            color = color_map.get(label, colors["secondary"])
            canvas.create_rectangle(legend_x, legend_y, legend_x + 14, legend_y + 14, fill=color, outline="")
            canvas.create_text(legend_x + 22, legend_y + 7, text=f"{label}: {total}", anchor="w", fill=colors["text"], font=(FONT_FAMILY, 10, "bold"))
            self.chart_regions[chart_key].append((legend_x, legend_y - 6, width - 10, legend_y + 20, label))
            legend_y += 28

    def fill_tree(self, tree, rows):
        tree.delete(*tree.get_children())
        columns = getattr(tree, "process_columns", PROCESS_COLUMNS)
        for idx, row in enumerate(rows):
            tags = list(self.row_tags(row, getattr(tree, "area_key", "PAINEL GERAL")))
            if not any(tag.startswith("status_") for tag in tags):
                tags.append("even" if idx % 2 else "odd")
            values = [
                self.display_process_cell(row, key) for key, _label, _width in columns
            ]
            tree.insert("", "end", iid=row["id"], text="", image=self.status_image_for_row(row, getattr(tree, "area_key", "PAINEL GERAL")), values=values, tags=tuple(tags))

    def status_image_for_row(self, row, tab_key=None):
        status = self.row_status_for_tab(row, tab_key or self.active_tab_key())
        key = status_icon_key(status)
        badge_key = f"{key}_badge"
        return self.icon_images.get(badge_key, self.icon_images.get(key, self.icon_images.get("status")))

    def display_process_cell(self, row, key):
        if key == "almoxarifado_info":
            return self.almoxarifado_info(row)
        if key == "localizacao_atual":
            area_key, area_label, _status = self.current_location(row)
            return area_label or "-"
        if key == "status_localizacao":
            area_key, _area_label, status = self.current_location(row)
            return area_status_label(area_key, status) if status else "-"
        return self.display_status_value(key, row[key])

    def almoxarifado_info(self, row):
        need = normalize_stockroom_need(row["necessita_almoxarifado"] if "necessita_almoxarifado" in row.keys() else "")
        status = normalize_status(row["status_almoxarifado"] or "")
        if need == "NAO" or status == "SEM_PARAFUSOS":
            return "Sem Almox."
        if status == "ALMOXARIFADO_ENTREGUE":
            return "Almox. entregue"
        if status:
            return "Tem Almox."
        return "Almox. indef."

    def current_location_label(self, row):
        area_key, area_label, status = self.current_location(row)
        if not area_label or not status:
            return "-"
        return f"{area_label}: {area_status_label(area_key, status)}"

    def current_location(self, row):
        area_order = (
            ("EXPEDICAO", "Expedicao", "status_expedicao"),
            ("GALVANIZACAO", "Galvanizacao", "status_galvanizacao"),
            ("PRODUCAO", "Producao", "status_producao"),
            ("CONTROLE GERAL", "Controle geral", "status_geral"),
        )

        if (row["tipo_processo"] or "PRINCIPAL") == "PRINCIPAL":
            if (row["status_producao"] or "") in ("FINALIZADO_PARCIAL", "ITEM_PENDENTE_FABRICACAO"):
                return "PRODUCAO", "Producao", row["status_producao"]
            partial_location = self.current_active_partial_location(row["id"], area_order)
            if partial_location:
                return partial_location

        if (row["status_expedicao"] or "") == "UNIFICADA_PRINCIPAL":
            return "CONTROLE GERAL", "Controle geral", "UNIFICADA_PRINCIPAL"

        for area_key, area_label, column in area_order:
            status = normalize_status(row[column] or "")
            if not status:
                continue
            if area_key != "CONTROLE GERAL" and status in AREA_FINISHED_STATUS.get(area_key, set()):
                continue
            if area_key == "EXPEDICAO" and status == "UNIFICADA_PRINCIPAL":
                continue
            label = area_status_label(area_key, status)
            if label:
                return area_key, area_label, status
        status = normalize_status(row["status_geral"] or "")
        return ("CONTROLE GERAL", "Controle geral", status) if status else ("", "", "")

    def current_active_partial_location(self, parent_id, area_order):
        active_partials = self.repo.list_active_child_partials(parent_id)
        for area_key, area_label, column in area_order:
            for partial in active_partials:
                status = normalize_status(partial[column] or "")
                if not status:
                    continue
                if area_key != "CONTROLE GERAL" and status in AREA_FINISHED_STATUS.get(area_key, set()):
                    continue
                if area_key == "EXPEDICAO" and status == "UNIFICADA_PRINCIPAL":
                    continue
                label = area_status_label(area_key, status)
                if label:
                    return area_key, area_label, status
        return None

    def display_status_value(self, key, value):
        if key.startswith("status_") or key in ("situacao_fluxo", "tipo_processo"):
            area_by_column = {
                "status_geral": "CONTROLE GERAL",
                "status_producao": "PRODUCAO",
                "status_galvanizacao": "GALVANIZACAO",
                "status_expedicao": "EXPEDICAO",
                "status_almoxarifado": "ALMOXARIFADO",
            }
            if key in area_by_column:
                status = normalize_status(value)
                label = area_status_label(area_by_column[key], status)
                return f"{STATUS_ICONS.get(status, ICONS['status'])} {label}" if label else ""
            return status_display(value) if key != "tipo_processo" else status_label(value)
        return self.display_value(value)

    def row_tags(self, row, tab_key=None):
        tags = []
        tab_key = tab_key or self.active_tab_key()
        status = self.row_status_for_tab(row, tab_key)
        if status:
            tags.append(f"status_{status}")
        if tab_key in AREAS and status in AREA_FINISHED_STATUS.get(tab_key, set()):
            tags.append("finished")
        prazo = row["prazo_entrega"]
        if not prazo:
            return tuple(tags)
        try:
            prazo_date = parse_date(prazo)
        except AppError:
            return tuple(tags)
        if row["status_geral"] == "ENTREGUE":
            return tuple(tags)
        if prazo_date < date.today():
            tags.append("overdue")
            return tuple(tags)
        if prazo_date <= date.today() + timedelta(days=7):
            tags.append("soon")
        return tuple(tags)

    def row_status_for_tab(self, row, tab_key):
        if tab_key in AREAS:
            return row[AREAS[tab_key]["column"]] or row["status_geral"] or ""
        if tab_key == "PARCIAIS":
            for column in ("status_expedicao", "status_galvanizacao", "status_producao", "situacao_fluxo"):
                if row[column]:
                    return row[column]
            return row["status_geral"] or ""
        return row["status_geral"] or ""

    def display_value(self, value):
        if value is None:
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    def fill_history(self):
        self.history_tree.delete(*self.history_tree.get_children())
        summary = self.repo.history_summary()
        if hasattr(self, "history_summary_var"):
            total = sum(row["total"] for row in summary)
            details = " | ".join(f"{row['area']}: {row['total']}" for row in summary[:5])
            self.history_summary_var.set(f"{total} movimentacao(oes) registradas. {details}")
        for idx, row in enumerate(self.repo.history()):
            self.history_tree.insert(
                "",
                "end",
                values=(
                    row["proposta"],
                    row["area"],
                    status_label(row["status_anterior"]),
                    status_label(row["status_novo"]),
                    row["data_hora"],
                    row["usuario"],
                    row["computador"],
                    row["observacao"],
                ),
                tags=("even" if idx % 2 else "odd",),
            )

    def fill_audit(self):
        if not self.audit_tree:
            return
        self.audit_tree.delete(*self.audit_tree.get_children())
        summary = self.repo.audit_summary()
        if hasattr(self, "audit_summary_var"):
            total = sum(row["total"] for row in summary)
            details = " | ".join(f"{row['acao'].replace('_', ' ').title()}: {row['total']}" for row in summary[:5])
            self.audit_summary_var.set(f"{total} alteracao(oes) auditadas. {details}")
        for idx, row in enumerate(self.repo.audit()):
            self.audit_tree.insert(
                "",
                "end",
                values=(
                    display_cell("acao", row["acao"]),
                    display_cell("entidade", row["entidade"]),
                    row["entidade_id"],
                    display_cell("campo", row["campo"]),
                    display_cell(row["campo"], row["valor_anterior"]),
                    display_cell(row["campo"], row["valor_novo"]),
                    row["data_hora"],
                    row["usuario"],
                ),
                tags=("even" if idx % 2 else "odd",),
            )

    def active_process_tree(self):
        current = self.notebook.select()
        widget = self.nametowidget(current)
        trees = [self.tree] + list(self.area_trees.values())
        if hasattr(self, "partial_tree"):
            trees.append(self.partial_tree)
        return next((candidate for candidate in trees if str(candidate.master) == str(widget)), self.tree)

    def selected_process_ids(self):
        tree = self.active_process_tree()
        selection = tree.selection()
        if not selection:
            messagebox.showwarning("Processo", "Selecione um processo.")
            return []
        return [int(item) for item in selection]

    def selected_process_id(self):
        ids = self.selected_process_ids()
        return ids[0] if ids else None

    def update_row_icon_cursor(self, event):
        tree = event.widget
        if tree.identify_column(event.x) == "#0" and tree.identify_row(event.y):
            tree.configure(cursor="hand2")
        else:
            tree.configure(cursor="")

    def open_status_from_row_icon(self, event):
        tree = event.widget
        if tree.identify_column(event.x) != "#0":
            return
        row_id = tree.identify_row(event.y)
        if not row_id:
            return
        tree.selection_set(row_id)
        tree.focus(row_id)
        self.change_status_for_process(int(row_id), tree)

    def default_status_area(self):
        tab_text = self.notebook.tab(self.notebook.select(), "text").upper()
        return next((name for name in AREAS if name == tab_text), "CONTROLE GERAL")

    def status_area_for_tree_row(self, tree, process):
        tree_area = getattr(tree, "area_key", "")
        allowed_areas = visible_area_names(self.user)
        if tree_area in AREAS:
            return tree_area
        area_key, _area_label, _status = self.current_location(process)
        if area_key in AREAS:
            return area_key
        if area_key == "CONTROLE GERAL" and "CONTROLE GERAL" in allowed_areas:
            return "CONTROLE GERAL"
        return self.default_status_area()

    def change_status_for_process(self, process_id, tree=None):
        allowed_areas = visible_area_names(self.user)
        if not allowed_areas:
            messagebox.showwarning("Permissao", "Seu usuario nao tem area liberada para alterar status.", parent=self)
            return
        process = self.repo.get_process(process_id)
        if not process:
            return
        area = self.status_area_for_tree_row(tree, process) if tree else self.default_status_area()
        if area not in allowed_areas:
            messagebox.showwarning("Permissao", f"Seu usuario nao tem acesso para alterar status em {area.title()}.", parent=self)
            return
        try:
            self.repo.acquire_process_lock(process_id, self.user)
            process = self.repo.get_process(process_id)
            dialog = StatusDialog(self, self.repo, self.user, process, area)
            self.wait_window(dialog)
            if dialog.saved:
                self.refresh_all()
        except AppError as exc:
            messagebox.showerror("Alterar status", str(exc), parent=self)
        finally:
            self.repo.release_process_lock(process_id, self.user)

    def show_process_menu(self, event):
        tree = event.widget
        row_id = tree.identify_row(event.y)
        if not row_id:
            return
        if row_id not in tree.selection():
            tree.selection_set(row_id)
            tree.focus(row_id)
        menu = tk.Menu(self, tearoff=False)
        selected_count = len(tree.selection())
        menu.add_command(label="Ver detalhes da proposta", command=self.show_process_details)
        menu.add_command(
            label="Editar proposta",
            command=self.edit_process,
            state="normal" if user_can_edit_process(self.user) else "disabled",
        )
        menu.add_command(
            label=f"Alterar status ({selected_count})",
            command=self.change_status,
            state="normal" if visible_area_names(self.user) else "disabled",
        )
        menu.add_command(
            label="Alterar status em lote...",
            command=self.open_batch_status_selection,
            state="normal" if visible_area_names(self.user) else "disabled",
        )
        menu.add_command(label="Historico da proposta", command=self.show_selected_history)
        menu.add_command(label="Exportar selecao Excel", command=lambda: self.export_selected("xlsx"))
        menu.add_command(label="Exportar selecao PDF", command=lambda: self.export_selected("pdf"))
        menu.add_separator()
        menu.add_command(
            label="Duplicar proposta",
            command=self.duplicate_process,
            state="normal" if user_can_edit_process(self.user) else "disabled",
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def show_process_details(self):
        process_id = self.selected_process_id()
        if not process_id:
            return
        dialog = ProcessDetailDialog(self, self.repo, self.user, process_id)
        self.wait_window(dialog)
        if dialog.changed:
            self.refresh_all()

    def show_selected_history(self):
        process_id = self.selected_process_id()
        if not process_id:
            return
        process = self.repo.get_process(process_id)
        rows = self.repo.history(process_id)
        dialog = tk.Toplevel(self)
        dialog.configure(background=COLOR_PALETTES[self.config_data.get("color_palette", "aurora")]["bg"])
        dialog.title(f"Historico - {process['proposta'] if process else process_id}")
        dialog.geometry("920x420")
        dialog.transient(self)
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=("area", "anterior", "novo", "data", "usuario", "observacao"), show="headings")
        for col, label, width in (
            ("area", "Area", 130),
            ("anterior", "Anterior", 150),
            ("novo", "Novo", 150),
            ("data", "Data/Hora", 140),
            ("usuario", "Usuario", 100),
            ("observacao", "Observacao", 260),
        ):
            tree.heading(col, text=label)
            tree.column(col, width=width)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        for row in rows:
            tree.insert(
                "",
                "end",
                values=(row["area"], status_label(row["status_anterior"]), status_label(row["status_novo"]), row["data_hora"], row["usuario"], row["observacao"]),
            )
        icon_button(frame, "cancel", "Fechar", command=dialog.destroy).grid(row=1, column=0, sticky="e", pady=(10, 0))

    def new_process(self):
        if self.active_tab_key() != "CONTROLE GERAL":
            messagebox.showwarning("Novo processo", "Novas propostas devem ser cadastradas pelo Controle Geral.", parent=self)
            return
        if not user_can_edit_process(self.user):
            messagebox.showwarning("Permissao", "Seu usuario nao pode cadastrar processos.", parent=self)
            return
        form = ProcessForm(self, self.repo, self.user)
        self.wait_window(form)
        if form.saved:
            self.refresh_all()

    def edit_process(self):
        if not user_can_edit_process(self.user):
            messagebox.showwarning("Permissao", "Seu usuario nao pode editar dados do processo.", parent=self)
            return
        process_id = self.selected_process_id()
        if not process_id:
            return
        try:
            self.repo.acquire_process_lock(process_id, self.user)
            process = self.repo.get_process(process_id)
            form = ProcessForm(self, self.repo, self.user, process)
            self.wait_window(form)
            if form.saved:
                self.refresh_all()
        except AppError as exc:
            messagebox.showerror("Editar processo", str(exc), parent=self)
        finally:
            self.repo.release_process_lock(process_id, self.user)

    def duplicate_process(self):
        if not user_can_edit_process(self.user):
            messagebox.showwarning("Permissao", "Seu usuario nao pode duplicar processos.", parent=self)
            return
        process_id = self.selected_process_id()
        if not process_id:
            return
        process = self.repo.get_process(process_id)
        if not process:
            return
        new_proposal = simpledialog.askstring(
            "Duplicar processo",
            f"Informe a nova proposta para copiar os dados de {process['proposta']}:",
            parent=self,
        )
        if not new_proposal:
            return
        data = {
            "cliente": process["cliente"],
            "proposta": new_proposal,
            "pedido_compra": process["pedido_compra"],
            "obra_site": process["obra_site"],
            "peso": process["peso"],
            "lote": process["lote"],
            "data_entrada": today_br(),
            "prazo_entrega": process["prazo_entrega"],
            "observacoes_gerais": process["observacoes_gerais"],
            "observacoes_producao": process["observacoes_producao"],
            "observacoes_galvanizacao": process["observacoes_galvanizacao"],
            "observacoes_expedicao": process["observacoes_expedicao"],
            "observacoes_almoxarifado": process["observacoes_almoxarifado"],
        }
        try:
            self.repo.save_process(data, self.user)
        except AppError as exc:
            messagebox.showerror("Duplicar processo", str(exc), parent=self)
            return
        self.refresh_all()
        messagebox.showinfo("Duplicar processo", "Processo duplicado com sucesso.", parent=self)

    def change_status(self):
        allowed_areas = visible_area_names(self.user)
        if not allowed_areas:
            messagebox.showwarning("Permissao", "Seu usuario nao tem area liberada para alterar status.", parent=self)
            return
        process_ids = self.selected_process_ids()
        if not process_ids:
            return
        if len(process_ids) > 1:
            self.change_status_batch(process_ids)
            return
        process_id = process_ids[0]
        self.change_status_for_process(process_id, self.active_process_tree())

    def change_status_batch(self, process_ids):
        dialog = BatchStatusDialog(self, self.repo, len(process_ids), self.default_status_area(), visible_area_names(self.user), process_ids)
        self.wait_window(dialog)
        if not dialog.saved:
            return
        area = dialog.area_var.get()
        status = dialog.status_choices.get(dialog.status_var.get(), dialog.status_var.get())
        observation = dialog.observation.get("1.0", "end").strip()
        if not messagebox.askyesno(
            "Alterar status em lote",
            f"Aplicar o status {status} em {len(process_ids)} proposta(s)?",
            parent=self,
        ):
            return
        changed = 0
        failures = []
        locked = []
        try:
            for process_id in process_ids:
                proposal = str(process_id)
                try:
                    self.repo.acquire_process_lock(process_id, self.user)
                    locked.append(process_id)
                    process = self.repo.get_process(process_id)
                    proposal = process["proposta"] if process else str(process_id)
                    self.repo.update_status(process_id, area, status, observation, self.user)
                    changed += 1
                except AppError as exc:
                    failures.append(f"{proposal}: {exc}")
        finally:
            for process_id in locked:
                try:
                    self.repo.release_process_lock(process_id, self.user)
                except Exception:
                    pass
        self.refresh_all()
        if failures:
            message = f"{changed} proposta(s) alterada(s).\n\nNao alteradas:\n" + "\n".join(failures[:10])
            if len(failures) > 10:
                message += f"\n... e mais {len(failures) - 10}."
            messagebox.showwarning("Alterar status em lote", message, parent=self)
        else:
            messagebox.showinfo("Alterar status em lote", f"{changed} proposta(s) alterada(s) com sucesso.", parent=self)

    def open_batch_status_selection(self):
        if not visible_area_names(self.user):
            messagebox.showwarning("Permissao", "Seu usuario nao tem area liberada para alterar status.", parent=self)
            return
        tree = self.active_process_tree()
        initial_ids = [int(item) for item in tree.selection()] if tree.selection() else []
        dialog = BatchStatusSelectionDialog(self, self.repo, self.user, self.default_status_area(), initial_ids)
        self.wait_window(dialog)
        if dialog.changed:
            self.refresh_all()

    def open_early_remanagement_delivery(self):
        if not user_can_access_area(self.user, "EXPEDICAO"):
            messagebox.showwarning("Permissao", "Seu usuario nao tem permissao para entrega por remanejamento.", parent=self)
            return
        dialog = EarlyRemanagementDeliveryDialog(self, self.repo, self.user)
        self.wait_window(dialog)
        if dialog.changed:
            self.refresh_all()

    def mount_galvanization_load(self):
        if not user_can_mount_galvanization_load(self.user):
            messagebox.showwarning("Permissao", "Seu usuario nao pode montar carga de galvanizacao.", parent=self)
            return
        preselected_ids = []
        if self.active_tab_key() == "GALVANIZACAO":
            tree = self.active_process_tree()
            preselected_ids = [int(item) for item in tree.selection()]
        dialog = GalvanizationLoadManagerDialog(self, self.repo, self.user, preselected_ids)
        self.wait_window(dialog)
        if dialog.changed:
            self.refresh_all()

    def generate_report(self):
        definition = self.selected_report_definition()
        if not definition:
            self.report_rows_cache = []
            self.report_columns_cache = []
            self.report_summary_var.set("Nenhum relatorio criado.")
            return
        name = definition.get("name", "Relatorio")
        rows, columns = self.report_data_for_definition(definition)
        self.report_rows_cache = rows
        self.report_columns_cache = columns
        self.report_name.set(name)
        self.report_summary_var.set(f"{name} | {len(rows)} registro(s) | Clique em Visualizar previa para abrir a tabela.")

    def fill_report_table(self, rows, title, columns=None):
        if not hasattr(self, "report_tree"):
            return
        self.report_tree.delete(*self.report_tree.get_children())
        if hasattr(self, "report_summary_var"):
            self.report_summary_var.set(f"{title} | {len(rows)} registro(s) | Gerado em {now_br()}")
        columns = columns or self.report_columns(rows, title)
        self.report_tree["columns"] = columns
        for col in columns:
            self.report_tree.heading(col, text=export_label(col))
            width = 120
            if col in ("cliente", "obra_site", "observacao"):
                width = 220
            elif col.startswith("status_") or col in ("status_anterior", "status_novo"):
                width = 170
            self.report_tree.column(col, width=width, anchor="center")
        if not rows:
            return
        for idx, row in enumerate(rows, start=1):
            self.report_tree.insert(
                "",
                "end",
                iid=str(idx),
                values=tuple(display_cell(col, row[col]) if col in row.keys() else "" for col in columns),
                tags=("even" if idx % 2 == 0 else "odd",),
            )

    def report_columns(self, rows, title):
        if title == "Producao por status":
            return ["status_producao", "total"]
        if title == "Entregas por cliente":
            return ["cliente", "proposta", "pedido_compra", "obra_site", "prazo_entrega", "data_retirada", "status_expedicao", "status_geral"]
        if title == "Galvanizacao enviada/retorno":
            return ["proposta", "cliente", "obra_site", "lote", "peso", "data_envio_galv", "data_prevista_retorno_galv", "data_retorno_galv", "status_galvanizacao", "status_expedicao", "situacao_fluxo"]
        if title == "Remanejamentos":
            return ["proposta", "cliente", "obra_site", "lote", "peso", "origem_remanejamento", "observacao_remanejamento", "status_producao", "status_expedicao", "situacao_fluxo", "atualizado_em", "atualizado_por"]
        preferred = [
            "id",
            "tipo_processo",
            "proposta",
            "processo_pai_id",
            "numero_parcial",
            "cliente",
            "obra_site",
            "lote",
            "peso",
            "peso_parcial",
            "saldo_pendente",
            "prazo_entrega",
            "status_geral",
            "situacao_fluxo",
            "tem_pendencia_producao",
            "status_producao",
            "status_galvanizacao",
            "status_expedicao",
            "descricao_parcial",
            "origem_remanejamento",
            "observacao_remanejamento",
        ]
        if not rows:
            return preferred
        keys = list(rows[0].keys())
        selected = [key for key in preferred if key in keys]
        return selected or keys

    def export_current(self, kind):
        rows = self.current_rows
        if not rows:
            messagebox.showinfo("Exportacao", "Nao ha dados para exportar.")
            return
        self.export_rows(rows, "processos_filtrados", kind)

    def export_selected(self, kind):
        process_ids = self.selected_process_ids()
        if not process_ids:
            return
        rows = [self.repo.get_process(process_id) for process_id in process_ids]
        rows = [row for row in rows if row]
        if not rows:
            messagebox.showinfo("Exportacao", "Nao ha dados para exportar.")
            return
        self.export_rows(rows, "processos_selecionados", kind)

    def export_report(self, kind):
        rows = self.report_rows_cache
        if not rows:
            messagebox.showinfo("Exportacao", "Nao ha dados para exportar.")
            return
        self.export_rows(rows, self.report_name.get().lower().replace(" ", "_"), kind, self.report_columns_cache, self.report_name.get())

    def export_rows(self, rows, name, kind, columns=None, title=None):
        default_ext = ".xlsx" if kind == "xlsx" else ".pdf"
        path = filedialog.asksaveasfilename(
            title="Salvar relatorio",
            defaultextension=default_ext,
            filetypes=[("Excel", "*.xlsx")] if kind == "xlsx" else [("PDF", "*.pdf")],
            initialfile=f"{name}_{datetime.now().strftime('%Y%m%d')}{default_ext}",
        )
        if not path:
            return
        try:
            if kind == "xlsx":
                write_xlsx(path, rows, columns=columns, title=title or name)
            else:
                write_pdf(path, rows, title or name, columns=columns)
        except Exception as exc:
            messagebox.showerror("Exportacao", f"Falha ao exportar: {exc}")
            return
        messagebox.showinfo("Exportacao", f"Arquivo salvo em:\n{path}")

    def manual_backup(self):
        target = backup_database(self.config_data, "manual")
        messagebox.showinfo("Backup", f"Backup criado em:\n{target}")

    def restore_backup(self):
        path = filedialog.askopenfilename(
            title="Restaurar backup",
            filetypes=[("Backup SQLite", "*.db"), ("Todos", "*.*")],
            initialdir=self.config_data.get("backup_dir", str(DEFAULT_BACKUP_DIR)),
        )
        if not path:
            return
        if not messagebox.askyesno(
            "Restaurar backup",
            "O banco atual sera substituido pelo backup escolhido.\n"
            "Uma copia do banco atual sera criada antes da restauracao.\n\n"
            "Deseja continuar?",
            parent=self,
        ):
            return
        connection_closed = False
        try:
            validate_database_file(path)
            if Path(path).resolve() == Path(self.config_data["db_path"]).resolve():
                raise AppError("Escolha um backup diferente do banco que esta em uso.")
            safety_backup = backup_database(self.config_data, "antes_restaurar")
            self.conn.close()
            connection_closed = True
            remove_database_sidecars(self.config_data["db_path"])
            shutil.copy2(path, self.config_data["db_path"])
            remove_database_sidecars(self.config_data["db_path"])
            self.conn = db_connect(self.config_data["db_path"])
            connection_closed = False
            initialize_database(self.conn)
            self.repo = Repository(self.conn)
            self.refresh_all()
        except Exception as exc:
            if connection_closed:
                try:
                    self.conn = db_connect(self.config_data["db_path"])
                    self.repo = Repository(self.conn)
                except Exception:
                    pass
            messagebox.showerror("Restaurar backup", f"Falha ao restaurar backup: {exc}", parent=self)
            return
        messagebox.showinfo(
            "Restaurar backup",
            "Backup restaurado com sucesso.\n\n"
            f"Copia anterior salva em:\n{safety_backup}",
            parent=self,
        )

    def choose_database(self):
        messagebox.showinfo(
            "Banco SQLite",
            "Escolha um arquivo .db existente ou informe um novo nome em uma pasta compartilhada da rede.",
        )
        path = filedialog.asksaveasfilename(
            title="Banco SQLite",
            defaultextension=".db",
            filetypes=[("SQLite", "*.db"), ("Todos", "*.*")],
            initialfile="controle_producao.db",
        )
        if not path:
            return
        self.config_data["db_path"] = path
        save_config(self.config_data)
        messagebox.showinfo("Banco SQLite", "Reabra o sistema para usar o novo banco.")

    def open_users(self):
        if not user_can_admin(self.user):
            messagebox.showwarning("Permissao", "Apenas administradores podem gerenciar usuarios.", parent=self)
            return
        UserDialog(self, self.repo)

    def on_close(self):
        try:
            backup_database(self.config_data, "fechar")
        except Exception:
            pass
        try:
            self.conn.close()
        except Exception:
            pass
        self.destroy()


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


def main():
    try:
        app = MainApp()
        if getattr(app, "ready", False):
            app.mainloop()
    except Exception as exc:
        log_file = BASE_DIR / "app.log"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(f"\n[{now_br()}] Falha ao abrir o sistema\n")
            f.write(traceback.format_exc())
            f.write("\n")
        try:
            messagebox.showerror(
                "Controle de Producao",
                f"Falha ao abrir o sistema:\n{exc}\n\nDetalhes salvos em:\n{log_file}",
            )
        except Exception:
            pass


if __name__ == "__main__":
    main()
