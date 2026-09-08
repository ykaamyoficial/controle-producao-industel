@echo off
setlocal

if "%~1"=="" (
  echo Uso:
  echo   scripts\provision_company_environment.bat CODIGO_EMPRESA "Nome da Empresa" PORTA_API PORTA_POSTGRES
  echo.
  echo Exemplo:
  echo   scripts\provision_company_environment.bat empresa01 "Empresa 01" 8010 55440
  exit /b 1
)

if "%~2"=="" (
  echo Informe o nome da empresa.
  exit /b 1
)

set "COMPANY_CODE=%~1"
set "COMPANY_NAME=%~2"
set "API_PORT=%~3"
set "POSTGRES_PORT=%~4"

if "%API_PORT%"=="" set "API_PORT=8000"
if "%POSTGRES_PORT%"=="" set "POSTGRES_PORT=55432"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0provision_company_environment.ps1" -CompanyCode "%COMPANY_CODE%" -CompanyName "%COMPANY_NAME%" -ApiPort %API_PORT% -PostgresPort %POSTGRES_PORT%
