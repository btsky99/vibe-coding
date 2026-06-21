@echo off
setlocal

chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem FILE: claude.cmd
rem DESCRIPTION: 프로젝트 로컬 Claude 실행기. 글로벌 claude가 없을 때 %USERPROFILE%\.local\bin\claude.exe도 탐색하도록 경로 추가.
rem REVISION HISTORY:
rem - 2026-06-21 Claude: %USERPROFILE%\.local\bin\claude.exe 경로 추가 및 헤더 필수 필드 추가

set "CLAUDECODE="
set "CLAUDE_CODE_ENTRYPOINT="
set "CLAUDE_CODE_SSE_PORT="

set "CLAUDE_GLOBAL=%AppData%\npm\claude-original.cmd"
if not exist "%CLAUDE_GLOBAL%" set "CLAUDE_GLOBAL=%AppData%\npm\claude.cmd"
if not exist "%CLAUDE_GLOBAL%" set "CLAUDE_GLOBAL=%USERPROFILE%\.local\bin\claude.exe"

if not exist "%CLAUDE_GLOBAL%" (
  echo [error] Global Claude CLI not found at "%AppData%\npm" or "%USERPROFILE%\.local\bin".
  echo Install Claude Code globally or run: python scripts\agent_launcher.py claude yolo
  exit /b 1
)

call "%CLAUDE_GLOBAL%" %*
exit /b %errorlevel%
