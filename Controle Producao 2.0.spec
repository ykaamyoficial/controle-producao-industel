# -*- mode: python ; coding: utf-8 -*-
# ATENCAO (Fase 07 - Instalador e Atualizacao): o spec oficial usado pelo
# instalador (installer\ControleProducao.iss) e pelo Updater (app.updater,
# ver docs\architecture\UPDATER_DESKTOP.md) e "ControleProducao.spec", nao
# este arquivo. Este .spec gera um executavel com outro nome
# ("Controle Producao 2.0.exe") e nao foi conferido quanto a paridade de
# hiddenimports/datas com o spec oficial -- nao usar para gerar uma release
# distribuida sem antes comparar os dois specs.
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['hmac', 'hashlib', 'secrets', 'json', 'sqlite3', 'datetime', 'pathlib', 'shutil']
hiddenimports += collect_submodules('PySide6.QtWidgets')
hiddenimports += collect_submodules('PySide6.QtCore')
hiddenimports += collect_submodules('PySide6.QtGui')
# ETAPA 7: app/ui/chat_realtime.py usa QtNetwork (QNetworkRequest) e
# QtWebSockets (QWebSocket) pro canal realtime — sem isso aqui o .exe
# gerado por este spec (o que gerar_exe_pyside6.bat realmente usa) fica
# sem esses modulos e o WebSocket nao funciona no build empacotado.
hiddenimports += collect_submodules('PySide6.QtNetwork')
hiddenimports += collect_submodules('PySide6.QtWebSockets')


a = Analysis(
    ['app\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('app\\data', 'app\\data'), ('app\\config', 'app\\config'), ('app\\assets', 'app\\assets'), ('app\\migrations', 'app\\migrations')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Controle Producao 2.0',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app\\assets\\images\\Logo_Industel_Icone.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Controle Producao 2.0',
)
