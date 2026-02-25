@echo off
setlocal
echo ==========================================
echo   Gemini CLI & MCP 환경 자동 복구 도구
echo ==========================================

echo [1/4] 충돌 프로세스(Node.js) 정리 중...
taskkill /f /im node.exe >nul 2>&1

echo [2/4] 기존 Gemini CLI 제거 및 캐시 정리...
call npm uninstall -g @google/gemini-cli
call npm cache clean --force

echo [3/4] 최신 버전 깨끗하게 재설치...
call npm install -g @google/gemini-cli

echo [4/4] MCP 서버 설정 초기화 체크...
if exist "%USERPROFILE%\.gemini\config.json" (
    echo 기존 설정 보존됨.
)

echo.
echo ==========================================
echo   복구가 완료되었습니다! 이제 다시 실행해 보세요.
echo ==========================================
pause
