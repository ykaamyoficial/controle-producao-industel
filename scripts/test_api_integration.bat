@echo off
setlocal

cd /d "%~dp0\.."

echo Aviso: o runtime oficial de integracao agora e Docker.
echo Preferir: scripts\run_api_integration_tests.bat

if not "%APP_ENV%"=="test" (
  echo Defina APP_ENV=test para executar testes de integracao PostgreSQL.
  exit /b 1
)

if "%POSTGRES_TEST_DATABASE_URL%"=="" (
  echo Defina POSTGRES_TEST_DATABASE_URL apontando para um banco PostgreSQL de testes.
  exit /b 1
)

python -m unittest discover -s api/tests -p "test_postgresql_integration.py" -v
