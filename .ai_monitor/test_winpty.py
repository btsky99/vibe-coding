"""
FILE: .ai_monitor/test_winpty.py
DESCRIPTION: winpty 비동기 PTY 통합 테스트 (개발용).

REVISION HISTORY:
- 2026-03-19 Claude: 표준 헤더 형식 적용 (RULES.md 섹션 2 준수)
"""
import asyncio
import threading

def test():
    try:
        from winpty import PtyProcess
        pty = PtyProcess.spawn('cmd.exe')
        print("PtyProcess works")
    except Exception as e:
        print("PtyProcess error:", e)

    try:
        from winpty import PTY
        pty = PTY(80, 24)
        pty.spawn('cmd.exe')
        print("PTY works")
    except Exception as e:
        print("PTY error:", e)

test()
