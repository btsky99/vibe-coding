@echo off
:: -----------------------------------------------------------------------
:: run_vibe.bat
:: 설명: Vibe Coding 서버를 콘솔 없이 백그라운드(pythonw)로 기동합니다.
::
:: REVISION HISTORY:
:: - 2026-03-10 Claude Sonnet 4.6: v3.7.44 — agent_launcher 우회 수정
::   agent_launcher.py가 os.execvp(python.exe) 호출로 콘솔창을 띄우는
::   문제 해결. pythonw.exe로 server.py를 직접 실행하도록 변경.
:: - 2026-03-07 Claude Sonnet 4.6: agent_launcher 연동 추가 — Phase 5 Task 13
:: -----------------------------------------------------------------------
cd /d "%~dp0"

set PYTHONW=.ai_monitor\venv\Scripts\pythonw.exe

:: pythonw.exe로 server.py 직접 실행 (콘솔창 없음)
:: Why: agent_launcher.py → os.execvp(python.exe) 경로를 거치면
::      콘솔(cmd) 창이 열리는 문제가 발생하므로 직접 실행합니다.
if exist "%PYTHONW%" (
    start "" "%PYTHONW%" .ai_monitor\server.py
) else (
    :: 가상환경이 없을 경우 시스템 pythonw 시도
    start "" pythonw .ai_monitor\server.py
)

:: 배치 파일 자체를 즉시 종료하여 터미널 창을 없앱니다.
exit
