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
