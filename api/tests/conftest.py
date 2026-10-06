"""Configuracao compartilhada da suite de testes da API.

Fase 16: maintenance/channels/updates/deployment agora emitem eventos de
auditoria (api.app.audit.service.record_event) a cada operacao real. Sem
isolar AUDIT_SPOOL_DIR aqui, qualquer teste que exercite esses servicos
gravaria arquivos no data/audit_spool/ real do repositorio -- mesma
categoria de problema que MAINTENANCE_STATE_DIR/UPDATE_REPOSITORY_DIR ja
evitam nos testes individuais. Isolado uma unica vez, no nivel da sessao,
em vez de em cada arquivo de teste.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest

# O timeout global (pytest.ini, 25 s) protege a suite do Desktop contra um
# QMessageBox real travado. Na API ele e curto: os testes de concorrencia com
# PostgreSQL real levam 6-12 s isolados e passam de 25 s no meio da suite.
API_TEST_TIMEOUT_SECONDS = 120
_API_TESTS_DIR = Path(__file__).resolve().parent

_TMP_AUDIT_SPOOL_DIR = tempfile.mkdtemp(prefix="audit-spool-tests-")
os.environ["AUDIT_SPOOL_DIR"] = _TMP_AUDIT_SPOOL_DIR


def pytest_configure(config) -> None:
    os.environ["AUDIT_SPOOL_DIR"] = _TMP_AUDIT_SPOOL_DIR
    from api.app.core.config import get_settings

    get_settings.cache_clear()


@atexit.register
def _cleanup_audit_spool_dir() -> None:
    shutil.rmtree(_TMP_AUDIT_SPOOL_DIR, ignore_errors=True)


def pytest_collection_modifyitems(config, items) -> None:
    for item in items:
        if _API_TESTS_DIR in Path(str(item.fspath)).resolve().parents and item.get_closest_marker("timeout") is None:
            item.add_marker(pytest.mark.timeout(API_TEST_TIMEOUT_SECONDS))
