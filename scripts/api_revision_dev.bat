@echo off
setlocal

cd /d "%~dp0\.."
call "%~dp0load_dev_env.bat"

docker compose -f docker-compose.dev.yml run --rm --no-deps api sh -c "cd /app/api && python -m alembic current && python -m alembic history"
