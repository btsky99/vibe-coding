@echo off
setlocal enabledelayedexpansion
:: -----------------------------------------------------------------------
:: run_vibe.bat
:: 설명: Vibe Coding 서버를 콘솔 없이 백그라운드(pythonw)로 기동합니다.
::
:: REVISION HISTORY:
:: - 2026-03-14 Claude Sonnet 4.6: v3.7.60 — PID 체크 버그 수정
::   setlocal enabledelayedexpansion + !OLD_PID! 사용으로 if 블록 내
::   변수 확장 문제 해결. 기존 %OLD_PID%는 항상 빈 문자열이었음.
:: - 2026-03-14 Claude Sonnet 4.6: v3.7.60 — 개발 모드 더블클릭 중복 실행 방지
::   PID 파일(.ai_monitor\data\.dev_server.pid) 기반으로 이미 실행 중인
::   pythonw.exe 프로세스가 있으면 조용히 종료. server.py가 시작 시 PID 기록.
:: - 2026-03-10 Claude Sonnet 4.6: v3.7.44 — agent_launcher 우회 수정
::   agent_launcher.py가 os.execvp(python.exe) 호출로 콘솔창을 띄우는
::   문제 해결. pythonw.exe로 server.py를 직접 실행하도록 변경.
:: - 2026-03-07 Claude Sonnet 4.6: agent_launcher 연동 추가 — Phase 5 Task 13
:: -----------------------------------------------------------------------
cd /d "%~dp0"

:: ── 중복 실행 방지 (더블클릭 실수로 2개 인스턴스 뜨는 문제 해소) ──────────
:: server.py가 시작 시 .ai_monitor\data\.dev_server.pid 에 자신의 PID를 기록함.
:: 이 PID의 pythonw.exe 프로세스가 살아있으면 이미 실행 중이므로 조용히 종료.
:: [버그 수정] setlocal enabledelayedexpansion 없이 if 블록 내 %OLD_PID%를 쓰면
::            블록 진입 시점에 확장되어 항상 빈 문자열이 됨 → !OLD_PID! 로 변경.
set PID_FILE=.ai_monitor\data\.dev_server.pid
if exist "%PID_FILE%" (
    set /p OLD_PID=<"%PID_FILE%"
    tasklist /FI "PID eq !OLD_PID!" /FI "IMAGENAME eq pythonw.exe" 2>NUL | find /I "pythonw.exe" >NUL 2>&1
    if not errorlevel 1 (
        exit
    )
)

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
