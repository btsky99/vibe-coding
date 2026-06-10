# ────────────────────────────────────────────────────────────────────────────
# 📄 파일명: src/pg_office.py
# 📝 설명: 오피스 프로필 CRUD(PostgreSQL SSOT) + 활성 세션 컨텍스트(크래시 복구)
#          (pg_store.py 분할 6/6)
# 🕒 변경 이력:
# [2026-06-10] Claude — pg_store.py 분할로 신설 (1500줄 규칙 준수)
# ────────────────────────────────────────────────────────────────────────────
from infra.project_context import assert_project_id
from src.pg_base import _sql_text, execute, query_rows


# ── 오피스 프로필 CRUD ──────────────────────────────────────────────────────
#
# 메인 창(pywebview)과 오피스 창(QWebEngineView)은 서로 다른 브라우저 엔진이라
# localStorage가 공유되지 않는다. 프로필은 서버 DB에서만 관리한다.

# 기본 프로필 시드 스키마 버전 — 이 값을 올리면 재시드 시 기본 프로필의 모델/역할이
# 자동 업그레이드된다. 사용자가 생성한 커스텀 프로필은 절대 건드리지 않는다.
_OFFICE_PROFILE_SCHEMA_VERSION = 2  # v2: Gemini 3.1 / GPT-5.3-Codex 최신 모델 반영

# 기본 프로필 씨드 — 경영진(대표) + 코딩 부서. useWorkspaceProfiles.ts의 DEFAULT_PROFILE과 동일
_DEFAULT_OFFICE_PROFILE = {
    "id": "default",
    "name": "코딩 회사",
    "isDefault": True,
    "schemaVersion": _OFFICE_PROFILE_SCHEMA_VERSION,
    "createdAt": "2026-04-08T00:00:00.000Z",
    "departments": [
        {
            "id": "dept-exec",
            "name": "경영진",
            "color": "#fbbf24",
            "icon": "crown",
            "agents": [
                {"id": "ceo", "name": "대표 (지휘자)", "role": "ceo",
                 "cli": "claude", "model": "claude-opus-4-6",
                 "skills": ["orchestrate", "brainstorm", "write-plan"],
                 "avatar": "crown", "yolo": True, "order": 0},
            ],
        },
        {
            "id": "dept-coding",
            "name": "코딩 부서",
            "color": "#22d3ee",
            "icon": "code-2",
            "agents": [
                {"id": "a1", "name": "기획자",     "role": "planner",   "cli": "claude", "model": "claude-opus-4-6",   "skills": ["brainstorm", "write-plan"], "avatar": "clipboard-list", "yolo": True, "order": 0},
                {"id": "a2", "name": "아키텍트",   "role": "architect", "cli": "claude", "model": "claude-opus-4-6",   "skills": ["brainstorm"],               "avatar": "blocks",         "yolo": True, "order": 1},
                {"id": "a3", "name": "프론트엔드", "role": "frontend",  "cli": "gemini", "model": "gemini-3.1-pro",       "skills": ["code"],                     "avatar": "monitor",        "yolo": True, "order": 2},
                {"id": "a4", "name": "백엔드",     "role": "backend",   "cli": "claude", "model": "claude-sonnet-4-6",    "skills": ["code"],                     "avatar": "server",         "yolo": True, "order": 3},
                {"id": "a5", "name": "풀스택",     "role": "fullstack", "cli": "gemini", "model": "gemini-3.1-flash",     "skills": ["code"],                     "avatar": "layers",         "yolo": True, "order": 4},
                {"id": "a6", "name": "코드 리뷰어","role": "reviewer",  "cli": "claude", "model": "claude-opus-4-6",      "skills": ["code-review"],              "avatar": "search-check",   "yolo": True, "order": 5},
                {"id": "a7", "name": "QA 테스터",  "role": "qa",        "cli": "codex",  "model": "gpt-5.3-codex-spark",  "skills": ["tdd"],                      "avatar": "test-tubes",     "yolo": True, "order": 6},
                {"id": "a8", "name": "보안 담당",  "role": "security",  "cli": "claude", "model": "claude-opus-4-6",      "skills": ["security"],                 "avatar": "shield",         "yolo": True, "order": 7},
                {"id": "a9", "name": "DevOps",     "role": "devops",    "cli": "codex",  "model": "gpt-5.3-codex",        "skills": ["release"],                  "avatar": "wrench",         "yolo": True, "order": 8},
            ],
        },
    ],
}


