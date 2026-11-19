@echo off
rem Destrava a atualizacao em PC na 2.9.0 (nao precisa de administrador). Ver destravar_atualizacao_2_10.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0destravar_atualizacao_2_10.ps1" %*
echo.
pause
