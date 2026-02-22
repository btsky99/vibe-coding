@echo off
title [Vibe Coding] Dashboard Server
cd /d "D:\vibe-coding"
echo [바이브코딩] 최신 소스 코드를 실행합니다...
python .ai_monitor/server.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ 서버 실행 중 오류가 발생했습니다! (코드를 확인해 주세요)
    pause
)
