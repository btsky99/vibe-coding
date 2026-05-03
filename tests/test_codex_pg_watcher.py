"""
FILE: tests/test_codex_pg_watcher.py
DESCRIPTION: Tests for mirroring Codex CLI history into pg_logs.

REVISION HISTORY:
- 2026-05-03 Codex: Add coverage for Codex history sync dedupe and logging.
"""

import json
import sys
import types
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import codex_pg_watcher


def test_read_history_parses_valid_entries(tmp_path):
    history = tmp_path / "history.jsonl"
    history.write_text(
        "\n".join([
            json.dumps({"session_id": "s1", "ts": 1, "text": "  hello   codex  "}),
            "not-json",
            json.dumps({"session_id": "", "ts": 2, "text": "skip"}),
        ]),
        encoding="utf-8",
    )

    entries = codex_pg_watcher.read_history(history)

    assert len(entries) == 1
    assert entries[0].session_id == "s1"
    assert entries[0].text == "hello codex"


def test_sync_once_logs_unseen_entries_once(monkeypatch, tmp_path):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "history.jsonl").write_text(
        json.dumps({"session_id": "s1", "ts": 10, "text": "fix the bug"}) + "\n",
        encoding="utf-8",
    )
    state_path = tmp_path / "state.json"
    calls = []

    fake_project_context = types.SimpleNamespace(slugify=lambda root: "D--vibe-coding")
    fake_pg_store = types.SimpleNamespace(insert_pg_log=lambda **kwargs: calls.append(kwargs))
    monkeypatch.setitem(sys.modules, "infra", types.SimpleNamespace(project_context=fake_project_context))
    monkeypatch.setitem(sys.modules, "src", types.SimpleNamespace(pg_store=fake_pg_store))
    monkeypatch.setitem(sys.modules, "infra.project_context", fake_project_context)
    monkeypatch.setitem(sys.modules, "src.pg_store", fake_pg_store)

    assert codex_pg_watcher.sync_once(codex_home=codex_home, state_path=state_path) == 1
    assert codex_pg_watcher.sync_once(codex_home=codex_home, state_path=state_path) == 0

    assert len(calls) == 1
    assert calls[0]["agent"] == "Codex"
    assert calls[0]["terminal_id"] == "CODEX"
    assert calls[0]["metadata"]["source"] == "codex_history"


def test_read_session_events_extracts_tool_and_completion(tmp_path):
    codex_home = tmp_path / ".codex"
    session_dir = codex_home / "sessions" / "2026" / "05" / "03"
    session_dir.mkdir(parents=True)
    session_file = session_dir / "rollout-test.jsonl"
    session_file.write_text(
        "\n".join([
            json.dumps({
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "shell_command",
                    "arguments": json.dumps({"command": "pytest tests/test_codex_pg_watcher.py"}),
                    "call_id": "c1",
                },
            }),
            json.dumps({
                "type": "event_msg",
                "payload": {
                    "type": "exec_command_end",
                    "call_id": "c1",
                    "command": ["pytest", "tests/test_codex_pg_watcher.py"],
                    "exit_code": 0,
                },
            }),
            json.dumps({
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "phase": "final",
                    "content": [{"type": "output_text", "text": "done"}],
                },
            }),
        ]),
        encoding="utf-8",
    )

    events = codex_pg_watcher.read_session_events(codex_home)

    assert [event.status for event in events] == ["started", "success", "success"]
    assert events[0].metadata["event"] == "function_call"
    assert events[1].metadata["event"] == "exec_command_end"
    assert events[2].metadata["event"] == "assistant_final"
