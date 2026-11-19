"""Auditoria 06 (B2, B4, C3, C9) e 02 (T5): o compose de producao repassa as flags
com default DESLIGADO, monta volume para o estado gravavel da API e o default do
codigo dessas flags continua desligado. Leitura de texto (sem Docker, sem PyYAML)."""

from __future__ import annotations

import re
from pathlib import Path

from api.app.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]
PROD = ROOT / "docker-compose.prod.yml"


def _text() -> str:
    return "\n".join(l for l in PROD.read_text(encoding="utf-8").splitlines() if not l.strip().startswith("#"))


def _env(name: str) -> str | None:
    m = re.search(rf"^\s+{name}:\s*(.*)$", _text(), re.M)
    return m.group(1).strip() if m else None


def test_flags_repassadas_com_default_desligado():
    assert _env("REMANAGEMENT_BY_ROWS_ENABLED") == "${REMANAGEMENT_BY_ROWS_ENABLED:-false}"
    assert _env("CLIENT_VERSION_ENFORCEMENT_ENABLED") == "${CLIENT_VERSION_ENFORCEMENT_ENABLED:-false}"
    assert _env("ALMOX_INTEGRATION_SECRET") == "${ALMOX_INTEGRATION_SECRET:-}"
    assert _env("ALMOX_WEBHOOK_URL") == "${ALMOX_WEBHOOK_URL:-}"
    assert _env("PASSWORD_MIN_LENGTH") == "${PASSWORD_MIN_LENGTH:-10}"


def test_diretorios_de_estado_ficam_no_volume_api_data():
    for var, sub in (("CHAT_STORAGE_ROOT", "storage"), ("AUDIT_SPOOL_DIR", "audit_spool"), ("MAINTENANCE_STATE_DIR", "system_state")):
        assert _env(var) == f"${{{var}:-/app/data/{sub}}}"
    assert re.search(r"^\s+- api_data:/app/data\s*$", _text(), re.M)
    assert re.search(r"^volumes:\n(?:\s+\w+:\n)*\s+api_data:", _text(), re.M)
    # volume antigo preservado
    assert "update_repository_data:/var/lib/controle-producao/updates" in _text()


def test_caddy_so_sobe_com_perfil():
    bloco = _text().split("\n  caddy:\n", 1)[1].split("\nvolumes:\n", 1)[0]
    assert re.search(r'^\s+profiles:\s*\["caddy"\]', bloco, re.M)


def test_defaults_do_codigo_para_flags_e_almox_sao_desligados():
    campos = Settings.model_fields
    assert campos["remanagement_by_rows_enabled"].default is False
    assert campos["client_version_enforcement_enabled"].default is False
    # sem segredo a conciliacao do Almox+ responde 503; sem URL nenhum webhook sai
    assert campos["almox_integration_secret"].default == ""
    assert campos["almox_webhook_url"].default == ""
