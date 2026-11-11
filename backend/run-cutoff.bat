@echo off
rem Auto-checkout: closes punches that were left open. Runs from any folder.
cd /d "%~dp0"
set "PY=python"
if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"
echo [%date% %time%] start >> cutoff.log
"%PY%" manage.py attendance-cutoff >> cutoff.log 2>&1
echo [%date% %time%] done >> cutoff.log
