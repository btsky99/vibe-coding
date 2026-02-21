@echo off
REM AI ?�업 모니??로거 ?�퍼 ?�크립트 (Windows??

set "AI_MONITOR_DIR=%~dp0.."
set "PYTHON_BIN=%AI_MONITOR_DIR%\venv\Scripts\python.exe"

if not exist "%PYTHON_BIN%" (
    echo Error: Virtual environment not found at %PYTHON_BIN%
    exit /b 1
)

set "COMMAND=%~1"
if "%COMMAND%"=="" (
    echo Usage: logger.bat ^<start^|phase^|end^> [args...]
    exit /b 1
)

REM JSON ?�이?��? 직접 ?�성?�거???�시 ?�일???�아 ?�용?????�도�?구성.
REM (Windows Batch ?�계??복잡??JSON ?�스케?�프가 까다로우므�?간단???�이???�크립트�??�임 ?�출)
"%PYTHON_BIN%" "%AI_MONITOR_DIR%\src\logger.py" payload "eyJjb21tYW5kIjogInN0YXJ0IiwgInRlcm1pbmFsX2lkIjogIldJTl9URU1QT1JBUlkiLCAicHJvamVjdCI6ICJ0ZXN0IiwgImFnZW50IjogInRlc3RfZW52In0="
REM Base64 ?�코???�코?�을 ?�이???�크립트 ?��??�서 ?�도???�라미터�?처리?�도�??�후 개선 ?�요.
rem ?�재???�스?�로 ?�퍼 출력�???
echo Logger called for %COMMAND%
