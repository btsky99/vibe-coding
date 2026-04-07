"""
FILE: .ai_monitor/create_shortcut.py
DESCRIPTION: Windows 바탕화면 바로가기 생성 유틸리티.
  pip install 모드: vibe-coding.exe entry point 또는 pythonw -m ai_monitor 사용.
  개발 모드: run_vibe.bat 사용 (기존 방식).
  EXE 모드: 현재 실행 파일 사용.

REVISION HISTORY:
- 2026-03-26 Claude: pythonw → vibe-coding.exe 직접 실행으로 변경 (pythonw는 에러 무시)
- 2026-03-26 Claude: remove_shortcut() 추가 — 언인스톨 시 바탕화면 바로가기 삭제
- 2026-03-25 Claude: pip install 모드 대응 — entry point 자동 탐색 + winshell 의존성 제거
- 2026-03-19 Claude: 표준 헤더 형식 적용 (RULES.md 섹션 2 준수)
"""
import os
import sys
import shutil
from pathlib import Path


def create_shortcut():
    """Windows 바탕화면에 '바이브코딩' 바로가기를 생성합니다.
    실행 모드(pip/dev/EXE)를 자동 감지하여 적절한 타겟을 설정합니다.
    """
    if os.name != 'nt':
        print("바탕화면 바로가기는 Windows에서만 지원됩니다.")
        return

    try:
        from win32com.client import Dispatch
    except ImportError:
        print("pywin32가 필요합니다: pip install pywin32")
        return

    # ── 바탕화면 경로 ──
    desktop = Path(os.environ.get('USERPROFILE', '')) / 'Desktop'
    shortcut_path = desktop / "바이브코딩.lnk"

    # ── 기존 바로가기 삭제 (아이콘 캐시 갱신) ──
    if shortcut_path.exists():
        try:
            shortcut_path.unlink()
            print("기존 아이콘을 삭제했습니다. 새로 생성합니다.")
        except Exception:
            pass

    # ── 실행 대상 결정: pip entry point → run_vibe.bat → EXE 순서로 탐색 ──
    target_path = None
    arguments = ""
    working_dir = ""

    # 1순위: vibe-coding-gui (pythonw 기반 — 콘솔 창 없음)
    # gui_scripts로 생성된 EXE는 내부적으로 pythonw를 사용하여 콘솔 창이 뜨지 않음
    # 2순위: vibe-coding (콘솔 EXE — gui가 없으면 폴백)
    gui_cmd = shutil.which('vibe-coding-gui')
    cli_cmd = shutil.which('vibe-coding')
    if gui_cmd:
        target_path = str(gui_cmd)
        working_dir = str(Path.home())
        print(f"[pip 모드] GUI entry point 감지: {gui_cmd}")
    elif cli_cmd:
        target_path = str(cli_cmd)
        working_dir = str(Path.home())
        print(f"[pip 모드] CLI entry point 감지: {cli_cmd}")

    # 2순위: 개발 모드 — run_vibe.bat
    if not target_path:
        # server.py 기준으로 프로젝트 루트 탐색
        base_dir = Path(__file__).resolve().parent.parent
        bat_path = base_dir / "run_vibe.bat"
        if bat_path.exists():
            target_path = "cmd.exe"
            arguments = f'/c "cd /d {base_dir} && {bat_path}"'
            working_dir = str(base_dir)
            print(f"[개발 모드] bat 감지: {bat_path}")

    # 3순위: frozen EXE 모드
    if not target_path and getattr(sys, 'frozen', False):
        target_path = sys.executable
        working_dir = str(Path(sys.executable).parent)
        print(f"[EXE 모드] 실행 파일: {target_path}")

    if not target_path:
        print("실행 대상을 찾을 수 없습니다. pip install 또는 개발 환경을 확인하세요.")
        return

    # ── 바로가기 생성 ──
    try:
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(str(shortcut_path))
        shortcut.Targetpath = target_path
        if arguments:
            shortcut.Arguments = arguments
        shortcut.WorkingDirectory = working_dir
        shortcut.Description = "바이브코딩 - AI 멀티 에이전트 하이브 마인드 대시보드"
        # 창 최소화 상태로 시작 (콘솔 창 숨김 효과)
        shortcut.WindowStyle = 7  # SW_SHOWMINNOACTIVE

        # 아이콘 설정 — pip 설치 시 패키지 내부, 개발 모드 시 프로젝트 내부
        for ico_candidate in [
            Path(__file__).resolve().parent / "bin" / "app_icon.ico",
            Path(__file__).resolve().parent.parent / ".ai_monitor" / "bin" / "app_icon.ico",
        ]:
            if ico_candidate.exists():
                shortcut.IconLocation = f"{ico_candidate},0"
                break

        shortcut.save()
        print(f"바탕화면 바로가기가 생성되었습니다: {shortcut_path}")
    except Exception as e:
        print(f"바로가기 생성 중 오류 발생: {e}")


