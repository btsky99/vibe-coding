# -*- coding: utf-8 -*-
"""
FILE: tests/test_pg_store_split.py
DESCRIPTION: pg_store.py 분할(2026-06-10) 회귀 방지 테스트.
             파사드 재노출 전수 검증 + 순수 헬퍼 단위 테스트 + 1500줄 규칙 검증.
             PostgreSQL 연결이 필요한 함수는 호출하지 않는다 (import 계약만 검증).

REVISION HISTORY:
- 2026-06-10 Claude: 최초 작성 — pg_store 6모듈 분할 직후 호환성 안전망
"""

import sys
from pathlib import Path

import pytest

# ── 프로젝트 경로 설정 ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_AI_MONITOR = _PROJECT_ROOT / ".ai_monitor"
sys.path.insert(0, str(_AI_MONITOR))


# ── 1. 파사드 재노출 계약 ────────────────────────────────────────────────────
# 분할 전 `from src.pg_store import X`로 쓰이던 외부 호출부 전수 조사 결과(grep).
# 여기서 하나라도 빠지면 60여 개 호출부 중 어딘가가 ImportError로 죽는다.
FACADE_NAMES = [
    # pg_base — 연결 인프라
    'ensure_schema', 'reset_schema_cache', 'migrate_legacy_data',
    'query_rows', 'execute', 'execute_raw', 'set_project_db',
    'get_pool_conn', 'return_pool_conn', '_pool', '_pool_lock',
    '_get_pg_conn', '_sql_text', '_sql_json', '_now_iso',
    # pg_memory
    'list_memory', 'get_memory', 'set_memory', 'delete_memory',
    'promote_to_zettel', 'auto_promote_fleeting', 'preview_auto_promote',
    'cleanup_expired_memory', 'upsert_session_log', 'list_session_logs',
    'get_agent_last_seen', 'send_chat', 'get_chat_history', 'get_chat_context',
    'recall_knowledge_summary',
    # pg_tasks
    'save_task', 'list_tasks', 'get_task', 'update_task', 'delete_task',
    'bulk_update_tasks', 'save_state', 'load_state',
    'upsert_skill_chain_row', 'list_skill_chain_rows',
    'atomic_checkout', 'release_checkout', 'find_tasks_for_agent',
    'add_task_comment', 'list_task_comments',
    'record_heartbeat', 'list_agent_status', 'trigger_agent',
    # pg_experience
    'record_experience', 'get_agent_stats', 'get_experience_history',
    'recall_similar_experience', 'recall_context_summary', 'insert_pg_log',
    # pg_office
    'seed_default_office_profile', 'list_office_profiles', 'get_office_profile',
    'upsert_office_profile', 'delete_office_profile',
    'get_active_office_profile_id', 'set_active_office_profile',
    'upsert_active_session', 'update_session_files', 'complete_active_session',
    'get_interrupted_sessions',
    # file_store 경유 재노출 — infra/memory_watcher.py가 pg_store에서 import
    'ensure_legacy_store',
]


def test_facade_reexports_all_legacy_names():
    import src.pg_store as ps
    missing = [n for n in FACADE_NAMES if not hasattr(ps, n)]
    assert not missing, f"파사드 재노출 누락: {missing}"


def test_domain_modules_importable():
    import src.pg_base
    import src.pg_schema
    import src.pg_memory
    import src.pg_tasks
    import src.pg_experience
    import src.pg_office


# ── 2. 순수 헬퍼 단위 테스트 (DB 불필요) ─────────────────────────────────────

def test_sql_text_escapes_quotes():
    from src.pg_base import _sql_text
    assert _sql_text("abc") == "'abc'"
    assert _sql_text("o'brien") == "'o''brien'"
    assert _sql_text(None) == 'NULL'
    assert _sql_text(42) == "'42'"


def test_sql_json_produces_jsonb_literal():
    from src.pg_base import _sql_json
    assert _sql_json({"한글": 1}) == "'{\"한글\": 1}'::jsonb"
    assert _sql_json([]) == "'[]'::jsonb"


def test_parse_json_text_fallbacks():
    from src.pg_base import _parse_json_text
    assert _parse_json_text('', []) == []
    assert _parse_json_text(None, {}) == {}
    assert _parse_json_text('{"a": 1}', {}) == {"a": 1}
    assert _parse_json_text('깨진 json', 'dflt') == 'dflt'
    assert _parse_json_text({'이미': 'dict'}, {}) == {'이미': 'dict'}


def test_calc_level_formula():
    from src.pg_experience import _calc_level
    assert _calc_level(0) == 1      # 최소 레벨 1 보장
    assert _calc_level(100) == 1
    assert _calc_level(400) == 2    # floor(sqrt(4)) = 2
    assert _calc_level(10000) == 10


def test_reset_schema_cache_clears_flag():
    import src.pg_schema as schema
    schema._SCHEMA_READY = True
    schema.reset_schema_cache()
    assert schema._SCHEMA_READY is False


# ── 3. 1500줄 규칙 (CLAUDE.md 절대 규칙 2) ──────────────────────────────────

@pytest.mark.parametrize("module_file", [
    "pg_store.py", "pg_base.py", "pg_schema.py",
    "pg_memory.py", "pg_tasks.py", "pg_experience.py", "pg_office.py",
])
def test_module_under_1500_lines(module_file):
    path = _AI_MONITOR / "src" / module_file
    n_lines = len(path.read_text(encoding='utf-8').splitlines())
    assert n_lines <= 1500, f"{module_file}: {n_lines}줄 — 1500줄 규칙 위반"
