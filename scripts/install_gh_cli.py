"""
FILE: scripts/install_gh_cli.py
DESCRIPTION: GitHub CLI(gh) 자동 설치 스크립트.
             winget 또는 MSI 직접 다운로드 방식으로 gh CLI를 설치하고,
             설치 결과를 검증하여 사용 가능 여부를 확인합니다.

REVISION HISTORY:
- 2026-04-05 Claude Opus 4.6: 최초 생성 — AI 도구 설치 메뉴 지원
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request


# ── gh CLI 최신 버전 (업데이트 시 이 값만 변경) ─────────────────────────
GH_VERSION = "2.89.0"
GH_MSI_URL = f"https://github.com/cli/cli/releases/download/v{GH_VERSION}/gh_{GH_VERSION}_windows_amd64.msi"


def _run(cmd: list[str], **kwargs) -> tuple[int, str, str]:
    """명령을 실행하고 (returncode, stdout, stderr) 튜플 반환."""
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def check_installed() -> str | None:
    """gh CLI가 이미 설치되어 있으면 버전 문자열 반환, 아니면 None."""
    # PATH에서 직접 검색
    gh_path = shutil.which("gh")
    if not gh_path:
        # Windows 기본 설치 경로 확인
        default_path = os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "GitHub CLI", "gh.exe")
        if os.path.exists(default_path):
            gh_path = default_path

    if gh_path:
        code, out, _ = _run([gh_path, "--version"])
        if code == 0:
            return out
    return None


def install_via_winget() -> bool:
    """winget으로 gh CLI 설치 시도.

    Why: winget이 Windows 표준 패키지 관리자이므로 우선 시도한다.
    자동 PATH 등록 + 업데이트 관리 측면에서 MSI 직접 설치보다 유리.
    """
    if not shutil.which("winget"):
        print("[gh] winget을 찾을 수 없음 — MSI 직접 설치로 전환")
        return False

    print("[gh] winget install GitHub.cli 실행 중...")
    code, out, err = _run([
        "winget", "install", "--id", "GitHub.cli",
        "--accept-package-agreements", "--accept-source-agreements",
        "--silent"
    ])
    if code == 0:
        print(f"[gh] winget 설치 성공")
        return True
    else:
        print(f"[gh] winget 설치 실패 (exit {code}): {err}")
        return False


def install_via_msi() -> bool:
    """MSI 파일을 직접 다운로드하여 /quiet 모드로 설치.

    Why: winget이 실패하거나 없는 환경에서의 폴백 수단.
    관리자 권한이 필요할 수 있으므로 실패 시 안내 메시지 출력.
    """
    print(f"[gh] MSI 다운로드 중: {GH_MSI_URL}")
    msi_path = os.path.join(tempfile.gettempdir(), f"gh_{GH_VERSION}_windows_amd64.msi")

    try:
        urllib.request.urlretrieve(GH_MSI_URL, msi_path)
        print(f"[gh] 다운로드 완료: {msi_path}")
    except Exception as e:
        print(f"[오류] MSI 다운로드 실패: {e}")
        return False

    # msiexec /i 로 조용히 설치
    print("[gh] msiexec /i ... /quiet /norestart 실행 중...")
    code, out, err = _run(["msiexec", "/i", msi_path, "/quiet", "/norestart"])
    if code == 0:
        print("[gh] MSI 설치 성공")
        return True
    else:
        print(f"[gh] MSI 설치 실패 (exit {code}). 관리자 권한이 필요할 수 있습니다.")
        print(f"     수동 설치: {GH_MSI_URL}")
        return False


def setup_git_credential() -> None:
    """gh auth setup-git을 실행하여 git credential helper를 등록."""
    gh_path = shutil.which("gh")
    if not gh_path:
        default_path = os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "GitHub CLI", "gh.exe")
        if os.path.exists(default_path):
            gh_path = default_path

    if gh_path:
        print("[gh] git credential helper 등록 중...")
        code, _, err = _run([gh_path, "auth", "setup-git"])
        if code == 0:
            print("[gh] git credential helper 등록 완료")
        else:
            print(f"[gh] credential 설정 건너뜀 (로그인 필요): {err}")


def main() -> None:
    print("=" * 50)
    print("  GitHub CLI (gh) 설치 스크립트")
    print("=" * 50)

    # 1단계: 이미 설치되어 있는지 확인
    version = check_installed()
    if version:
        print(f"[정보] gh CLI가 이미 설치되어 있습니다: {version}")
        setup_git_credential()
        print("[완료] 재설치를 건너뜁니다.")
        return

    # 2단계: winget 우선, 실패 시 MSI 직접 설치
    installed = install_via_winget()
    if not installed:
        installed = install_via_msi()

    if not installed:
        print("\n[실패] gh CLI 설치에 실패했습니다.")
        print("  수동 설치: https://cli.github.com/")
        sys.exit(1)

    # 3단계: 설치 검증
    version = check_installed()
    if version:
        print(f"\n[검증] gh CLI 설치 확인: {version}")
        setup_git_credential()
        print("[완료] gh CLI를 사용할 준비가 되었습니다.")
        print("  로그인: gh auth login --web")
    else:
        print("\n[주의] 설치는 완료되었지만 PATH에서 찾을 수 없습니다.")
        print("  터미널을 재시작하거나 'C:\\Program Files\\GitHub CLI'를 PATH에 추가하세요.")


if __name__ == "__main__":
    main()
