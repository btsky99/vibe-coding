@echo off
cd /d "%~dp0"
set PYTHON=.ai_monitor\venv\Scripts\python.exe

set MODE=%~1

if /I "%MODE%"=="normal" shift
if /I "%MODE%"=="yolo" goto launch_yolo
goto launch_normal

:launch_normal
if exist "%PYTHON%" (
    "%PYTHON%" scripts\run_gemini_clean.py %*
) else (
    python scripts\run_gemini_clean.py %*
)
goto :eof

:launch_yolo
shift
if exist "%PYTHON%" (
    "%PYTHON%" scripts\run_gemini_clean.py --yolo %*
) else (
    python scripts\run_gemini_clean.py --yolo %*
)
