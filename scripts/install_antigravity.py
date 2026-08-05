"""
FILE: scripts/install_antigravity.py
DESCRIPTION: Install Google's official Antigravity CLI (`agy`).

REVISION HISTORY:
- 2026-08-05 Claude: 설치 후 `agy` 실검증 추가 — returncode 0만 믿고 '완료'로 보고하던 구멍.
- 2026-07-29 Codex: Add official Antigravity CLI installation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def _refresh_path() -> None:
    """설치기가 레지스트리에 추가한 %LOCALAPPDATA%\\agy\\bin을 이 프로세스에 반영한다.

    [WHY] install.ps1은 사용자 레지스트리 PATH만 갱신한다. 이 프로세스의 PATH는 기동 시점
      스냅샷이라 갱신 없이 shutil.which('agy')를 부르면 방금 깐 것도 못 찾는다.
    [제약] infra 모듈을 못 찾아도 설치는 성공한 상태다 — 검증만 건너뛴다(설치 자체를 막지 않음).
    """
    ai_monitor = SCRIPT_DIR.parent / ".ai_monitor"
    if ai_monitor.is_dir() and str(ai_monitor) not in sys.path:
        sys.path.insert(0, str(ai_monitor))
    try:
        from infra import env_path
        env_path.refresh_path(force=True)
    except Exception:
        pass


def _agy_present() -> bool:
    """`agy` 실행 파일이 PATH에서 잡히는지. Windows는 확장자 변형까지 확인한다."""
    return any(shutil.which(name) for name in ("agy", "agy.exe", "agy.cmd", "agy.bat"))


def main() -> None:
    _refresh_path()
    if _agy_present():
        print("[skip] Antigravity CLI is already installed.")
        return

    if os.name == "nt":
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                (
                    "Invoke-RestMethod https://antigravity.google/cli/install.ps1 "
                    "| Invoke-Expression"
                ),
            ],
            timeout=900,
        )
    else:
        result = subprocess.run(
            ["sh", "-c", "curl -fsSL https://antigravity.google/cli/install.sh | bash"],
            timeout=900,
        )

    if result.returncode != 0:
        raise SystemExit(result.returncode)

    # [과거사고 2026-08-05] 여기서 바로 '완료'를 찍고 끝냈다. install.ps1은 다운로드만 하고
    #   PATH 등록에 실패해도 0을 반환할 수 있어, 다음 진단에서 '미설치'로 돌아오는데도
    #   설치 로그는 성공으로 남아 원인 추적이 막혔다. 실제 실행 파일 존재로 판정한다.
    _refresh_path()
    if not _agy_present():
        print(
            "[failed] 설치 스크립트는 성공했지만 `agy` 실행 파일을 찾지 못했습니다.\n"
            "         새 터미널을 열어 `agy --version`을 확인하거나, PATH에 "
            "%LOCALAPPDATA%\\agy\\bin 이 등록됐는지 점검하세요."
        )
        raise SystemExit(1)
    print("[complete] Antigravity CLI installation finished.")


if __name__ == "__main__":
    main()
