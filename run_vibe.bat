@echo off
:: -----------------------------------------------------------------------
:: run_vibe.bat
:: 설명: Vibe Coding 서버를 백그라운드(pythonw)로 기동합니다.
::       agent_launcher.py에 저장된 현재 모드(NORMAL/YOLO)를 자동 반영합니다.
::
:: REVISION HISTORY:
:: - 2026-03-07 Claude Sonnet 4.6: agent_launcher 연동 추가 — Phase 5 Task 13
:: -----------------------------------------------------------------------
cd /d "%~dp0"

set PYTHON=.ai_monitor\venv\Scripts\python.exe
set PYTHONW=.ai_monitor\venv\Scripts\pythonw.exe

:: agent_launcher.py를 통해 현재 저장된 모드로 vibe 서버 실행
:: Why: agent_launcher가 모드에 맞는 플래그를 자동으로 선택하므로
::      배치 파일은 단순히 launcher를 호출만 하면 됩니다.
if exist "%PYTHON%" (
    start "" "%PYTHONW%" scripts\agent_launcher.py vibe
) else (
    :: 가상환경이 없을 경우 시스템 pythonw 시도
    start "" pythonw scripts\agent_launcher.py vibe
)

:: 배치 파일 자체를 즉시 종료하여 터미널 창을 없앱니다.
exit
