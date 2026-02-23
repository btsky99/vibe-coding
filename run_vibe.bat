@echo off
title [바이브 코딩 v2.3.0] Dashboard Server
cd /d "%~dp0"
echo [바이브코딩] 최신 소스 코드를 실행합니다...
echo.

:: 파이썬 실행 확인
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ 파이썬(Python)이 설치되어 있지 않거나 PATH가 설정되지 않았습니다.
    pause
    exit /b
)

:: 서버 실행
python .ai_monitor/server.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ 서버 실행 중 오류가 발생했습니다! (위 에러 내용을 확인해 주세요)
    pause
)
pause
