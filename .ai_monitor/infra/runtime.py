"""
FILE: infra/runtime.py
DESCRIPTION: 시스템 런타임 보조 유틸 — Python 인터프리터 후보 탐색,
             tkinter 폴더 다이얼로그 서브프로세스 실행, Playwright 설치 스크립트 위치 탐색.
             EXE(frozen) 환경에서 sys.executable이 vibe-coding.exe를 가리키므로,
             실제 Python 인터프리터를 별도 후보 목록에서 찾아야 하는 공통 로직을
             모았습니다. server.py와 데몬/API 모듈이 공유합니다.

REVISION HISTORY:
- 2026-04-20 Claude: server.py L770~862 분리 (Task 2.1)
                     무상태 함수로 재구성, BASE_DIR/PROJECT_ROOT는 인자로 명시화
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def python_runner_cmds(base_dir: Path, project_root: Path) -> list[str]:
    """Python 스크립트를 실행할 인터프리터 후보 목록을 반환합니다."""
    candidates: list[str] = []
    seen: set[str] = set()

    for path in (
        base_dir / 'venv' / 'Scripts' / 'python.exe',
        project_root / '.ai_monitor' / 'venv' / 'Scripts' / 'python.exe',
        project_root / 'venv' / 'Scripts' / 'python.exe',
    ):
        path_str = str(path)
        if path.exists() and path_str not in seen:
            candidates.append(path_str)
            seen.add(path_str)

    exe_name = Path(sys.executable).name.lower()
    if exe_name.startswith('python') and sys.executable not in seen:
        candidates.append(sys.executable)
        seen.add(sys.executable)

    for name in ('python', 'py'):
        resolved = shutil.which(name)
        if resolved and resolved not in seen:
            candidates.append(resolved)
            seen.add(resolved)

    return candidates or ['python']


def project_python_runner_cmds(
    base_dir: Path,
    fallback_project_root: Path,
    project_root: Path | None = None,
) -> list[str]:
    """현재 프로젝트 가상환경을 우선하는 Python 인터프리터 후보 목록."""
    candidates: list[str] = []
    seen: set[str] = set()

    if project_root is not None:
        for path in (
            project_root / '.venv' / 'Scripts' / 'python.exe',
            project_root / 'venv' / 'Scripts' / 'python.exe',
            project_root / '.ai_monitor' / 'venv' / 'Scripts' / 'python.exe',
        ):
            path_str = str(path)
            if path.exists() and path_str not in seen:
                candidates.append(path_str)
                seen.add(path_str)

    for cmd in python_runner_cmds(base_dir, fallback_project_root):
        if cmd not in seen:
            candidates.append(cmd)
            seen.add(cmd)

    return candidates or ['python']


def resolve_playwright_install_script(base_dir: Path, project_root: Path) -> Path | None:
    """Playwright 설치 스크립트 위치를 탐색합니다."""
    candidates = (
        project_root / 'scripts' / 'install_playwright_cli.py',
        base_dir.parent / 'scripts' / 'install_playwright_cli.py',
        Path.cwd() / 'scripts' / 'install_playwright_cli.py',
    )
    for path in candidates:
        if path.exists():
            return path
    return None


def open_folder_dialog_subprocess(python_cmd: str) -> str:
    """tkinter 폴더 선택 다이얼로그를 별도 프로세스에서 실행.

    pywebview GUI 스레드에서 tkinter를 직접 호출하면 충돌하므로,
    독립 Python 프로세스로 실행하여 선택된 경로 문자열을 반환합니다.
    사용자가 취소하면 빈 문자열 반환.

    EXE 빌드에서는 sys.executable이 vibe-coding.exe를 가리키므로,
    호출자가 python_runner_cmds()[0]를 인자로 전달해야 합니다.
    """
    script = (
        "import tkinter as tk; from tkinter import filedialog; "
        "root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True); "
        "path = filedialog.askdirectory(title='프로젝트 폴더 선택'); "
        "print(path if path else '')"
    )
    _no_win = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    result = subprocess.run(
        [python_cmd, '-c', script],
        capture_output=True, text=True, timeout=60,
        creationflags=_no_win,
    )
    return result.stdout.strip()


def open_file_dialog_subprocess(python_cmd: str) -> str:
    """tkinter 파일 선택 다이얼로그를 별도 프로세스에서 실행.

    [WHY] LAN 파일 전송이 경로를 손으로 타이핑해야만 하는 문제(찾아보기 부재) 해소.
      폴더용 open_folder_dialog_subprocess와 동일 패턴 — pywebview GUI 스레드에서
      tkinter 직접 호출 시 충돌하므로 독립 프로세스로 우회한다(검증된 방식).
    [제약] askdirectory가 아니라 askopenfilename — 전송할 '파일 1개'를 고른다.
      취소 시 빈 문자열. EXE 빌드에선 호출자가 python_runner_cmds()[0]를 넘겨야 함.
    """
    script = (
        "import tkinter as tk; from tkinter import filedialog; "
        "root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True); "
        "path = filedialog.askopenfilename(title='전송할 파일 선택'); "
        "print(path if path else '')"
    )
    _no_win = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    result = subprocess.run(
        [python_cmd, '-c', script],
        capture_output=True, text=True, timeout=60,
        creationflags=_no_win,
    )
    return result.stdout.strip()
