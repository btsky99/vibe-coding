"""
FILE: scripts/install_playwright_cli.py
DESCRIPTION: Playwright CLI 설치 + 브라우저 다운로드 — UI 검증(스크린샷 대신 Playwright 직접 확인)용.

REVISION HISTORY:
- 2026-07-30 Claude: 표준 헤더 추가 — PROJECT_MAP 설명 자동 수집(헤더 파싱)에서 유일하게 누락되던 파일.

Install Playwright CLI for the current Python interpreter and download browsers.

Usage:
    python scripts/install_playwright_cli.py
    python scripts/install_playwright_cli.py --browser chromium
    python scripts/install_playwright_cli.py --skip-browser-install
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install Playwright CLI")
    parser.add_argument(
        "--browser",
        default="chromium",
        choices=["chromium", "firefox", "webkit", "all"],
        help="Browser payload to install after the CLI package is installed.",
    )
    parser.add_argument(
        "--skip-browser-install",
        action="store_true",
        help="Install the CLI package only.",
    )
    args = parser.parse_args()

    python = sys.executable
    print(f"[playwright] using interpreter: {python}")
    print("[playwright] installing package...")
    run([python, "-m", "pip", "install", "-U", "playwright"])

    print("[playwright] verifying CLI...")
    run([python, "-m", "playwright", "--version"])
    cli_path = shutil.which("playwright")
    if cli_path:
        print(f"[playwright] playwright command detected: {cli_path}")
    else:
        print("[playwright] playwright command not found on PATH. Use: python -m playwright")

    if args.skip_browser_install:
        print("[playwright] browser install skipped.")
        return

    install_cmd = [python, "-m", "playwright", "install"]
    if args.browser != "all":
        install_cmd.append(args.browser)

    print(f"[playwright] installing browser payload: {args.browser}")
    run(install_cmd)


if __name__ == "__main__":
    main()
