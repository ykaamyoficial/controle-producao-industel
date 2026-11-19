@echo off
setlocal

cd /d "%~dp0\.."
call "%~dp0load_dev_env.bat"
if errorlevel 1 exit /b 1

if "%POSTGRES_PASSWORD%"=="" (
  echo Defina POSTGRES_PASSWORD no ambiente local antes de iniciar o PostgreSQL de desenvolvimento.
  exit /b 1
)

docker compose -f docker-compose.dev.yml up -d postgres
