"""
FILE: scripts/install_nodejs.py
DESCRIPTION: Node.js LTS 자동 설치 스크립트 (Windows).
             winget을 우선 시도하고, 없으면 공식 MSI 인스톨러를 다운로드하여 실행.
             Claude CLI, Antigravity CLI, Codex CLI 등 npm 기반 도구의 사전 요구사항.

REVISION HISTORY:
- 2026-07-29 Codex: Wait for fallback MSI completion so dependent CLI installs run in order.
- 2026-04-05 Claude Opus 4.6: 최초 생성 — Node.js 원클릭 설치 지원
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


def _run(cmd: list[str], **kwargs) -> tuple[int, str, str]:
    """명령을 실행하고 (returncode, stdout, stderr) 반환."""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, **kwargs)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def check_node() -> str | None:
    """Node.js가 설치되어 있으면 버전 반환."""
    if shutil.which("node"):
        code, out, _ = _run(["node", "--version"])
        if code == 0:
            return out
    return None


def install_via_winget() -> bool:
    """winget으로 Node.js LTS 설치 시도."""
    if not shutil.which("winget"):
        print("[정보] winget을 사용할 수 없습니다. MSI 다운로드로 전환합니다.")
        return False

    print("[설치] winget install --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements")
    code, out, err = _run([
        "winget", "install",
        "--id", "OpenJS.NodeJS.LTS",
        "--accept-source-agreements",
        "--accept-package-agreements",
    ])

    if code == 0:
        print(f"[성공] winget 설치 완료")
        if out:
            print(out)
        return True

    # 이미 설치된 경우
    if "already installed" in (out + err).lower() or "이미 설치" in (out + err):
        print("[정보] Node.js가 이미 설치되어 있습니다.")
        return True

    print(f"[실패] winget 설치 실패. MSI 다운로드로 전환합니다.")
    if err:
        print(f"       {err[:200]}")
    return False


def install_via_msi() -> bool:
    """Node.js 공식 MSI 인스톨러 다운로드 후 실행."""
    # LTS 최신 버전 MSI (x64)
    url = "https://nodejs.org/dist/v22.16.0/node-v22.16.0-x64.msi"
    msi_path = Path(tempfile.gettempdir()) / "node-lts-installer.msi"

    print(f"[다운로드] {url}")
    print(f"[경로] {msi_path}")

    try:
        urllib.request.urlretrieve(url, str(msi_path))
        print(f"[다운로드] 완료 ({msi_path.stat().st_size / 1024 / 1024:.1f} MB)")
    except Exception as e:
        print(f"[오류] 다운로드 실패: {e}")
        print("       https://nodejs.org/ 에서 직접 다운로드하세요.")
        return False

    print("[설치] MSI 인스톨러 실행 중... (설치 마법사를 따라 진행하세요)")
    try:
        # MSI 실행 (사용자 인터랙션 필요)
        result = subprocess.run(
            ["msiexec", "/i", str(msi_path), "/passive", "/norestart"],
            timeout=900,
            close_fds=True,
        )
        if result.returncode not in (0, 3010):
            print(f"[failed] MSI exit code: {result.returncode}")
            return False
        print("[안내] 설치 마법사가 열렸습니다. 설치를 완료한 후 터미널을 재시작하세요.")
        return True
    except Exception as e:
        print(f"[오류] MSI 실행 실패: {e}")
        return False


def main() -> None:
    print("=" * 50)
    print("  Vibe Coding — Node.js LTS 설치")
    print("=" * 50)

    # 이미 설치 확인
    version = check_node()
    if version:
        print(f"\n[확인] Node.js가 이미 설치되어 있습니다: {version}")

        # npm 확인
        if shutil.which("npm"):
            code, npm_ver, _ = _run(["npm", "--version"])
            if code == 0:
                print(f"[확인] npm {npm_ver}")

        print("\n✅ Node.js가 이미 사용 가능합니다.")
        return

    # winget 우선 시도
    print("\n[1단계] winget으로 설치 시도...")
    if install_via_winget():
        version = check_node()
        if version:
            print(f"\n✅ Node.js {version} 설치 완료!")
            return
        print("[주의] 설치 후 PATH 반영을 위해 터미널을 재시작하세요.")
        return

    # MSI 다운로드 폴백
    print("\n[2단계] 공식 MSI 인스톨러로 전환...")
    if install_via_msi():
        print("\n⏳ MSI 설치 마법사를 완료한 후 터미널을 재시작하세요.")
    else:
        print("\n❌ Node.js 설치에 실패했습니다.")
        print("   https://nodejs.org/ 에서 직접 다운로드하세요.")
        sys.exit(1)


if __name__ == "__main__":
    main()
