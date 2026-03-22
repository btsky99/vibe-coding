import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import auto_dispatcher
import itcp


def test_parse_task_reference_extracts_metadata_and_kind():
    message = {
        "channel": "review",
        "content": "[CROSS-VERIFY] review request",
        "from_agent": "dispatcher",
        "to_agent": "claude",
        "metadata": {
            "task_id": "TASK-20260317-abc123",
            "author": "codex",
        },
    }

    ref = itcp.parse_task_reference(message)

    assert ref["kind"] == "review"
    assert ref["task_id"] == "TASK-20260317-abc123"
    assert ref["author"] == "codex"


def test_report_task_completion_sends_task_result_and_requests_verify(monkeypatch):
    sent = []

    monkeypatch.setattr(itcp, "send", lambda **kwargs: sent.append(kwargs) or True)
    monkeypatch.setattr(
        auto_dispatcher,
        "request_verification",
        lambda task_id, result_summary, author: {
            "task_id": task_id,
            "author": author,
            "status": "verification_requested",
        },
    )

    result = auto_dispatcher.report_task_completion(
        "TASK-20260317-abc123",
        "codex",
        "implemented tests",
    )

    assert result["status"] == "completed"
    assert sent[0]["to_terminal"] == "dispatcher"
    assert sent[0]["channel"] == "task"
    assert sent[0]["metadata"]["task_id"] == "TASK-20260317-abc123"


def test_report_verification_result_sends_dispatcher_and_author(monkeypatch):
    sent = []

    monkeypatch.setattr(itcp, "send", lambda **kwargs: sent.append(kwargs) or True)

    result = auto_dispatcher.report_verification_result(
        "TASK-20260317-abc123",
        "claude",
        "looks good",
        verdict="approved",
        author="codex",
    )

    assert result["status"] == "verified"
    assert len(sent) == 2
    assert sent[0]["to_terminal"] == "dispatcher"
    assert sent[1]["to_terminal"] == "codex"


def test_select_best_agent_excludes_codex_for_high_context_work():
    agent = auto_dispatcher.select_best_agent("architecture", exclude=["codex"])
    assert agent != "codex"


def test_select_best_agent_respects_local_codex_disable(monkeypatch):
    monkeypatch.setattr(auto_dispatcher, "is_codex_enabled", lambda: False)

    agent = auto_dispatcher.select_best_agent("test")

    assert agent != "codex"


def test_dispatch_avoids_codex_for_review_tasks(monkeypatch):
    sent = []
    broadcasts = []

    monkeypatch.setattr(auto_dispatcher.itcp, "send", lambda **kwargs: sent.append(kwargs) or True)
    monkeypatch.setattr(auto_dispatcher.itcp, "broadcast", lambda **kwargs: broadcasts.append(kwargs) or True)
    monkeypatch.setattr(auto_dispatcher, "_save_dispatch_to_hive_tasks", lambda payload: None)
    monkeypatch.setattr(auto_dispatcher, "is_codex_enabled", lambda: True)

    result = auto_dispatcher.dispatch("이 변경 리뷰해줘", task_type="review")

    assert result["assigned_to"] != "codex"
    assert result["verifier"] != "codex"
