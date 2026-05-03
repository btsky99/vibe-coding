"""
FILE: tests/test_orchestrator_monitor.py
DESCRIPTION: Regression tests for orchestration monitor data adapters.

REVISION HISTORY:
- 2026-05-03 Codex: Added coverage for project-scoped PTY keys and port discovery.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MONITOR_DIR = ROOT / ".ai_monitor"
SCRIPTS_DIR = ROOT / "scripts"
for path in (MONITOR_DIR, SCRIPTS_DIR):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)


from api.hive_api import _merge_live_pty_skill_chains, _pty_slot_info
import orchestrator


def test_pty_slot_info_reads_project_scoped_keys():
    sessions = {
        "T1@D--vibe-coding": {
            "running": True,
            "agent": "claude",
            "project_id": "D--vibe-coding",
        },
        "T1": {"running": False, "agent": ""},
    }

    info = _pty_slot_info(sessions, 1, "D--vibe-coding")

    assert info is not None
    assert info["agent"] == "claude"


def test_skill_chain_merges_live_project_scoped_pty_sessions():
    sessions = {
        "T2@D--vibe-coding": {
            "running": True,
            "agent": "codex",
            "started": "2026-05-03T03:51:43.715Z",
            "last_line": "working",
            "project_id": "D--vibe-coding",
        }
    }

    result = _merge_live_pty_skill_chains(
        {"skill_registry": [], "terminals": {}},
        sessions,
    )

    assert result["terminals"]["2"]["agent"] == "codex"
    assert result["terminals"]["2"]["steps"][0]["status"] == "running"
    assert result["skill_registry"][0]["name"] == "vibe-orchestrate"


def test_orchestrator_detects_current_server_port():
    assert 9000 in orchestrator.DEFAULT_PORTS
