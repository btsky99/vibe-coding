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
