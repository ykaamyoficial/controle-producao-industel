# -*- mode: python ; coding: utf-8 -*-
# Launcher do layout versionado: vira ControleProducao.exe na raiz da
# instalacao (o exe real do app e ControleProducaoApp.exe em versions/<v>/).
# Sem UI, sem rede -- so stdlib + app.updater.versions. Onefile NAO: onefile
# descompacta em %TEMP% a cada abertura (lento e mais sujeito a antivirus).

import os
# Edicao de teste (scripts/build_test_installer.py): variaveis de ambiente
# trocam nomes, assets e embutem app/config/edition.json. Sem elas o build e
# o oficial, identico ao de sempre.
_EDITION = os.environ.get('CONTROLE_PRODUCAO_EDITION', '').strip().lower()
_S = 'Teste' if _EDITION == 'teste' else ''
_EDITION_FILE = os.environ.get('CONTROLE_PRODUCAO_EDITION_FILE', '')
_EXTRA_DATAS = [(_EDITION_FILE, 'app\\config')] if _EDITION_FILE else []
_ASSETS = os.environ.get('CONTROLE_PRODUCAO_ASSETS_DIR', 'app/assets')

a = Analysis(
    ['app/launcher/launcher.py'],
    pathex=[],
    binaries=[],
    datas=_EXTRA_DATAS,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6', 'httpx', 'httpcore', 'pdfplumber', 'pdfminer', 'PIL', 'fastapi', 'uvicorn', 'sqlalchemy',
              'asyncpg', 'alembic', 'tkinter', 'unittest', 'email', 'http', 'xml', 'pydoc'],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ControleProducao' + _S,
    icon=os.path.join(_ASSETS, 'images', 'Logo_Industel_Icone.ico'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
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
    name='Launcher',
)
