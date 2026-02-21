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
