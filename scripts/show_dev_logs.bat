@echo off
setlocal

cd /d "%~dp0\.."
call "%~dp0load_dev_env.bat"
docker compose -f docker-compose.dev.yml logs --tail=200 api postgres
