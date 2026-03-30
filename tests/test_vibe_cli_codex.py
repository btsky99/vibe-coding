"""
FILE: tests/test_vibe_cli_codex.py
DESCRIPTION: Tests for Codex-specific vibe CLI helpers.

REVISION HISTORY:
- 2026-03-30 Codex: Add global Codex install detection coverage
"""

import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import vibe_cli


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_check_codex_install_detects_global_cli(monkeypatch):
    monkeypatch.setattr(vibe_cli.shutil, "which", lambda name: r"C:\Users\com\AppData\Roaming\npm\codex.cmd" if name in {"codex", "codex.cmd"} else None)

    def fake_run(cmd, **kwargs):
        if cmd[0] == "node":
            return _Result(stdout="v22.0.0")
        return _Result(stdout="codex-cli 0.117.0")

    monkeypatch.setattr(vibe_cli.subprocess, "run", fake_run)

    status = vibe_cli._check_codex_install()

    assert status["node"] is True
    assert status["codex"] is True
    assert status["path"].endswith("codex.cmd")
    assert status["version"] == "codex-cli 0.117.0"

