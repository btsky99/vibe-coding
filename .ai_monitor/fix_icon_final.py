import os
import shutil
from pathlib import Path
from win32com.client import Dispatch

def force_fix_icon():
    base_dir = Path(r"D:\vibe-coding")
    src_ico = base_dir / ".ai_monitor" / "bin" / "app_icon.ico"
    new_ico = base_dir / ".ai_monitor" / "bin" / "vibe_neon.ico"
    
    # 1. 새 이름으로 아이콘 복사 (캐시 무력화 핵심)
    if src_ico.exists():
        shutil.copy2(src_ico, new_ico)
        print(f"[*] Icon copied to {new_ico}")

    # 2. 바탕화면 경로
    desktop = os.path.join(os.environ['USERPROFILE'], 'Desktop')
    shortcut_path = os.path.join(desktop, "바이브코딩.lnk")
    
    # 3. 바로가기 생성 (PowerShell 대신 win32com 사용)
    try:
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.Targetpath = "cmd.exe"
        shortcut.Arguments = f'/k "cd /d {base_dir} && run_vibe.bat"'
        shortcut.IconLocation = f"{new_ico},0"
        shortcut.WorkingDirectory = str(base_dir)
        shortcut.save()
        print(f"[*] Desktop shortcut updated with NEW icon: {shortcut_path}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    force_fix_icon()
