"""
FILE: scripts/install_dev_tools.py
DESCRIPTION: 프로젝트 개발 도구 통합 설치 스크립트.
             ruff, uv, pytest, pyinstaller 등 Python 기반 개발 도구를
             pip로 설치하고 결과를 검증한다.
             --tool 인자로 특정 도구만 선택 설치 가능.

REVISION HISTORY:
- 2026-04-05 Claude Opus 4.6: 최초 생성 — AI 도구 설치 메뉴 지원
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys


# ── 설치 가능한 도구 정의 ──────────────────────────────────────────────
# 각 항목: (pip 패키지명, CLI 명령어, 설명)
TOOLS: dict[str, dict] = {
    "ruff": {
        "package": "ruff",
        "command": "ruff",
        "description": "Python 린팅 + 포맷팅 도구 (Rust 기반, 초고속)",
    },
    "uv": {
        "package": "uv",
        "command": "uv",
        "description": "초고속 Python 패키지 관리자 (pip 대체)",
    },
    "pytest": {
        "package": "pytest",
        "command": "pytest",
        "description": "Python 단위 테스트 프레임워크",
    },
    "pyinstaller": {
        "package": "pyinstaller",
        "command": "pyinstaller",
        "description": "Python → Windows EXE 빌드 도구",
    },
}


def _run(cmd: list[str]) -> tuple[int, str, str]:
    """명령을 실행하고 (returncode, stdout, stderr) 반환."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def check_installed(tool_id: str) -> str | None:
    """도구가 설치되어 있으면 버전 문자열 반환, 아니면 None."""
    tool = TOOLS.get(tool_id)
    if not tool:
        return None

    cmd_name = tool["command"]
    # shutil.which로 PATH 확인
    if shutil.which(cmd_name):
        code, out, _ = _run([cmd_name, "--version"])
        if code == 0:
            return out.split("\n")[0]

    # python -m 방식으로도 확인
    code, out, _ = _run([sys.executable, "-m", tool["package"], "--version"])
    if code == 0:
        return out.split("\n")[0]

    return None


def install_tool(tool_id: str) -> bool:
    """pip로 도구를 설치."""
    tool = TOOLS.get(tool_id)
    if not tool:
        print(f"[오류] 알 수 없는 도구: {tool_id}")
        return False

    pkg = tool["package"]
    print(f"\n[{tool_id}] {tool['description']}")
    print(f"[{tool_id}] pip install -U {pkg} 실행 중...")

    code, out, err = _run([sys.executable, "-m", "pip", "install", "-U", pkg])
    if code != 0:
        print(f"[오류] 설치 실패:\n{err}")
        return False

    print(f"[성공] {pkg} 설치 완료")

    # 설치 검증
    version = check_installed(tool_id)
    if version:
        print(f"[검증] {version}")
    else:
        print(f"[주의] 설치 후 PATH에서 감지되지 않음. 터미널 재시작 필요할 수 있음.")

    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="프로젝트 개발 도구 설치")
    parser.add_argument(
        "--tool",
        choices=list(TOOLS.keys()) + ["all"],
        default="all",
        help="설치할 도구 (기본: all)",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("  Vibe Coding — 개발 도구 설치")
    print(f"  Python: {sys.executable}")
    print("=" * 50)

    targets = list(TOOLS.keys()) if args.tool == "all" else [args.tool]
    results: dict[str, str] = {}

    for tool_id in targets:
        # 이미 설치된 경우 건너뛰기
        version = check_installed(tool_id)
        if version:
            print(f"\n[{tool_id}] 이미 설치됨: {version}")
            results[tool_id] = "이미 설치됨"
            continue

        ok = install_tool(tool_id)
        results[tool_id] = "설치 완료" if ok else "설치 실패"

    # 결과 요약
    print("\n" + "=" * 50)
    print("  설치 결과 요약")
    print("=" * 50)
    for tid, status in results.items():
        icon = "✅" if "완료" in status or "이미" in status else "❌"
        print(f"  {icon} {tid:15s} — {status}")
    print()


if __name__ == "__main__":
    main()
