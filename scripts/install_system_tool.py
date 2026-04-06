"""
FILE: scripts/install_system_tool.py
DESCRIPTION: Windows 시스템 도구 설치 스크립트.
             winget을 사용하여 Git, Inno Setup(ISCC) 등
             시스템 레벨 도구를 자동 설치한다.

             사용법:
               python install_system_tool.py --tool git
               python install_system_tool.py --tool iscc

REVISION HISTORY:
- 2026-04-05 Claude Opus 4.6: 최초 생성 — 시스템 도구 원클릭 설치
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


# ── 시스템 도구 정의 ──────────────────────────────────────────────────
SYSTEM_TOOLS: dict[str, dict] = {
    "git": {
        "name": "Git",
        "winget_id": "Git.Git",
        "check_cmd": ["git", "--version"],
        "check_paths": [
            str(Path("C:/Program Files/Git/cmd/git.exe")),
        ],
        "description": "분산 버전 관리 시스템",
        "fallback_url": "https://git-scm.com/downloads/win",
    },
    "iscc": {
        "name": "Inno Setup (ISCC)",
        "winget_id": "JRSoftware.InnoSetup",
        "check_cmd": ["ISCC.exe", "/?"],
        "check_paths": [
            str(Path("C:/Program Files (x86)/Inno Setup 6/ISCC.exe")),
            str(Path("C:/Program Files/Inno Setup 6/ISCC.exe")),
        ],
        "description": "Windows 인스톨러 빌드 도구",
        "fallback_url": "https://jrsoftware.org/isdl.php",
    },
    "obsidian": {
        "name": "Obsidian",
        "winget_id": "Obsidian.Obsidian",
        "check_cmd": ["obsidian", "--version"],
        "check_paths": [
            str(Path.home() / "AppData" / "Local" / "Obsidian" / "Obsidian.exe"),
            str(Path.home() / "AppData" / "Local" / "Programs" / "Obsidian" / "Obsidian.exe"),
        ],
        "description": "Markdown 기반 지식 관리 앱",
        "fallback_url": "https://obsidian.md/download",
    },
}


def _run(cmd: list[str]) -> tuple[int, str, str]:
    """명령을 실행하고 (returncode, stdout, stderr) 반환."""
    resolved = list(cmd)
    exe_name = resolved[0]
    if not Path(exe_name).is_absolute():
        candidates = [exe_name]
        if sys.platform == "win32" and "." not in Path(exe_name).name:
            candidates.extend([f"{exe_name}.exe", f"{exe_name}.cmd", f"{exe_name}.bat"])

        for candidate in candidates:
            found = shutil.which(candidate)
            if found:
                resolved[0] = found
                break

    result = subprocess.run(
        resolved,
        capture_output=True,
        text=True,
        timeout=600,
        encoding="utf-8",
        errors="replace",
    )
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    return result.returncode, stdout, stderr


def check_installed(tool_id: str) -> str | None:
    """도구가 설치되어 있으면 버전 문자열 반환."""
    tool = SYSTEM_TOOLS.get(tool_id)
    if not tool:
        return None
    cmd = tool["check_cmd"]
    cmd_name = cmd[0]
    if shutil.which(cmd_name):
        code, out, _ = _run(cmd)
        if code == 0:
            return out.split("\n")[0]

    for path_str in tool.get("check_paths", []):
        path = Path(path_str)
        if not path.exists():
            continue
        try:
            code, out, err = _run([str(path), "--version"])
            output = out or err
            if code == 0 and output:
                return output.split("\n")[0]
        except Exception:
            pass
        return f"installed at {path}"
    return None


def check_winget() -> bool:
    """winget 사용 가능 여부 확인."""
    if shutil.which("winget"):
        code, out, _ = _run(["winget", "--version"])
        if code == 0:
            print(f"[확인] winget {out}")
            return True
    print("[오류] winget을 사용할 수 없습니다.")
    print("       Windows 10 (1709+) 또는 Windows 11이 필요합니다.")
    return False


def install_tool(tool_id: str) -> bool:
    """winget으로 도구 설치."""
    tool = SYSTEM_TOOLS.get(tool_id)
    if not tool:
        print(f"[오류] 알 수 없는 도구: {tool_id}")
        return False

    name = tool["name"]
    winget_id = tool["winget_id"]

    print(f"\n[{name}] {tool['description']}")
    print(f"[{name}] winget install --id {winget_id} 실행 중...")

    code, out, err = _run([
        "winget", "install",
        "--id", winget_id,
        "--accept-source-agreements",
        "--accept-package-agreements",
    ])

    combined = out + err
    if code == 0:
        print(f"[성공] {name} 설치 완료")
        if out:
            print(out)
        return True

    # 이미 설치된 경우
    if "already installed" in combined.lower() or "이미 설치" in combined:
        print(f"[정보] {name}이(가) 이미 설치되어 있습니다.")
        return True

    print(f"[실패] winget 설치 실패:")
    if err:
        print(f"       {err[:300]}")
    print(f"\n       수동 다운로드: {tool['fallback_url']}")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="시스템 도구 설치 (winget)")
    parser.add_argument(
        "--tool",
        choices=list(SYSTEM_TOOLS.keys()),
        required=True,
        help="설치할 도구",
    )
    args = parser.parse_args()

    tool = SYSTEM_TOOLS[args.tool]
    name = tool["name"]

    print("=" * 50)
    print(f"  Vibe Coding — {name} 설치")
    print("=" * 50)

    # 이미 설치 확인
    version = check_installed(args.tool)
    if version:
        print(f"\n[확인] {name}이(가) 이미 설치되어 있습니다: {version}")
        return

    # winget 확인
    if not check_winget():
        print(f"\n수동으로 설치하세요: {tool['fallback_url']}")
        sys.exit(1)

    # 설치 실행
    ok = install_tool(args.tool)
    if ok:
        version = check_installed(args.tool)
        if version:
            print(f"\n[검증] {name} {version}")
        else:
            print(f"\n[주의] 설치 후 PATH 반영을 위해 터미널을 재시작하세요.")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
