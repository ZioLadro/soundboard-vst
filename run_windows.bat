@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creo l'ambiente virtuale...
    python -m venv .venv || (echo Python non trovato: installalo da python.org & pause & exit /b 1)
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (pause & exit /b 1)
)

set PYTHONPATH=%~dp0src
start "" ".venv\Scripts\pythonw.exe" -m soundboard_vst
