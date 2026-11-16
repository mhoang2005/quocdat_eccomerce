@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [QuocDat Marketplace] Creating Python environment...
  python -m venv .venv
)

".venv\Scripts\python.exe" -c "import flask, pyodbc" >nul 2>&1
if errorlevel 1 (
  echo [QuocDat Marketplace] Installing dependencies...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

if /I "%QUOCDAT_DB_BACKEND%"=="sqlite" (
  if not exist "instance\oltp.db" ".venv\Scripts\python.exe" -m flask --app run:app init-system
) else (
  ".venv\Scripts\python.exe" -m flask --app run:app db-status
  if errorlevel 1 (
    echo [QuocDat Marketplace] Check the SQL Server connection and the migration instructions in docs\SQL_SERVER.md.
    pause
    exit /b 1
  )
)

echo [QuocDat Marketplace] Opening http://127.0.0.1:5000
start "" powershell.exe -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:5000'"
".venv\Scripts\python.exe" run.py

endlocal
