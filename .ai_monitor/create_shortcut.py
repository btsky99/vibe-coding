import os
import sys
import winshell
from win32com.client import Dispatch
from pathlib import Path

def create_shortcut():
    # 현재 스크립트 기준 경로
    base_dir = Path(__file__).resolve().parent
    exe_path = base_dir / "bin" / "aimon.exe"
    
    if not exe_path.exists():
        print(f"Error: {exe_path} 파일을 찾을 수 없습니다. (먼저 pyinstaller 등으로 컴파일 해주세요)")
        return

    desktop = winshell.desktop()
    shortcut_path = os.path.join(desktop, "AI 작업 모니터.lnk")
    
    try:
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.Targetpath = str(exe_path)
        shortcut.WorkingDirectory = str(base_dir)
        shortcut.Description = "AI 작업 동시 모니터링 뷰어 (aimon)"
        
        ico_path = base_dir / "bin" / "app_icon.ico"
        if ico_path.exists():
            shortcut.IconLocation = str(ico_path)
        else:
            shortcut.IconLocation = sys.executable

        shortcut.save()
        print(f"바탕화면에 성공적으로 바로가기가 생성되었습니다:\n> {shortcut_path}")
    except Exception as e:
        print(f"바로가기 생성 중 오류 발생: {e}")

if __name__ == "__main__":
    create_shortcut()
