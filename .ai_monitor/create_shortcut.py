import os
import winshell
from win32com.client import Dispatch
from pathlib import Path

def create_shortcut():
    base_dir = Path("D:/vibe-coding")
    bat_path = base_dir / "run_vibe.bat"
    
    if not bat_path.exists():
        print(f"Error: {bat_path} 파일을 찾을 수 없습니다.")
        return

    # 바탕화면 경로 가져오기
    desktop = os.path.join(os.path.join(os.environ['USERPROFILE']), 'Desktop')
    shortcut_path = os.path.join(desktop, "바이브코딩.lnk")
    
    # 💥 기존 단축어 강제 삭제 (아이콘 캐시 갱신 유도)
    if os.path.exists(shortcut_path):
        try:
            os.remove(shortcut_path)
            print("기존 아이콘을 삭제했습니다. 새로 생성합니다.")
        except: pass
    
    try:
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(shortcut_path)
        
        # 🟢 cmd /k 를 사용하여 실행 실패 시에도 창이 사라지지 않고 에러를 보여줌
        shortcut.Targetpath = "cmd.exe"
        shortcut.Arguments = f'/k "cd /d {str(base_dir)} && {str(bat_path)}"'
        
        shortcut.WorkingDirectory = str(base_dir)
        shortcut.Description = "바이브코딩 - AI 멀티 에이전트 하이브 마인드 대시보드"
        
        # 🎨 아이콘 설정 (새로 생성한 네온 아이콘 연결)
        ico_path = base_dir / ".ai_monitor" / "bin" / "app_icon.ico"
        if ico_path.exists():
            # 아이콘 인덱스뿐만 아니라 캐시 무효화를 위해 경로를 다시 고정
            shortcut.IconLocation = f"{str(ico_path)},0"
        
        shortcut.save()
        print(f"✨ 바탕화면 아이콘(v2.3.0)이 성공적으로 생성되었습니다: {shortcut_path}")
    except Exception as e:
        print(f"❌ 바로가기 생성 중 오류 발생: {e}")
    except Exception as e:
        print(f"❌ 바로가기 생성 중 오류 발생: {e}")
    except Exception as e:
        print(f"바로가기 생성 중 오류 발생: {e}")

if __name__ == "__main__":
    create_shortcut()
