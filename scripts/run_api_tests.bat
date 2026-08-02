@echo off
setlocal

cd /d "%~dp0\.."
call "%~dp0load_dev_env.bat"
docker compose -f docker-compose.dev.yml run --rm --no-deps -e DATABASE_URL= -e SECRET_KEY=%SECRET_KEY% api python -m unittest discover -s /app/api/tests -v
