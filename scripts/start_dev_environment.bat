@echo off
setlocal

cd /d "%~dp0\.."
call "%~dp0load_dev_env.bat"

if "%POSTGRES_PASSWORD%"=="" (
  echo Defina POSTGRES_PASSWORD no ambiente local antes de iniciar o ambiente de desenvolvimento.
  exit /b 1
)
if "%SECRET_KEY%"=="" (
  echo Defina SECRET_KEY com pelo menos 32 caracteres antes de iniciar a API.
  exit /b 1
)

docker compose -f docker-compose.dev.yml up -d --build postgres api