def create_office_shortcut():
    """Windows 바탕화면에 '바이브 오피스' 바로가기를 생성합니다.
    dashboard_window.py를 office 탭으로 실행하는 독립 바로가기입니다.
    """
    if os.name != 'nt':
        print("바탕화면 바로가기는 Windows에서만 지원됩니다.")
        return

    try:
        from win32com.client import Dispatch
    except ImportError:
        print("pywin32가 필요합니다: pip install pywin32")
        return

    desktop = Path(os.environ.get('USERPROFILE', '')) / 'Desktop'
    shortcut_path = desktop / "바이브 오피스.lnk"

    if shortcut_path.exists():
        try:
            shortcut_path.unlink()
        except Exception:
            pass

    # pythonw.exe로 dashboard_window.py office 실행
    base_dir = Path(__file__).resolve().parent
    dashboard_script = base_dir / 'dashboard_window.py'

    # venv pythonw → 시스템 pythonw 순으로 탐색
    pythonw = None
    for candidate in [
        base_dir / 'venv' / 'Scripts' / 'pythonw.exe',
        Path(sys.executable).parent / 'pythonw.exe',
    ]:
        if candidate.exists():
            pythonw = str(candidate)
            break
    if not pythonw:
        pythonw = shutil.which('pythonw') or shutil.which('python')
    if not pythonw:
        print("Python 인터프리터를 찾을 수 없습니다.")
        return

    try:
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(str(shortcut_path))
        shortcut.Targetpath = pythonw
        shortcut.Arguments = f'"{dashboard_script}" 9000 office'
        shortcut.WorkingDirectory = str(base_dir.parent)
        shortcut.Description = "바이브 오피스 - AI 에이전트 가상 오피스"
        shortcut.WindowStyle = 1  # SW_SHOWNORMAL

        # 아이콘 — 클래식과 동일 아이콘 사용
        for ico_candidate in [
            base_dir / "bin" / "app_icon.ico",
            base_dir.parent / ".ai_monitor" / "bin" / "app_icon.ico",
        ]:
            if ico_candidate.exists():
                shortcut.IconLocation = f"{ico_candidate},0"
                break

        shortcut.save()
        print(f"바탕화면 바로가기가 생성되었습니다: {shortcut_path}")
    except Exception as e:
        print(f"바로가기 생성 중 오류 발생: {e}")


def remove_shortcut():
    """Windows 바탕화면의 '바이브코딩' 바로가기를 삭제합니다.
    언인스톨 시 호출됩니다.
    """
    if os.name != 'nt':
        print("바탕화면 바로가기 삭제는 Windows에서만 지원됩니다.")
        return

    desktop = Path(os.environ.get('USERPROFILE', '')) / 'Desktop'
    shortcut_path = desktop / "바이브코딩.lnk"

    if shortcut_path.exists():
        try:
            shortcut_path.unlink()
            print(f"바탕화면 바로가기를 삭제했습니다: {shortcut_path}")
        except Exception as e:
            print(f"바로가기 삭제 실패: {e}")
    else:
        print("바탕화면에 바로가기가 없습니다.")


def shortcut_exists():
    """바탕화면에 '바이브코딩' 바로가기가 존재하는지 확인합니다."""
    if os.name != 'nt':
        return False
    desktop = Path(os.environ.get('USERPROFILE', '')) / 'Desktop'
    return (desktop / "바이브코딩.lnk").exists()


def _shortcut_needs_update():
    """기존 바로가기가 콘솔 버전(vibe-coding.exe)을 가리키는데
    GUI 버전(vibe-coding-gui.exe)이 사용 가능한 경우 True 반환.
    pip upgrade 후 바로가기가 자동으로 GUI 모드로 갱신되어야 함.
    """
    if os.name != 'nt':
        return False
    desktop = Path(os.environ.get('USERPROFILE', '')) / 'Desktop'
    lnk = desktop / "바이브코딩.lnk"
    if not lnk.exists():
        return False
    # GUI 버전이 사용 가능한지 확인
    gui_cmd = shutil.which('vibe-coding-gui')
    if not gui_cmd:
        return False
    # 현재 바로가기의 타겟 읽기
    try:
        from win32com.client import Dispatch
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(str(lnk))
        target = shortcut.Targetpath.lower()
        # 콘솔 버전을 가리키고 있으면 갱신 필요
        if 'vibe-coding-gui' not in target and 'vibe-coding' in target:
            return True
        # run_vibe.bat이나 cmd.exe를 가리키는 경우에도 갱신
        if 'cmd.exe' in target or 'run_vibe' in target:
            return True
    except Exception:
        pass
    return False


if __name__ == "__main__":
    create_shortcut()
