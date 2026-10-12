@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1/3] Creating Python virtual environment...
if not exist .venv\Scripts\python.exe python -m venv .venv
echo [2/3] Installing PyTorch (CUDA 12.8)...
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
echo [3/3] Installing other packages...
.venv\Scripts\python.exe -m pip install -r requirements.txt
echo Done.
pause
