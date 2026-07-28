"""
FILE: tests/test_ai_toolchain_installer.py
DESCRIPTION: Sequential AI toolchain installer regression tests.

REVISION HISTORY:
- 2026-07-29 Codex: Guard install order and already-installed skip behavior.
"""

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import install_ai_toolchain


def test_installer_skips_existing_tools_and_installs_missing_in_order():
    installed = {"claude"}
    calls = []

    def command_exists(names):
        return any(name in installed for name in names)

    def run(command, timeout):
        calls.append(command)
        installed.add({
            "@openai/codex": "codex",
            "@google/gemini-cli": "gemini",
        }.get(command[-1], "node"))
        return type("Result", (), {"returncode": 0})()

    with (
        patch.object(install_ai_toolchain, "_find_npm", return_value="npm.cmd"),
        patch.object(install_ai_toolchain, "_refresh_windows_path"),
        patch.object(install_ai_toolchain, "_command_exists", side_effect=command_exists),
        patch.object(install_ai_toolchain.subprocess, "run", side_effect=run),
    ):
        install_ai_toolchain.main()

    assert [command[-1] for command in calls] == [
        "@openai/codex",
        "@google/gemini-cli",
    ]
