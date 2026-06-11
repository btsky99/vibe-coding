"""
FILE: tests/test_codex_orchestration.py
DESCRIPTION: Codex 라우팅과 오케스트레이터 연동 회귀 테스트.

REVISION HISTORY:
- 2026-06-11 Claude: gemini→antigravity 식별자 스윕 (agy 마이그레이션 Task 8)
- 2026-06-11 Claude: auto_dispatcher 폐기 반영 — _dispatcher 모킹 테스트 2개를
  config 기반 활성화/부하 기반 배정 검증으로 교체 (폐기 전에도 모킹 불완전으로 실패하던 테스트)
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
    # [레거시 alias] config 키 'gemini_enabled'는 입력 경계 — 본체(_known_agents)가
    # 이 키를 받아 표준 식별자 'antigravity'를 반환하는지 검증 (agy 마이그레이션 규칙)
    monkeypatch.setattr(
        orchestrator, "_load_runtime_config",
        lambda: {"gemini_enabled": True, "codex_enabled": True},
    )

    agents = orchestrator._known_agents()

    assert agents == ["claude", "antigravity", "codex"]


def test_pick_best_agent_returns_none_when_all_dead():
    # 활동 기록이 전혀 없으면 alive 후보 0명 → None (호출자가 'all' 유지)
    best = orchestrator.pick_best_agent(
        last_seen={"claude": None, "antigravity": None, "codex": None},
        task_count={"claude": 0, "antigravity": 0, "codex": 0, "all": 0},
        task={"title": "테스트 추가", "description": "회귀 테스트 작성"},
    )

    assert best is None


def test_pick_best_agent_prefers_lower_load(monkeypatch):
    # 동일 활동성이면 태스크 부하(load_penalty)가 낮은 에이전트 선택
    from datetime import datetime
    monkeypatch.setattr(
        orchestrator, "_load_runtime_config",
        lambda: {"gemini_enabled": False, "codex_enabled": True},
    )
    now_iso = datetime.now().isoformat()

    best = orchestrator.pick_best_agent(
        last_seen={"claude": now_iso, "codex": now_iso},
        task_count={"claude": 3, "codex": 0, "all": 0},
        task={"title": "테스트 추가"},
    )

    assert best == "codex"
