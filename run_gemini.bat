@echo off
REM run_gemini.bat - Gemini CLI launcher with stderr noise filtering
REM All arguments are passed directly to run_gemini_clean.py -> gemini CLI
REM Use --yolo flag directly (no mode keyword needed)
cd /d "%~dp0"

REM Keep Korean output readable in Windows console sessions.
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set PYTHON=.ai_monitor\venv\Scripts\python.exe

if exist "%PYTHON%" (
    "%PYTHON%" scripts\run_gemini_clean.py %*
) else (
    python scripts\run_gemini_clean.py %*
)
