"""
FILE: tests/test_codex_orchestration.py
DESCRIPTION: Codex 라우팅과 오케스트레이터 연동 회귀 테스트.

REVISION HISTORY:
- 2026-03-27 Codex: Codex 자동 라우팅, worktree 우선 경로, 오케스트레이터 Codex 포함 검증 추가
"""

import sys
import types
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / ".ai_monitor"))

import cli_agent
import orchestrator


def test_route_task_with_reason_prefers_codex_for_narrow_test_work(monkeypatch):
    monkeypatch.setattr(cli_agent, "_load_runtime_config", lambda: {"codex_enabled": True})

    cli, reason = cli_agent.route_task_with_reason(
        "tests/test_itcp_context.py 파일에 테스트 추가하고 py_compile 검증"
    )

    assert cli == "codex"
    assert "Codex" in reason


def test_route_task_with_reason_avoids_codex_for_high_context_review(monkeypatch):
    monkeypatch.setattr(cli_agent, "_load_runtime_config", lambda: {"codex_enabled": True})

    cli, _ = cli_agent.route_task_with_reason("전체 구조 설계와 보안 리뷰를 분석해줘")

    assert cli != "codex"


def test_resolve_working_dir_prefers_terminal_worktree(monkeypatch):
    fake_worktree = types.SimpleNamespace(get_path=lambda terminal_id: r"D:\vibe-wt\T3")
    monkeypatch.setitem(sys.modules, "worktree_manager", fake_worktree)

    cwd = cli_agent._resolve_working_dir(None, "T3")

    assert cwd == r"D:\vibe-wt\T3"


def test_known_agents_includes_codex_when_enabled(monkeypatch):
    dispatcher = types.SimpleNamespace(is_codex_enabled=lambda: True)
    monkeypatch.setattr(orchestrator, "_dispatcher", dispatcher)

    agents = orchestrator._known_agents()

    assert agents == ["claude", "gemini", "codex"]


def test_pick_best_agent_uses_codex_for_test_tasks(monkeypatch):
    dispatcher = types.SimpleNamespace(
        is_codex_enabled=lambda: True,
        detect_task_type=lambda text: "test",
        score_agent=lambda agent, task_type: {
            "claude": 0.85,
            "gemini": 0.65,
            "codex": 0.9,
        }[agent],
    )
    monkeypatch.setattr(orchestrator, "_dispatcher", dispatcher)

    best = orchestrator.pick_best_agent(
        last_seen={"claude": None, "gemini": None, "codex": None},
        task_count={"claude": 0, "gemini": 0, "codex": 0, "all": 0},
        task={"title": "테스트 추가", "description": "회귀 테스트 작성"},
    )

    assert best == "codex"
