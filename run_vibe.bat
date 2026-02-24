@echo off
cd /d "%~dp0"

:: pythonw.exe는 터미널 창을 생성하지 않는 윈도우용 파이썬입니다.
set PYTHONW=.ai_monitor\venv\Scripts\pythonw.exe

if exist "%PYTHONW%" (
    start "" "%PYTHONW%" .ai_monitor\server.py
) else (
    :: 가상환경이 없을 경우 시스템 pythonw 시도
    start "" pythonw .ai_monitor\server.py
)

:: 배치 파일 자체를 즉시 종료하여 터미널 창을 없앱니다.
exit
