# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
import os
# Edicao de teste (scripts/build_test_installer.py): variaveis de ambiente
# trocam nomes, assets e embutem app/config/edition.json. Sem elas o build e
# o oficial, identico ao de sempre.
_EDITION = os.environ.get('CONTROLE_PRODUCAO_EDITION', '').strip().lower()
_S = 'Teste' if _EDITION == 'teste' else ''
_EDITION_FILE = os.environ.get('CONTROLE_PRODUCAO_EDITION_FILE', '')
_EXTRA_DATAS = [(_EDITION_FILE, 'app\\config')] if _EDITION_FILE else []
_ASSETS = os.environ.get('CONTROLE_PRODUCAO_ASSETS_DIR', 'app\\assets')

hiddenimports = ['hmac', 'hashlib', 'secrets', 'json', 'sqlite3', 'datetime', 'pathlib', 'shutil']
hiddenimports += collect_submodules('PySide6.QtWidgets')
hiddenimports += collect_submodules('PySide6.QtCore')
hiddenimports += collect_submodules('PySide6.QtGui')
hiddenimports += collect_submodules('PySide6.QtPrintSupport')
hiddenimports += collect_submodules('PySide6.QtNetwork')
hiddenimports += collect_submodules('PySide6.QtWebSockets')
hiddenimports += collect_submodules('pdfplumber')
hiddenimports += collect_submodules('pdfminer')
hiddenimports += collect_submodules('PIL')
hiddenimports += collect_submodules('certifi')
hiddenimports += collect_submodules('openpyxl')
certifi_datas = collect_data_files('certifi')
# Windows nao tem base de fusos: ZoneInfo("America/Sao_Paulo") precisa do pacote tzdata
tzdata_datas = collect_data_files('tzdata')

# Baloes do Windows (windows-toasts -> winrt-*, extensoes nativas). Se algum
# pacote nao estiver instalado no ambiente de build, o app cai no winotify.
from PyInstaller.utils.hooks import collect_all
winrt_binaries = []
for _pkg in ('windows_toasts', 'winrt'):
    try:
        _datas, _bins, _hidden = collect_all(_pkg)
        certifi_datas += _datas
        winrt_binaries += _bins
        hiddenimports += _hidden
    except Exception:
        pass
for _mod in (
    'winrt.runtime', 'winrt.system', 'winrt.windows.foundation', 'winrt.windows.foundation.collections',
    'winrt.windows.ui.notifications', 'winrt.windows.data.xml.dom', 'winotify',
):
    hiddenimports.append(_mod)


a = Analysis(
    ['app\\main.py'],
    pathex=[],
    binaries=winrt_binaries,
    datas=[
        (_ASSETS, 'app\\assets'),
        ('app\\migrations', 'app\\migrations'),
        ('app\\config\\controle_producao_config.example.json', 'app\\config'),
    ] + certifi_datas + tzdata_datas + _EXTRA_DATAS,
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
    # Layout versionado: o exe real e ControleProducaoApp.exe (em versions/<v>/);
    # ControleProducao.exe na raiz da instalacao e o launcher (Launcher.spec).
    name='ControleProducao' + _S + 'App',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # Qt/PySide6 nao deve ser comprimido por UPX: em alguns Windows isso
    # provoca "DLL load failed ... procedimento nao encontrado" ao importar
    # QtWidgets, mesmo com todas as DLLs presentes.
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(_ASSETS, 'images', 'Logo_Industel_Icone.ico')],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ControleProducao' + _S,
)
