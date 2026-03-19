"""
FILE: .ai_monitor/test_pty.py
DESCRIPTION: winpty PtyProcess 통합 테스트 (개발용).

REVISION HISTORY:
- 2026-03-19 Claude: 표준 헤더 형식 적용 (RULES.md 섹션 2 준수)
"""
from winpty import PtyProcess
import time

def test():
    try:
        pty = PtyProcess.spawn('cmd.exe')
        print("Spawned cmd.exe")
        print("Read 1:", pty.read(1024))
        
        pty.write('claude\r\n')
        print("Wrote claude")
        
        time.sleep(1)
        print("Read 2:", pty.read(4096))
        
        time.sleep(1)
        print("Read 3:", pty.read(4096))
    except Exception as e:
        print("Exception:", e)

test()
