@echo off
rem Recuperacao de emergencia da atualizacao do Controle de Producao Industel.
rem Encerra o programa, o agente de bandeja (--notifier) e o Updater e, se um
rem instalador for informado, abre-o em seguida.
rem
rem Uso (como administrador):
rem   recuperar_atualizacao.bat "C:\caminho\ControleProducaoSetup-X.Y.Z.exe"
rem
rem Dados do usuario ficam em %ProgramData%\Industel\ControleProducao e nao sao tocados.

net session >nul 2>&1
if errorlevel 1 (
    echo Execute este arquivo como administrador ^(botao direito ^> Executar como administrador^).
    pause
    exit /b 1
)

echo Encerrando processos do Controle de Producao...
taskkill /F /T /IM ControleProducao.exe >nul 2>&1
taskkill /F /T /IM ControleProducaoApp.exe >nul 2>&1
taskkill /F /T /IM Updater.exe >nul 2>&1
timeout /t 2 /nobreak >nul

if "%~1"=="" (
    echo Processos encerrados. Informe o caminho do instalador para continuar a instalacao.
    pause
    exit /b 0
)

if not exist "%~1" (
    echo Instalador nao encontrado: %~1
    pause
    exit /b 1
)

echo Abrindo o instalador...
start "" "%~1"
exit /b 0
