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

_TMP_AUDIT_SPOOL_DIR = tempfile.mkdtemp(prefix="audit-spool-tests-")
os.environ["AUDIT_SPOOL_DIR"] = _TMP_AUDIT_SPOOL_DIR


def pytest_configure(config) -> None:
    os.environ["AUDIT_SPOOL_DIR"] = _TMP_AUDIT_SPOOL_DIR
    from api.app.core.config import get_settings

    get_settings.cache_clear()


@atexit.register
def _cleanup_audit_spool_dir() -> None:
    shutil.rmtree(_TMP_AUDIT_SPOOL_DIR, ignore_errors=True)
