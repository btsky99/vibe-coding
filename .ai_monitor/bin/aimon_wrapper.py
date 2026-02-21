import os
import sys
import subprocess
from pathlib import Path

def main():
    if getattr(sys, 'frozen', False):
        # PyInstaller로 패키징된 exe 실행 중일 때
        base_dir = Path(sys.executable).resolve().parent.parent
    else:
        # 일반 python 스크립트로 실행될 때
        base_dir = Path(__file__).resolve().parent.parent
        
    # venv 안의 파이썬 인터프리터 경로
    python_bin = base_dir / "venv" / "Scripts" / "python.exe"
    viewer_script = base_dir / "src" / "view.py"
    
    if not python_bin.exists():
        print(f"Error: Virtual environment not found at {python_bin}")
        input("Press Enter to exit...")
        sys.exit(1)
        
    if not viewer_script.exists():
        print(f"Error: Viewer script not found at {viewer_script}")
        input("Press Enter to exit...")
        sys.exit(1)
    
    # view.py 실행
    subprocess.run([str(python_bin), str(viewer_script)])

if __name__ == "__main__":
    main()
