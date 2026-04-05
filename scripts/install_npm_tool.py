"""
FILE: scripts/install_npm_tool.py
DESCRIPTION: npm 글로벌 패키지 설치 스크립트.
             Claude CLI, Gemini CLI, Codex CLI 등 npm 기반 AI 도구를
             원클릭으로 설치한다. Node.js/npm 사전 설치 필요.

             사용법:
               python install_npm_tool.py --package @anthropic-ai/claude-code --name "Claude CLI"
               python install_npm_tool.py --package @google/gemini-cli --name "Gemini CLI"

REVISION HISTORY:
- 2026-04-05 Claude Opus 4.6: 최초 생성 — npm 기반 AI 도구 자동 설치 지원
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys


def _run(cmd: list[str]) -> tuple[int, str, str]:
    """명령을 실행하고 (returncode, stdout, stderr) 반환."""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def check_npm() -> bool:
    """npm이 설치되어 있는지 확인."""
    if shutil.which("npm"):
        code, out, _ = _run(["npm", "--version"])
        if code == 0:
            print(f"[확인] npm {out}")
            return True
    print("[오류] npm이 설치되어 있지 않습니다.")
    print("       Node.js를 먼저 설치하세요: https://nodejs.org/")
    print("       또는 대시보드에서 Node.js 설치 버튼을 클릭하세요.")
    return False


def install_package(package: str, name: str) -> bool:
    """npm 글로벌 패키지 설치."""
    print(f"\n[{name}] npm install -g {package} 실행 중...")

    code, out, err = _run(["npm", "install", "-g", package])
    if code != 0:
        print(f"[오류] 설치 실패:\n{err}")
        return False

    print(f"[성공] {package} 설치 완료")
    if out:
        print(out)
    return True


def verify_install(package: str, name: str) -> None:
    """설치 검증 — npm list에서 패키지 확인."""
    code, out, _ = _run(["npm", "list", "-g", package, "--depth=0"])
    if code == 0 and package in out:
        print(f"[검증] {name} 설치 확인됨")
        print(f"       {out}")
    else:
        print(f"[주의] 설치 후 확인 불가. 터미널 재시작이 필요할 수 있습니다.")


def main() -> None:
    parser = argparse.ArgumentParser(description="npm 글로벌 패키지 설치")
    parser.add_argument("--package", required=True, help="npm 패키지명 (예: @anthropic-ai/claude-code)")
    parser.add_argument("--name", default="", help="도구 표시 이름 (예: Claude CLI)")
    args = parser.parse_args()

    name = args.name or args.package

    print("=" * 50)
    print(f"  Vibe Coding — {name} 설치")
    print("=" * 50)

    if not check_npm():
        sys.exit(1)

    ok = install_package(args.package, name)
    if ok:
        verify_install(args.package, name)
        print(f"\n✅ {name} 설치가 완료되었습니다.")
    else:
        print(f"\n❌ {name} 설치에 실패했습니다.")
        sys.exit(1)


if __name__ == "__main__":
    main()
