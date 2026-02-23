import os
import shutil
from pathlib import Path
from PIL import Image
from win32com.client import Dispatch

def fix_all_icons_and_shortcut():
    base_dir = Path(r"D:\vibe-coding")
    png_src = base_dir / "assets" / "vibe_coding_icon.png"
    new_ico = base_dir / ".ai_monitor" / "bin" / "vibe_final.ico"
    
    # 1. ICO 파일 생성 (사용자님 네온 이미지 기반)
    if png_src.exists():
        img = Image.open(png_src)
        img.save(new_ico, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32)])
        print(f"[*] New icon created: {new_ico}")

    # 2. 바탕화면 바로가기 생성
    desktop = os.path.join(os.environ['USERPROFILE'], 'Desktop')
    lnk_path = os.path.join(desktop, "바이브코딩.lnk")
    
    try:
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(lnk_path)
        shortcut.Targetpath = "cmd.exe"
        shortcut.Arguments = f'/k "cd /d {base_dir} && run_vibe.bat"'
        shortcut.IconLocation = f"{new_ico},0"
        shortcut.WorkingDirectory = str(base_dir)
        shortcut.save()
        print(f"[*] Desktop shortcut RECREATED with new icon: {lnk_path}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fix_all_icons_and_shortcut()
