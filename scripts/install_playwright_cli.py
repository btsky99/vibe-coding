"""
Install Playwright CLI for the current Python interpreter and download browsers.

Usage:
    python scripts/install_playwright_cli.py
    python scripts/install_playwright_cli.py --browser chromium
    python scripts/install_playwright_cli.py --skip-browser-install
"""

from __future__ import annotations

import argparse
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
