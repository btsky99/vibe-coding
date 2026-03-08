@echo off
:: -----------------------------------------------------------------------
:: run_claude.bat
:: 설명: Claude 에이전트를 agent_launcher.py를 통해 실행합니다.
::       저장된 모드(NORMAL/YOLO)에 따라 자동으로 적절한 플래그를 적용합니다.
::       인자를 전달하면 추가 옵션으로 Claude에 넘깁니다.
::
:: REVISION HISTORY:
:: - 2026-03-07 Claude Sonnet 4.6: agent_launcher 연동 추가 — Phase 5 Task 13
:: -----------------------------------------------------------------------

:: CLAUDE 관련 환경 변수는 agent_launcher.py에서 자동으로 정화(Sanitize)합니다.
:: Why: Gemini CLI 등에서 상속된 변수가 중첩 실행 방지 로직을 트리거하는 것을 방지하기 위함입니다.

cd /d "%~dp0"

set PYTHON=.ai_monitor\venv\Scripts\python.exe

:: agent_launcher를 통해 저장된 모드로 Claude 실행
:: Why: 모드 전환 시 배치 파일을 수정할 필요 없이 launcher가 처리합니다.
if exist "%PYTHON%" (
    "%PYTHON%" scripts\agent_launcher.py claude %*
) else (
    python scripts\agent_launcher.py claude %*
)
