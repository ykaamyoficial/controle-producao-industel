@echo off
setlocal

cd /d "%~dp0\.."
call "%~dp0load_dev_env.bat"
if errorlevel 1 exit /b 1
docker compose -f docker-compose.dev.yml up -d --build postgres api
