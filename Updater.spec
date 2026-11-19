# -*- mode: python ; coding: utf-8 -*-
# Fase 10: Updater do Desktop, executavel SEPARADO do Desktop principal
# (ControleProducao.spec). Console (sem UI grafica nesta fase -- Secao 28),
# so depende de httpx + stdlib (nao arrasta PySide6/pdfplumber/PIL, que o
# Desktop principal precisa mas o Updater nao usa).
#
# Build verificado (2026-10-08, ver docs/architecture/UPDATER_DESKTOP.md). Spec
# oficial: faz parte do caminho Updater.spec + ControleProducao.spec + Launcher.spec
# -> ISCC. UPX desligado (como nos demais specs): reduz falso positivo de antivirus.

from PyInstaller.utils.hooks import collect_submodules
import os
# Edicao de teste (scripts/build_test_installer.py): variaveis de ambiente
# trocam nomes, assets e embutem app/config/edition.json. Sem elas o build e
# o oficial, identico ao de sempre.
_EDITION = os.environ.get('CONTROLE_PRODUCAO_EDITION', '').strip().lower()
_S = 'Teste' if _EDITION == 'teste' else ''
_EDITION_FILE = os.environ.get('CONTROLE_PRODUCAO_EDITION_FILE', '')
_EXTRA_DATAS = [(_EDITION_FILE, 'app\\config')] if _EDITION_FILE else []

hiddenimports = ['hashlib', 'json', 'zipfile', 'shutil', 'ctypes']
hiddenimports += collect_submodules('httpx')
hiddenimports += collect_submodules('httpcore')

a = Analysis(
    ['app\\updater\\__main__.py'],
    pathex=[],
    binaries=[],
    datas=_EXTRA_DATAS,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6', 'pdfplumber', 'pdfminer', 'PIL', 'fastapi', 'uvicorn', 'sqlalchemy', 'asyncpg', 'alembic'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Updater' + _S,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Updater' + _S,
)
