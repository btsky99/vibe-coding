"""
FILE: tests/test_ai_toolchain_installer.py
DESCRIPTION: Sequential AI toolchain installer regression tests.

REVISION HISTORY:
- 2026-07-29 Codex: Require official Antigravity installer after npm-based CLIs.
- 2026-07-29 Codex: Guard synchronous Node MSI fallback before dependent installs.
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

    # [🔴 **kwargs 를 받는다 — 2026-08-17] 설치 스크립트가 규칙 10에 맞춰
    #   무창 실행기(_install_common.run → infra.proc.run)를 거치면서
    #   creationflags 가 함께 넘어온다. 가짜가 좁으면 **규칙을 지킨 쪽이 깨진다** —
    #   가짜는 진짜의 호출 규약을 따라가야 한다.
    def run(command, timeout=None, **_kwargs):
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

    assert [command[-1] for command in calls[:1]] == [
        "@openai/codex",
    ]
    assert calls[1][-1].endswith("install_antigravity.py")


def test_node_msi_fallback_waits_for_completion():
    source = (ROOT / "scripts" / "install_nodejs.py").read_text(encoding="utf-8")

    assert '"/passive", "/norestart"' in source
    assert 'subprocess.Popen(["msiexec"' not in source
