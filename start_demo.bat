@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [QuocDat Marketplace] Creating Python environment...
  python -m venv .venv
)

".venv\Scripts\python.exe" -c "import flask" >nul 2>&1
if errorlevel 1 (
  echo [QuocDat Marketplace] Installing dependencies...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

set "NEED_INIT=0"
if not exist "instance\oltp.db" set "NEED_INIT=1"
if not exist "instance\staging.db" set "NEED_INIT=1"
if not exist "instance\dwh.db" set "NEED_INIT=1"
if "%NEED_INIT%"=="1" (
  echo [QuocDat Marketplace] Initializing OLTP, Staging, and DWH...
  ".venv\Scripts\python.exe" -m flask --app run:app init-system
)

echo [QuocDat Marketplace] Opening http://127.0.0.1:5000
start "" powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:5000'"
".venv\Scripts\python.exe" run.py

endlocal
