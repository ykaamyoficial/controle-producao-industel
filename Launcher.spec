# -*- mode: python ; coding: utf-8 -*-
# Launcher do layout versionado: vira ControleProducao.exe na raiz da
# instalacao (o exe real do app e ControleProducaoApp.exe em versions/<v>/).
# Sem UI, sem rede -- so stdlib + app.updater.versions. Onefile NAO: onefile
# descompacta em %TEMP% a cada abertura (lento e mais sujeito a antivirus).

a = Analysis(
    ['app\launcher\launcher.py'],
    pathex=[],
    binaries=[],
    datas=[],
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
    name='ControleProducao',
    icon='app\assets\images\Logo_Industel_Icone.ico',
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
