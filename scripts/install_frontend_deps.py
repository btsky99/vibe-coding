"""
FILE: scripts/install_frontend_deps.py
DESCRIPTION: 프론트엔드(React/Vite) 의존성 설치 스크립트.
             .ai_monitor/vibe-view/ 디렉토리에서 npm install을 실행하여
             TypeScript, Vite, ESLint, Tailwind CSS 등 프론트엔드 도구를 설치한다.
             --tool 인자로 특정 도구 상태만 확인하거나, 전체 npm install 실행.

REVISION HISTORY:
- 2026-04-05 Claude Opus 4.6: 최초 생성 — 프론트엔드 도구 원클릭 설치
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


# ── 경로 설정 ──────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_VIBE_VIEW_DIR = _PROJECT_ROOT / ".ai_monitor" / "vibe-view"

# 프론트엔드 도구 → npm 패키지명 매핑
FRONTEND_TOOLS: dict[str, dict] = {
    "typescript": {
        "package": "typescript",
        "check_cmd": ["npx", "tsc", "--version"],
        "description": "JavaScript/TypeScript 타입 체크 컴파일러",
    },
    "vite": {
        "package": "vite",
        "check_cmd": ["npx", "vite", "--version"],
        "description": "초고속 프론트엔드 빌드 번들러",
    },
    "eslint": {
        "package": "eslint",
        "check_cmd": ["npx", "eslint", "--version"],
        "description": "JavaScript/TypeScript 린팅 도구",
    },
    "tailwindcss": {
        "package": "tailwindcss",
        "check_cmd": ["npx", "tailwindcss", "--help"],
        "description": "유틸리티 기반 CSS 프레임워크",
    },
}


def _run(cmd: list[str], cwd: str | Path | None = None) -> tuple[int, str, str]:
    """명령을 실행하고 (returncode, stdout, stderr) 반환."""
    resolved = list(cmd)
    exe_name = resolved[0]
    if not os.path.isabs(exe_name):
        candidates = [exe_name]
        if os.name == "nt" and "." not in Path(exe_name).name:
            candidates.extend([f"{exe_name}.cmd", f"{exe_name}.exe", f"{exe_name}.bat"])

        for candidate in candidates:
            found = shutil.which(candidate)
            if found:
                resolved[0] = found
                break

    result = subprocess.run(
        resolved, capture_output=True, text=True, timeout=300, cwd=cwd,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def check_node() -> bool:
    """Node.js/npm 설치 여부 확인."""
    npm_cmd = shutil.which("npm.cmd") or shutil.which("npm.exe") or shutil.which("npm")
    if not npm_cmd:
        print("[오류] npm이 설치되어 있지 않습니다.")
        print("       Node.js를 먼저 설치하세요: https://nodejs.org/")
        return False
    code, out, _ = _run([npm_cmd, "--version"])
    if code == 0:
        print(f"[확인] npm {out}")
    return code == 0


def check_tool(tool_id: str) -> str | None:
    """프론트엔드 도구 설치 여부 확인."""
    tool = FRONTEND_TOOLS.get(tool_id)
    if not tool:
        return None
    code, out, _ = _run(tool["check_cmd"], cwd=str(_VIBE_VIEW_DIR))
    if code == 0:
        return out.split("\n")[0]
    return None


def npm_install() -> bool:
    """npm install 실행하여 모든 프론트엔드 의존성 설치."""
    if not _VIBE_VIEW_DIR.exists():
        print(f"[오류] 프론트엔드 디렉토리가 없습니다: {_VIBE_VIEW_DIR}")
        return False

    package_json = _VIBE_VIEW_DIR / "package.json"
    if not package_json.exists():
        print(f"[오류] package.json이 없습니다: {package_json}")
        return False

    print(f"\n[설치] npm install 실행 중...")
    print(f"       경로: {_VIBE_VIEW_DIR}")

    # npm install 실행 (stdout을 실시간 출력)
    npm_cmd = shutil.which("npm.cmd") or shutil.which("npm.exe") or shutil.which("npm") or "npm"
    proc = subprocess.run(
        [npm_cmd, "install"],
        cwd=str(_VIBE_VIEW_DIR),
        timeout=600,
        text=True,
        capture_output=True,
    )

    if proc.stdout:
        print(proc.stdout)
    if proc.returncode != 0:
        print(f"[오류] npm install 실패:")
        if proc.stderr:
            print(proc.stderr[:500])
        return False

    print("[성공] npm install 완료")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="프론트엔드 의존성 설치")
    parser.add_argument(
        "--tool",
        choices=list(FRONTEND_TOOLS.keys()) + ["all"],
        default="all",
        help="확인/설치할 도구 (기본: all — npm install 전체 실행)",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("  Vibe Coding — 프론트엔드 도구 설치")
    print(f"  경로: {_VIBE_VIEW_DIR}")
    print("=" * 50)

    if not check_node():
        sys.exit(1)

    # 특정 도구 또는 전체 설치
    targets = list(FRONTEND_TOOLS.keys()) if args.tool == "all" else [args.tool]

    # 현재 상태 확인
    print("\n[상태 확인]")
    all_installed = True
    for tid in targets:
        tool = FRONTEND_TOOLS[tid]
        version = check_tool(tid)
        if version:
            print(f"  [설치됨] {tid}: {version}")
        else:
            print(f"  [미설치] {tid}: {tool['description']}")
            all_installed = False

    if all_installed:
        print(f"\n모든 도구가 이미 설치되어 있습니다.")
        return

    # npm install 실행
    ok = npm_install()
    if not ok:
        print("\n설치에 실패했습니다.")
        sys.exit(1)

    # 설치 검증
    print("\n[설치 검증]")
    results: dict[str, str] = {}
    for tid in targets:
        version = check_tool(tid)
        if version:
            results[tid] = f"설치됨: {version}"
        else:
            results[tid] = "감지 안 됨"

    print("\n" + "=" * 50)
    print("  설치 결과 요약")
    print("=" * 50)
    for tid, status in results.items():
        icon = "O" if "설치됨" in status else "X"
        print(f"  [{icon}] {tid:15s} — {status}")
    print()


if __name__ == "__main__":
    main()
