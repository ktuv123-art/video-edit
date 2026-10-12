@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set HF_HUB_DISABLE_TELEMETRY=1
if not exist .venv\Scripts\python.exe call install.bat
echo Opening the web UI in your browser... (close this window to stop)
.venv\Scripts\python.exe app.py
pause
