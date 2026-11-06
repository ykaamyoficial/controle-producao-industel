"""Edicao do programa: "producao" (padrao, identica ao comportamento original)
ou "teste" (instalavel em paralelo ao oficial, sem nenhum recurso compartilhado).

Fonte da edicao: variavel CONTROLE_PRODUCAO_EDITION ou, no build de teste, o
arquivo empacotado app/config/edition.json ({"edition": "teste"}). Sem nenhum
dos dois, e producao. So stdlib: o launcher e o Updater tambem importam isto."""

from __future__ import annotations

import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

EDITION_ENV = "CONTROLE_PRODUCAO_EDITION"
EDITION_FILE_NAME = "edition.json"
# Endereco publico da API de desenvolvimento usado pelo instalador de teste.
TEST_API_BASE_URL = "https://producaodev.ykora.com.br"
OFFICIAL_API_PORT = 8000
TEST_SUFFIX = "Teste"


@lru_cache(maxsize=1)
def _edition_from_file() -> str:
    roots = [Path(__file__).resolve().parent]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.insert(0, Path(meipass) / "app")
    for root in roots:
        path = root / "config" / EDITION_FILE_NAME
        try:
            return str(json.loads(path.read_text(encoding="utf-8")).get("edition") or "").strip().lower()
        except (OSError, ValueError, AttributeError):
            continue
    return ""


def is_test() -> bool:
    return (os.environ.get(EDITION_ENV) or _edition_from_file() or "").strip().lower() == "teste"


def _s() -> str:
    """Sufixo de identificadores (sem espacos) da edicao atual."""
    return TEST_SUFFIX if is_test() else ""


def display_suffix() -> str:
    return " TESTE" if is_test() else ""


# --- nomes exibidos
def app_name() -> str:
    return "Controle de Producao Industel" + display_suffix()


def display_name() -> str:
    return "Controle de Produção Industel" + (" [TESTE]" if is_test() else "")


def test_banner_text(base_url: str | None = None) -> str:
    parsed = urlparse(base_url or TEST_API_BASE_URL)
    try:
        port = parsed.port
    except ValueError:
        port = None
    host = parsed.hostname or "?"
    return f"AMBIENTE DE TESTE · API dev {host}:{port}" if port else f"AMBIENTE DE TESTE · API dev {host}"


# --- executaveis (raiz = launcher, App, Updater)
def launcher_exe_name() -> str:
    return f"ControleProducao{_s()}.exe"


def app_exe_name() -> str:
    return f"ControleProducao{_s()}App.exe"


def updater_exe_name() -> str:
    return f"Updater{_s()}.exe"


# --- pastas (ProgramData, %APPDATA%, %LOCALAPPDATA%, cache do chat)
def data_dir_name() -> str:
    return f"ControleProducao{_s()}"


def chat_cache_dir_name() -> str:
    return f"ControleProducaoIndustel{_s()}"


def default_install_dir() -> str:
    return r"C:\Program Files\Industel\Controle de Producao" + display_suffix()


# --- identidade no Windows
def main_app_mutex_name() -> str:
    return f"Global\\ControleProducaoIndustel{_s()}_MainAppRunning"


def notifier_mutex_name() -> str:
    return f"Global\\ControleProducaoIndustel{_s()}_NotifierInstance"


def toast_app_id() -> str:
    return app_name()


def startup_run_value_name() -> str:
    return f"ControleProducaoIndustel{_s()}Notificacoes"


def app_user_model_id() -> str:
    return f"Industel.ControleProducao{_s()}.2"


# --- comportamento
def updates_enabled() -> bool:
    return not is_test()


def check_test_api_url(url: str) -> None:
    """Na edicao de teste a API oficial (porta 8000) nunca e aceita. Levanta ValueError."""
    try:
        port = urlparse(url).port
    except ValueError:
        raise ValueError("Endereco da API invalido: porta incorreta.") from None
    if port == OFFICIAL_API_PORT:
        raise ValueError(
            f"A edicao de teste nao pode usar a API oficial (porta {OFFICIAL_API_PORT}). "
            "Use a API de dev, por exemplo https://producaodev.ykora.com.br."
        )
