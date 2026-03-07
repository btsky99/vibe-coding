"""
FILE: scripts/install_codex.py
DESCRIPTION: Codex CLI 설치 및 초기 설정 스크립트.
             npm을 통해 OpenAI Codex CLI를 전역 설치하고,
             설치 결과를 검증하여 사용 가능 여부를 확인합니다.

REVISION HISTORY:
- 2026-03-07 Claude Sonnet 4.6: 최초 생성 — Phase 5 Task 10
"""

import subprocess
import sys
import shutil


def run(cmd: list[str]) -> tuple[int, str, str]:
    """명령을 실행하고 (returncode, stdout, stderr) 튜플 반환."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def check_npm() -> bool:
    """npm이 PATH에 존재하는지 확인."""
    return shutil.which("npm") is not None


def install_codex() -> bool:
    """npm으로 @openai/codex를 전역 설치.

    Why: Codex CLI는 npm 패키지로 배포되므로 npm install -g 방식이 표준입니다.
    """
    print("[Codex 설치] npm install -g @openai/codex 실행 중...")
    code, out, err = run(["npm", "install", "-g", "@openai/codex"])
    if code != 0:
        print(f"[오류] 설치 실패:\n{err}")
        return False
    print(f"[성공] 설치 완료:\n{out}")
    return True


def verify_codex() -> bool:
    """codex --version을 실행하여 설치 성공 검증."""
    # Windows에서 npx 또는 직접 codex 명령을 시도
    for cmd in [["codex", "--version"], ["npx", "codex", "--version"]]:
        code, out, err = run(cmd)
        if code == 0:
            print(f"[검증] Codex 버전 확인: {out}")
            return True
    print("[경고] codex --version 실행 실패. PATH 재설정 후 재시도하세요.")
    return False


def main():
    print("=" * 50)
    print("  Codex CLI 설치 스크립트")
    print("=" * 50)

    # 1단계: npm 존재 여부 확인
    if not check_npm():
        print("[오류] npm이 설치되어 있지 않습니다. Node.js를 먼저 설치하세요.")
        print("  다운로드: https://nodejs.org/")
        sys.exit(1)
    print("[확인] npm 발견됨.")

    # 2단계: 이미 설치되어 있는지 확인 (중복 설치 방지)
    code, out, _ = run(["codex", "--version"])
    if code == 0:
        print(f"[정보] Codex가 이미 설치되어 있습니다: {out}")
        print("[완료] 재설치를 건너뜁니다.")
        return

    # 3단계: 설치
    if not install_codex():
        sys.exit(1)

    # 4단계: 검증
    if verify_codex():
        print("\n[완료] Codex CLI를 사용할 준비가 되었습니다.")
    else:
        print("\n[주의] 설치는 완료되었지만 PATH에서 찾을 수 없습니다.")
        print("  터미널을 재시작하거나 npm global bin 경로를 PATH에 추가하세요.")


if __name__ == "__main__":
    main()
