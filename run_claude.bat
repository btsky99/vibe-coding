@echo off
:: CLAUDECODE 관련 환경 변수를 해제하고 Claude를 실행합니다.
set CLAUDECODE=
set CLAUDE_CODE_ENTRYPOINT=
set CLAUDE_CODE_SSE_PORT=

:: 전달된 인자가 있으면 그대로 전달, 없으면 기본 지시 없이 실행
if "%~1"=="" (
    claude --dangerously-skip-permissions
) else (
    claude -p "%~1" --dangerously-skip-permissions
)
