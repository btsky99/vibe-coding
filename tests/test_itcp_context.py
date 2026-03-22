import os
import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import itcp


def test_build_agent_context_includes_unread_and_debate(monkeypatch):
    monkeypatch.setattr(
        itcp,
        "receive",
        lambda agent_name, mark_read=True: [
            {
                "from_agent": "dispatcher",
                "channel": "task",
                "content": "write tests",
            }
        ],
    )
    monkeypatch.setenv("HIVE_DEBATE_CONTEXT", '{"topic":"codex review"}')

    context = itcp.build_agent_context("codex")

    assert "[ITCP inbox]" in context
    assert "dispatcher" in context
    assert "write tests" in context
    assert "[Hive debate context]" in context
    assert "codex review" in context


def test_build_agent_context_can_include_project_bootstrap(monkeypatch):
    monkeypatch.setattr(itcp, "_build_project_bootstrap", lambda agent_name: "RULES.md summary")
    monkeypatch.setattr(itcp, "receive", lambda *args, **kwargs: [])
    monkeypatch.delenv("HIVE_DEBATE_CONTEXT", raising=False)

    context = itcp.build_agent_context("codex", include_project_bootstrap=True)

    assert "[Project bootstrap]" in context
    assert "RULES.md summary" in context


def test_project_bootstrap_includes_local_codex_prompt(monkeypatch):
    monkeypatch.setattr(itcp, "_read_context_file", lambda *args, **kwargs: "")
    monkeypatch.setattr(itcp, "_run_context_command", lambda *args, **kwargs: "")
    monkeypatch.setattr(itcp, "_load_runtime_config", lambda: {"codex_boot_prompt": "Stay narrow and validate first."})

    bootstrap = itcp._build_project_bootstrap("codex")

    assert "[Local codex operator prompt]" in bootstrap
    assert "Stay narrow and validate first." in bootstrap


def test_inject_agent_context_wraps_task(monkeypatch):
    monkeypatch.setattr(itcp, "build_agent_context", lambda *args, **kwargs: "[ITCP inbox]\n- [claude -> codex] (task) fix bug")

    prompt = itcp.inject_agent_context("Implement the assigned task.", "codex")

    assert prompt.startswith("[ITCP inbox]")
    assert "[Assigned task]" in prompt
    assert prompt.endswith("Implement the assigned task.")


def test_inject_agent_context_returns_original_task_when_empty(monkeypatch):
    monkeypatch.setattr(itcp, "build_agent_context", lambda *args, **kwargs: "")

    prompt = itcp.inject_agent_context("No extra context task", "codex")

    assert prompt == "No extra context task"
