@echo off
setlocal

cd /d "%~dp0\.."
call "%~dp0load_dev_env.bat"

if "%POSTGRES_PASSWORD%"=="" (
  echo Defina POSTGRES_PASSWORD no ambiente local antes de executar testes de integracao.
  exit /b 1
)
if "%POSTGRES_TEST_DB%"=="" set POSTGRES_TEST_DB=controle_producao_test

echo %POSTGRES_TEST_DB% | findstr /I "test" >nul
if errorlevel 1 (
  echo Recusado: POSTGRES_TEST_DB precisa conter "test" no nome.
  exit /b 1
)

echo Recriando banco de testes %POSTGRES_TEST_DB%...
docker compose -f docker-compose.dev.yml exec -T postgres sh -c "PGPASSWORD='%POSTGRES_PASSWORD%' dropdb -U '%POSTGRES_USER%' --if-exists '%POSTGRES_TEST_DB%' --force"
if errorlevel 1 exit /b 1
docker compose -f docker-compose.dev.yml exec -T postgres sh -c "PGPASSWORD='%POSTGRES_PASSWORD%' createdb -U '%POSTGRES_USER%' '%POSTGRES_TEST_DB%'"
if errorlevel 1 exit /b 1

docker compose -f docker-compose.dev.yml run --rm --no-deps -e APP_ENV=test -e SECRET_KEY=%SECRET_KEY% -e POSTGRES_TEST_DATABASE_URL=postgresql+asyncpg://%POSTGRES_USER%:%POSTGRES_PASSWORD%@postgres:5432/%POSTGRES_TEST_DB% api python -m unittest discover -s /app/api/tests -p "test_*integration*.py" -v