def seed_default_office_profile() -> bool:
    """기본 프로필을 시드 또는 업그레이드한다.

    - 최초 실행: 'default' 프로필을 그대로 INSERT.
    - 재실행: 'default' 프로필의 schemaVersion이 현재 버전보다 낮으면 data를 덮어쓴다.
              사용자가 생성한 다른 프로필은 절대 건드리지 않는다.
              'default' 프로필을 사용자가 직접 수정했더라도, 기본 시드는 진실의 원천이
              바뀐 경우(예: 구버전 모델 → 최신 모델) 자동 최신화되는 편이 안전하다.
    """
    import json as _json
    data_json = _json.dumps(_DEFAULT_OFFICE_PROFILE, ensure_ascii=False)

    # 현재 저장된 'default' 프로필의 schemaVersion 확인
    rows = query_rows(
        "SELECT (data->>'schemaVersion')::int AS v FROM office_profiles WHERE id = 'default';"
    )
    if not rows:
        # 최초 시드
        return execute(
            f"INSERT INTO office_profiles (id, name, data, is_default) "
            f"VALUES ('default', {_sql_text(_DEFAULT_OFFICE_PROFILE['name'])}, "
            f"{_sql_text(data_json)}::jsonb, TRUE) "
            f"ON CONFLICT (id) DO NOTHING;"
        )

    current_version = rows[0].get('v') or 0
    if current_version < _OFFICE_PROFILE_SCHEMA_VERSION:
        # 기본 프로필 데이터 업그레이드 (모델명 등 최신화)
        print(f"[pg_store] 기본 오피스 프로필 업그레이드: v{current_version} → v{_OFFICE_PROFILE_SCHEMA_VERSION}")
        return execute(
            f"UPDATE office_profiles SET "
            f"data = {_sql_text(data_json)}::jsonb, "
            f"name = {_sql_text(_DEFAULT_OFFICE_PROFILE['name'])}, "
            f"updated_at = NOW() "
            f"WHERE id = 'default';"
        )
    return True


def list_office_profiles() -> list[dict]:
    """전체 오피스 프로필 목록 + 활성 프로필 ID 반환.

    반환 형식: [{"id", "name", "data", "is_default", "created_at", "updated_at"}, ...]
    data 필드는 JSON 문자열이 아닌 파싱된 dict이다.
    """
    import json as _json
    rows = query_rows(
        "SELECT id, name, data::text AS data, is_default, "
        "to_char(created_at, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS created_at, "
        "to_char(updated_at, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS updated_at "
        "FROM office_profiles ORDER BY is_default DESC, created_at ASC;"
    )
    for r in rows:
        try:
            r['data'] = _json.loads(r.get('data') or '{}')
        except Exception:
            r['data'] = {}
    return rows


def get_office_profile(profile_id: str) -> dict | None:
    """단일 프로필 조회."""
    import json as _json
    rows = query_rows(
        f"SELECT id, name, data::text AS data, is_default, "
        f"to_char(created_at, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS created_at, "
        f"to_char(updated_at, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS updated_at "
        f"FROM office_profiles WHERE id = {_sql_text(profile_id)} LIMIT 1;"
    )
    if not rows:
        return None
    r = rows[0]
    try:
        r['data'] = _json.loads(r.get('data') or '{}')
    except Exception:
        r['data'] = {}
    return r


def upsert_office_profile(profile_id: str, name: str, data: dict,
                           is_default: bool = False) -> bool:
    """프로필 생성 또는 전체 대체. data는 departments를 포함한 전체 JSON."""
    import json as _json
    data_json = _json.dumps(data, ensure_ascii=False)
    return execute(
        f"INSERT INTO office_profiles (id, name, data, is_default, updated_at) "
        f"VALUES ({_sql_text(profile_id)}, {_sql_text(name)}, "
        f"{_sql_text(data_json)}::jsonb, {'TRUE' if is_default else 'FALSE'}, NOW()) "
        f"ON CONFLICT (id) DO UPDATE SET "
        f"name = EXCLUDED.name, data = EXCLUDED.data, updated_at = NOW();"
    )


