@echo off
rem Valores locais apenas para o ambiente de desenvolvimento Docker.
rem Se a variavel ja existir no Windows, ela sera preservada.

if "%POSTGRES_DB%"=="" set "POSTGRES_DB=controle_producao_dev"
if "%POSTGRES_USER%"=="" set "POSTGRES_USER=controle_dev"
if "%POSTGRES_PASSWORD%"=="" set "POSTGRES_PASSWORD=controle_dev"
if "%POSTGRES_PORT%"=="" set "POSTGRES_PORT=55432"
if "%API_PORT%"=="" set "API_PORT=8000"
if "%SECRET_KEY%"=="" set "SECRET_KEY=controle-producao-api-dev-secret-key-2026"
if "%PROVISIONING_SECRET%"=="" set "PROVISIONING_SECRET=dev-provisioning-secret-change-me-32chars"
if "%OPERATIONAL_COMPANY_CODE%"=="" set "OPERATIONAL_COMPANY_CODE=local-dev"
if "%OPERATIONAL_COMPANY_NAME%"=="" set "OPERATIONAL_COMPANY_NAME=Empresa Local"
if "%OPERATIONAL_ENVIRONMENT_TYPE%"=="" set "OPERATIONAL_ENVIRONMENT_TYPE=production"
