@echo off
REM PlanWise Outlook companion — runs on YOUR PC, drafts into YOUR Outlook.
setlocal
cd /d "%~dp0.."
.venv\Scripts\python.exe -m uvicorn companion.companion:app --host 127.0.0.1 --port 8772
