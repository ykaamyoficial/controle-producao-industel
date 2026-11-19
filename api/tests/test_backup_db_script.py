"""Auditoria 06 (C1/C2): scripts/servidor/backup_db.ps1 valida o dump, grava sha256, cobre os
volumes e preve copia externa. Nao executa o script: so parseia e confere as etapas."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "servidor" / "backup_db.ps1"


def test_sintaxe_powershell_valida():
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        pytest.skip("PowerShell indisponivel")
    cmd = (
        "$e=$null;$t=$null;"
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}',[ref]$t,[ref]$e);"
        "if($e.Count){$e|%{$_.Message};exit 1}"
    )
    r = subprocess.run([ps, "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_contem_as_etapas_de_validacao_volumes_e_copia_externa():
    s = SCRIPT.read_text(encoding="utf-8")
    for trecho in (
        "pg_restore --list",
        "Get-FileHash",
        ".sha256",
        "$VolumeStorage",
        "$VolumeUpdates",
        "update_repository_data",
        "$DestinoExterno",
        "SEM COPIA EXTERNA",
        "$RetencaoDias",
    ):
        assert trecho in s, trecho


def test_retencao_so_depois_das_etapas_que_podem_falhar():
    s = SCRIPT.read_text(encoding="utf-8")
    ret = s.index("# 5. retencao")
    assert s.index("pg_restore --list") < s.index("Backup-Volume $VolumeUpdates") < s.index("# 4. copia externa") < ret
    assert s.count("Remove-Item") == 1 and s.index("Remove-Item") > ret
    assert s.count("exit 1") >= 1 and s.index("exit 1") < ret