def delete_office_profile(profile_id: str) -> bool:
    """프로필 삭제. 기본 프로필은 삭제 불가 (is_default=TRUE 제외)."""
    return execute(
        f"DELETE FROM office_profiles "
        f"WHERE id = {_sql_text(profile_id)} AND is_default = FALSE;"
    )


def get_active_office_profile_id() -> str:
    """현재 활성 프로필 ID."""
    rows = query_rows("SELECT active_profile_id FROM office_profile_state WHERE id = 1 LIMIT 1;")
    if rows:
        return rows[0].get('active_profile_id') or 'default'
    return 'default'


def set_active_office_profile(profile_id: str) -> bool:
    """활성 프로필 변경 — 싱글톤 레코드 업데이트."""
    return execute(
        f"UPDATE office_profile_state SET active_profile_id = {_sql_text(profile_id)}, "
        f"updated_at = NOW() WHERE id = 1;"
    )


# ── 활성 세션 컨텍스트 (크래시 복구) ─────────────────────────────────────────

def upsert_active_session(terminal_id: str, agent_id: str, task_summary: str,
                          modified_files: list | None = None,
                          project_id: str = '') -> bool:
    """현재 작업 컨텍스트를 DB에 기록/갱신한다.

    매 UserPromptSubmit/PostToolUse마다 호출되어 최신 상태를 유지.
    동일 terminal_id + status='active' 레코드를 덮어쓰기(UPSERT).
    """
    project_id = assert_project_id(project_id, 'upsert_active_session')
    import json as _json
    files_json = _json.dumps(modified_files or [], ensure_ascii=False)

    # 기존 active 레코드가 있으면 업데이트, 없으면 새로 생성
    existing = query_rows(
        f"SELECT id FROM active_session_context "
        f"WHERE terminal_id = {_sql_text(terminal_id)} AND status = 'active' "
        f"LIMIT 1;"
    )
    if existing:
        return execute(
            f"UPDATE active_session_context SET "
            f"task_summary = {_sql_text(task_summary)}, "
            f"modified_files = {_sql_text(files_json)}::jsonb, "
            f"project_id = {_sql_text(project_id)}, "
            f"updated_at = NOW() "
            f"WHERE id = {existing[0]['id']};"
        )
    else:
        return execute(
            f"INSERT INTO active_session_context "
            f"(terminal_id, agent_id, task_summary, modified_files, status, project_id) "
            f"VALUES ({_sql_text(terminal_id)}, {_sql_text(agent_id)}, "
            f"{_sql_text(task_summary)}, {_sql_text(files_json)}::jsonb, 'active', "
            f"{_sql_text(project_id)});"
        )


def update_session_files(terminal_id: str, file_path: str) -> bool:
    """활성 세션의 수정 파일 목록에 파일을 추가한다.

    PostToolUse에서 Edit/Write 완료 시 호출.
    jsonb_set으로 기존 배열에 추가 (중복 방지).
    """
    return execute(
        f"UPDATE active_session_context SET "
        f"modified_files = CASE "
        f"  WHEN NOT modified_files @> to_jsonb({_sql_text(file_path)}::text) "
        f"  THEN modified_files || to_jsonb({_sql_text(file_path)}::text) "
        f"  ELSE modified_files END, "
        f"updated_at = NOW() "
        f"WHERE terminal_id = {_sql_text(terminal_id)} AND status = 'active';"
    )


def complete_active_session(terminal_id: str) -> bool:
    """활성 세션을 완료 처리한다. Stop 이벤트에서 호출."""
    return execute(
        f"UPDATE active_session_context SET status = 'done', updated_at = NOW() "
        f"WHERE terminal_id = {_sql_text(terminal_id)} AND status = 'active';"
    )


def get_interrupted_sessions(terminal_id: str = '') -> list[dict]:
    """미완료(active) 상태인 세션 목록을 반환한다.

    새 세션 시작 시 UserPromptSubmit에서 호출.
    terminal_id 필터는 선택적 — 빈 문자열이면 모든 터미널의 중단 세션 반환.
    """
    where = f"WHERE status = 'active'"
    if terminal_id:
        where += f" AND terminal_id = {_sql_text(terminal_id)}"
    return query_rows(
        f"SELECT id, terminal_id, agent_id, task_summary, "
        f"modified_files::text, status, started_at, updated_at "
        f"FROM active_session_context {where} "
        f"ORDER BY updated_at DESC LIMIT 5;"
    )
