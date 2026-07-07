# ────────────────────────────────────────────────────────────────────────────
# 📄 파일명: src/pg_store.py
# 📝 설명: PostgreSQL 저장소 파사드 — 분할된 pg_* 도메인 모듈을 단일 경로로 재노출
#          (실제 구현: pg_base / pg_schema / pg_memory / pg_tasks / pg_experience / pg_office)
# 🕒 변경 이력:
# [2026-06-10] Claude — 2492줄 단일 파일을 도메인 6모듈로 분할 (1500줄 규칙 준수)
#   - [호환성] 기존 60여 곳의 `from src.pg_store import X` 호출부를 깨지 않기 위해
#     모든 공개 함수 + 외부에서 쓰이는 내부 헬퍼(_sql_text, _get_pg_conn, _pool 등)를
#     여기서 재노출한다. 신규 코드는 도메인 모듈을 직접 import 해도 된다.
#   - [함정] PG_DB는 set_project_db()가 pg_base 안에서 재바인딩하는 가변 전역 —
#     이 파사드의 PG_DB 사본은 import 시점 값으로 고정된다(스테일 가능).
#     값이 필요하면 src.pg_base를 모듈로 import 해 pg_base.PG_DB로 읽을 것.
#   - [함정] 구버전의 `pg_store._SCHEMA_READY = False` 직접 대입은 분할 후 무효 —
#     reset_schema_cache()를 사용한다 (server.py 기동 2단계가 유일한 호출부였음).
# [2026-04-15 이전 이력] 분할 전 이력은 git log -- .ai_monitor/src/pg_store.py 참고
# ────────────────────────────────────────────────────────────────────────────

# ── 레거시 폴백 저장소 — infra/memory_watcher.py가 이 경로로 import ──────────
from src.file_store import (
    ensure_legacy_store,
    load_memory_entries,
    load_session_logs,
    load_skill_chain_rows,
)
from infra.project_context import assert_project_id

# ── 연결 인프라 (pg_base) ───────────────────────────────────────────────────
from src.pg_base import (
    DATA_DIR,
    PG_BIN,
    PG_PORT,
    PG_USER,
    PG_DB,           # [함정] import 시점 사본 — 최신 값은 pg_base.PG_DB
    PROJECT_ROOT,
    _ensure_pg_running,
    _get_pg_conn,
    _now_iso,
    _parse_json_text,
    _pg_conn_lock,
    _pool,
    _pool_lock,
    _run_psql,
    _sql_json,
    _sql_text,
    execute,
    execute_raw,
    get_pool_conn,
    query_rows,
    return_pool_conn,
    run_pg_sql,
    run_pg_sql_csv,
    set_project_db,
    set_pg_port,
)

# ── 스키마 DDL + 레거시 마이그레이션 (pg_schema) ────────────────────────────
from src.pg_schema import (
    ensure_schema,
    migrate_legacy_data,
    reset_schema_cache,
)

# ── 하이브 메모리 / zettel 승격 / 세션 로그 / 채팅 / 지식 회상 (pg_memory) ──
from src.pg_memory import (
    auto_promote_fleeting,
    cleanup_expired_memory,
    delete_memory,
    get_agent_last_seen,
    get_chat_context,
    get_chat_history,
    get_memory,
    list_memory,
    list_session_logs,
    preview_auto_promote,
    promote_to_zettel,
    recall_knowledge_summary,
    send_chat,
    set_memory,
    upsert_session_log,
)

# ── 태스크 / 체크아웃 / 코멘트 / 하트비트 / 상태 (pg_tasks) ─────────────────
from src.pg_tasks import (
    add_task_comment,
    atomic_checkout,
    bulk_update_tasks,
    delete_task,
    find_tasks_for_agent,
    get_task,
    list_agent_status,
    list_skill_chain_rows,
    list_task_comments,
    list_tasks,
    load_state,
    record_heartbeat,
    release_checkout,
    save_state,
    save_task,
    trigger_agent,
    update_task,
    upsert_skill_chain_row,
)

# ── 경험/성장 + 회상 + pg_logs (pg_experience) ──────────────────────────────
from src.pg_experience import (
    get_agent_stats,
    get_experience_history,
    insert_pg_log,
    recall_context_summary,
    recall_similar_experience,
    record_experience,
)

# ── 오피스 프로필 + 활성 세션 컨텍스트 (pg_office) ──────────────────────────
from src.pg_office import (
    complete_active_session,
    delete_office_profile,
    get_active_office_profile_id,
    get_interrupted_sessions,
    get_office_profile,
    list_office_profiles,
    seed_default_office_profile,
    set_active_office_profile,
    set_session_checkpoint,
    update_session_files,
    upsert_active_session,
    upsert_office_profile,
)
