import os
import winshell
from win32com.client import Dispatch
from pathlib import Path

def create_shortcut():
    # 빌드된 실행 파일 경로
    base_dir = Path("D:/vibe-coding")
    exe_path = base_dir / "dist" / "vibe-coding.exe"
    
    if not exe_path.exists():
        print(f"Error: {exe_path} 파일을 찾을 수 없습니다.")
        return

    desktop = winshell.desktop()
    shortcut_path = os.path.join(desktop, "바이브코딩.lnk")
    
    try:
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(shortcut_path)
        
        # 빌드된 .exe 파일을 직접 타겟으로 설정
        shortcut.Targetpath = str(exe_path)
        shortcut.WorkingDirectory = str(base_dir) # 프로젝트 루트
        shortcut.Description = "바이브코딩 - AI 멀티 에이전트 하이브 마인드 대시보드"
        
        # 아이콘 설정
        ico_path = base_dir / ".ai_monitor" / "bin" / "app_icon.ico"
        if ico_path.exists():
            shortcut.IconLocation = f"{str(ico_path)},0"
        
        shortcut.save()
        print(f"✨ 바탕화면에 최신 실행 파일과 연결된 바로가기가 생성되었습니다: {shortcut_path}")
    except Exception as e:
        print(f"바로가기 생성 중 오류 발생: {e}")

if __name__ == "__main__":
    create_shortcut()
