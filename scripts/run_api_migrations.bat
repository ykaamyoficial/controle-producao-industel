@echo off
setlocal

cd /d "%~dp0\.."
call "%~dp0load_dev_env.bat"

if "%POSTGRES_PASSWORD%"=="" (
  echo Defina POSTGRES_PASSWORD no ambiente local antes de executar migrations.
  exit /b 1
)
docker compose -f docker-compose.dev.yml run --rm --no-deps api sh -c "cd /app/api && python -m alembic upgrade head"
