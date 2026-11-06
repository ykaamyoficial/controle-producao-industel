@echo off
setlocal EnableExtensions

rem Publica a API usando um tunel nomeado Cloudflare (endereco fixo).
rem Defina CLOUDFLARE_TUNNEL_TOKEN somente nesta sessao ou em um .env local.

cd /d "%~dp0.."

if "%CLOUDFLARE_TUNNEL_TOKEN%"=="" (
  echo ERRO: defina CLOUDFLARE_TUNNEL_TOKEN antes de executar.
  echo Exemplo: set CLOUDFLARE_TUNNEL_TOKEN=seu-token-do-cloudflare
  exit /b 1
)

where cloudflared >nul 2>nul
if errorlevel 1 (
  echo ERRO: cloudflared nao foi encontrado no PATH.
  exit /b 1
)

docker compose -f docker-compose.dev.yml up -d api
if errorlevel 1 exit /b 1

echo Iniciando tunel nomeado para http://127.0.0.1:8001
cloudflared tunnel --no-autoupdate run --token "%CLOUDFLARE_TUNNEL_TOKEN%"

