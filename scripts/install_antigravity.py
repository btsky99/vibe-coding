"""
FILE: scripts/install_antigravity.py
DESCRIPTION: Install Google's official Antigravity CLI (`agy`).

REVISION HISTORY:
- 2026-07-29 Codex: Add official Antigravity CLI installation.
"""

from __future__ import annotations

import os
import shutil
import subprocess


def main() -> None:
    if shutil.which("agy") or shutil.which("agy.exe"):
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
    print("[complete] Antigravity CLI installation finished.")


if __name__ == "__main__":
    main()
