@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo  Gerador do EXE pelo setup.py
echo ==========================================
echo.

set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3.11"
) else (
    set "PYTHON_ARGS="
)

echo Instalando dependencias...
"%PYTHON_EXE%" %PYTHON_ARGS% -m pip install --upgrade pip
"%PYTHON_EXE%" %PYTHON_ARGS% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERRO ao instalar dependencias.
    pause
    exit /b 1
)

echo.
echo Gerando executavel pelo setup.py...
"%PYTHON_EXE%" %PYTHON_ARGS% -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --name "Controle Producao Industel Telecom" ^
    --icon "app\assets\images\Logo_Industel_Icone.ico" ^
    --add-data "app\assets;app\assets" ^
    --add-data "app\config;app\config" ^
    --add-data "app\data;app\data" ^
    setup.py
if errorlevel 1 (
    echo.
    echo ERRO ao gerar executavel.
    pause
    exit /b 1
)

echo.
echo Executavel gerado em:
echo dist\Controle Producao Industel Telecom
echo.
pause
