@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if "%~1"=="" (
  echo Drag and drop video file^(s^) onto this .bat file.
  pause
  exit /b
)
if not exist .venv\Scripts\python.exe call install.bat
.venv\Scripts\python.exe main.py %*
echo.
echo Results are in the "output" folder.
start "" "%~dp0output"
pause
