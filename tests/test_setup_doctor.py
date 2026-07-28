"""
FILE: tests/test_setup_doctor.py
DESCRIPTION: Setup Doctor AI CLI detection regression tests.

REVISION HISTORY:
- 2026-07-28 Codex: Cover partially and fully installed AI CLI states.
"""

import sys
from pathlib import Path
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / ".ai_monitor"))

from setup_doctor import check_cli_agents


def test_partial_cli_installation_requires_action():
    def fake_which(command: str):
        return "C:/tools/claude.cmd" if command in {"claude", "claude.cmd"} else None

    with patch("setup_doctor.shutil.which", side_effect=fake_which):
        result = check_cli_agents()

    assert result["status"] == "missing"
    assert result["action"] == "install_cli"
    assert "codex" in result["message"]
    assert "antigravity" in result["message"]


def test_all_cli_installations_are_ready():
    with patch("setup_doctor.shutil.which", return_value="C:/tools/agent.cmd"):
        result = check_cli_agents()

    assert result["status"] == "ok"
    assert "action" not in result


def test_gemini_command_satisfies_antigravity_compatibility():
    available = {"claude", "codex", "gemini"}

    with patch(
        "setup_doctor.shutil.which",
        side_effect=lambda command: f"C:/tools/{command}.cmd" if command in available else None,
    ):
        result = check_cli_agents()

    assert result["status"] == "ok"
