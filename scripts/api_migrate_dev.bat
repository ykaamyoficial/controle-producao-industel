@echo off
setlocal

cd /d "%~dp0\.."
call "%~dp0run_api_migrations.bat"
