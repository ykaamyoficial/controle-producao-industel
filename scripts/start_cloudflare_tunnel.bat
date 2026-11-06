@echo off
setlocal EnableExtensions

rem Publica a API de desenvolvimento local pela Cloudflare.
rem Requisito: cloudflared.exe instalado e disponivel no PATH.
rem O endereco exibido e temporario; para um endereco fixo, use
rem CLOUDFLARE_TUNNEL_TOKEN com scripts\start_cloudflare_named_tunnel.bat.

cd /d "%~dp0.."

where cloudflared >nul 2>nul
if errorlevel 1 (
  echo ERRO: cloudflared nao foi encontrado no PATH.
  echo Instale pelo guia: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
  exit /b 1
)

docker compose -f docker-compose.dev.yml up -d api
if errorlevel 1 exit /b 1

echo.
echo Iniciando tunel temporario para http://127.0.0.1:8001
echo Copie a URL https://*.trycloudflare.com exibida abaixo para o programa de teste.
echo Mantenha esta janela aberta enquanto os outros computadores estiverem usando a API.
echo.
cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8001

