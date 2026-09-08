@echo off
setlocal

cd /d "%~dp0\.."
set DATABASE_URL=
python -m unittest discover -s api/tests -p "test_api_foundation.py" -v
python -m unittest discover -s api/tests -p "test_postgresql_readiness.py" -v
