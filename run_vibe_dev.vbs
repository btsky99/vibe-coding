Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "D:\vibe-coding"
WshShell.Run """D:\vibe-coding\.ai_monitor\venv\Scripts\pythonw.exe"" ""D:\vibe-coding\.ai_monitor\server.py""", 0, False
