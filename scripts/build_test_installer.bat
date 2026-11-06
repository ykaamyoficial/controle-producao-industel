@echo off
rem Gera release\teste\ControleProducaoTesteSetup-<versao>.exe (edicao de teste, API dev 8001).
setlocal
cd /d "%~dp0.."
set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" scripts\build_test_installer.py
exit /b %ERRORLEVEL%
