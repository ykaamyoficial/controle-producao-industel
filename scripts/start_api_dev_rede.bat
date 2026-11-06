@echo off
rem Sobe a API de dev (porta 8001) ACESSIVEL PELA REDE LOCAL, para testar o programa de teste
rem em outro computador. Use so em rede confiavel: a dev tem senhas/chaves de desenvolvimento.
rem Antes, libere a porta no firewall (PowerShell como administrador):
rem   New-NetFirewallRule -DisplayName "Controle Producao API dev 8001" -Direction Inbound -Protocol TCP -LocalPort 8001 -Action Allow -Profile Private -RemoteAddress LocalSubnet
setlocal

cd /d "%~dp0\.."
call "%~dp0load_dev_env.bat"
set "API_PORT=8001"
set "API_BIND=0.0.0.0"
docker compose -f docker-compose.dev.yml up -d api
echo.
echo API de dev na rede: http://ENDERECO-DESTE-COMPUTADOR:8001
echo Descubra o endereco com: ipconfig  (linha "Endereco IPv4")
