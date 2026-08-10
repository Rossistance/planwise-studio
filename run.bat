@echo off
REM PlanWise launcher. Creates the venv on first run, then serves on 8771.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv || goto :nopython
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -r requirements.txt
)

start "" http://127.0.0.1:8771
.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8771
goto :eof

:nopython
echo.
echo Python 3 was not found on PATH. Install it from https://python.org and re-run.
pause
