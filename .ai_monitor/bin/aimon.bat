@echo off
REM AI ?�업 모니???��???뷰어 ?�행 ?�크립트 (Windows??
set "AI_MONITOR_DIR=%~dp0.."
set "PYTHON_BIN=%AI_MONITOR_DIR%\venv\Scripts\python.exe"
set "VIEWER_SCRIPT=%AI_MONITOR_DIR%\src\view.py"

if not exist "%PYTHON_BIN%" (
    echo Error: Virtual environment not found at %PYTHON_BIN%
    pause
    exit /b 1
)

"%PYTHON_BIN%" "%VIEWER_SCRIPT%"

