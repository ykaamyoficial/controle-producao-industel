# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

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
certifi_datas = collect_data_files('certifi')

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
        ('app\\assets', 'app\\assets'),
        ('app\\migrations', 'app\\migrations'),
        ('app\\config\\controle_producao_config.example.json', 'app\\config'),
    ] + certifi_datas,
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
    name='ControleProducaoApp',
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
    name='ControleProducao',
)
