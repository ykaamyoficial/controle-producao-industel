@echo off
setlocal

cd /d "%~dp0\.."
call "%~dp0load_dev_env.bat"

if "%SECRET_KEY%"=="" (
  echo Defina SECRET_KEY com pelo menos 32 caracteres antes de criar o administrador.
  echo Exemplo: set SECRET_KEY=sua-chave-local-grande-e-segura
  exit /b 1
)

if "%API_BOOTSTRAP_USERNAME%"=="" set "API_BOOTSTRAP_USERNAME=admin"
if "%API_BOOTSTRAP_DISPLAY_NAME%"=="" set "API_BOOTSTRAP_DISPLAY_NAME=Administrador"
if "%API_BOOTSTRAP_PASSWORD%"=="" set "API_BOOTSTRAP_PASSWORD=admin12345"

docker compose -f docker-compose.dev.yml run --rm ^
  -e API_BOOTSTRAP_USERNAME ^
  -e API_BOOTSTRAP_DISPLAY_NAME ^
  -e API_BOOTSTRAP_PASSWORD ^
  api python -m api.app.cli create-admin

if errorlevel 2 exit /b %errorlevel%
if errorlevel 1 (
  echo Administrador ativo ja existe. Ambiente confirmado.
  exit /b 0
)
