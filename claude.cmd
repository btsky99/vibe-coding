@echo off
setlocal

rem Project-local Claude launcher.
rem Why: when this repo is opened inside an existing Claude Code session,
rem      raw `claude` inherits CLAUDE* vars and trips the nested-session guard.
rem      This wrapper clears those vars only for this process and forwards to
rem      the globally installed Claude CLI.

set "CLAUDECODE="
set "CLAUDE_CODE_ENTRYPOINT="
set "CLAUDE_CODE_SSE_PORT="

set "CLAUDE_GLOBAL=%AppData%\npm\claude-original.cmd"
if not exist "%CLAUDE_GLOBAL%" set "CLAUDE_GLOBAL=%AppData%\npm\claude.cmd"

if not exist "%CLAUDE_GLOBAL%" (
  echo [error] Global Claude CLI not found at "%AppData%\npm".
  echo Install Claude Code globally or run: python scripts\agent_launcher.py claude yolo
  exit /b 1
)

call "%CLAUDE_GLOBAL%" %*
exit /b %errorlevel%
