"""
FILE: tests/test_codex_harness_v2.py
DESCRIPTION: Focused tests for Codex Harness V2 bootstrap and entrypoints.

REVISION HISTORY:
- 2026-03-30 Codex: Add Codex bootstrap and explicit launch path tests
"""

import sys
import types
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import agent_shell
import itcp


def test_build_project_bootstrap_includes_v2_sections(monkeypatch):
    monkeypatch.setattr(itcp, "_summarize_feature_list", lambda: "- pending: F006")
    monkeypatch.setattr(itcp, "_summarize_progress", lambda: "## latest\n진행 중:\n- [F006] Codex")
    monkeypatch.setattr(itcp, "_summarize_harness_status", lambda: "- status: ok")
    monkeypatch.setattr(itcp, "_read_context_file", lambda *args, **kwargs: "")
    monkeypatch.setattr(itcp, "_run_context_command", lambda args, **kwargs: "abc123 init" if args and args[0] == "git" else "")
    monkeypatch.setattr(itcp, "_load_runtime_config", lambda: {"codex_boot_prompt": "Validate first."})

    bootstrap = itcp._build_project_bootstrap("codex")

    assert "[Session init]" in bootstrap
    assert "[Feature status]" in bootstrap
    assert "[Progress snapshot]" in bootstrap
    assert "[Harness status]" in bootstrap
    assert "[Recent commits]" in bootstrap
    assert "[Local codex operator prompt]" in bootstrap


def test_prepare_codex_context_reuses_project_bootstrap(monkeypatch):
    fake_itcp = types.SimpleNamespace(
        receive=lambda *args, **kwargs: [{"content": "fix bug", "channel": "task"}],
        parse_task_reference=lambda message: {"task_id": "TASK-1", "kind": "task"},
        build_agent_context=lambda *args, **kwargs: "[Project bootstrap]\nRULES.md summary",
    )
    monkeypatch.setitem(sys.modules, "itcp", fake_itcp)

    prompt, task_refs, review_refs = agent_shell._prepare_codex_context("Implement the fix.")

    assert "[Project bootstrap]" in prompt
    assert prompt.endswith("Implement the fix.")
    assert task_refs == [{"task_id": "TASK-1", "kind": "task"}]
    assert review_refs == []


def test_run_agent_honors_explicit_codex_even_when_orchestration_default(monkeypatch):
    launched = {}

    class FakeProc:
        def __init__(self):
            self.stdout = self
            self.returncode = 0
            self.pid = 1234

        def readline(self):
            return b""

        def wait(self):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(agent_shell, "_prepare_codex_context", lambda task: (task, [], []))
    monkeypatch.setattr(agent_shell, "_write_live", lambda event: None)

    def fake_popen(cmd, **kwargs):
        launched["cmd"] = cmd
        launched["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr(agent_shell.subprocess, "Popen", fake_popen)

    rc = agent_shell.run_agent("tests/test_itcp_context.py update", cli="codex", terminal_id="T7")

    assert rc == 0
    assert "codex" in str(launched["cmd"]).lower()
    assert "exec" in str(launched["cmd"]).lower()

