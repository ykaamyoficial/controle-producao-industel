@echo off
rem ATENCAO (Fase 07 - Instalador e Atualizacao): este script gera o build a
rem partir de "Controle Producao 2.0.spec", que NAO e o spec oficial usado
rem pelo instalador/Updater (esse e "ControleProducao.spec" -- ver
rem docs\architecture\UPDATER_DESKTOP.md). Para gerar um instalador oficial,
rem use "py -m PyInstaller ControleProducao.spec --clean --noconfirm".
cd /d "%~dp0"
set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
set "PYTHON_ARGS="
if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3.11"
)
echo ==========================================
echo  Gerador do executavel - Controle Producao 2.0
echo ==========================================
echo.
echo Instalando dependencias...
"%PYTHON_EXE%" %PYTHON_ARGS% -m pip install --upgrade pip
"%PYTHON_EXE%" %PYTHON_ARGS% -m pip install -r requirements.txt
echo.
echo Limpando geracao anterior...
if exist "dist\Controle Producao 2.0" rmdir /s /q "dist\Controle Producao 2.0"
if exist "build\Controle Producao 2.0" rmdir /s /q "build\Controle Producao 2.0"
echo.
echo Gerando executavel...
"%PYTHON_EXE%" %PYTHON_ARGS% -m PyInstaller "Controle Producao 2.0.spec" --noconfirm --clean
echo.
if exist "dist\Controle Producao 2.0\Controle Producao 2.0.exe" (
    echo Executavel gerado em:
    echo dist\Controle Producao 2.0\Controle Producao 2.0.exe
) else (
    echo Nao foi possivel localizar o executavel gerado.
)
echo.
pause
