# ────────────────────────────────────────────────────────────────────────────
# 📄 파일명: src/pg_tasks.py
# 📝 설명: 하이브 태스크(hive_tasks) CRUD + 원자적 체크아웃 + 코멘트 + 하트비트 + 상태 저장
#          (pg_store.py 분할 4/6)
# 🕒 변경 이력:
# [2026-06-10] Claude — pg_store.py 분할로 신설 (1500줄 규칙 준수)
#   - [제약] atomic_checkout/trigger_agent는 _get_pg_conn()을 락 없이 직접 호출
#     (분할 전부터의 동작 유지) — psycopg2 autocommit 커넥션 전제.
# ────────────────────────────────────────────────────────────────────────────
import threading

from infra.project_context import assert_project_id
from src.pg_base import (
    _get_pg_conn,
    _now_iso,
    _parse_json_text,
    _sql_json,
    _sql_text,
    execute,
    query_rows,
)


def save_task(task: dict, project_id: str = '', source: str = 'classic') -> dict | None:
    task_id = str(task.get('id', '')).strip()
    if not task_id:
        return None
    # task dict 안에 project_id/source가 있으면 우선 사용, 없으면 파라미터 사용
    _proj_id = str(task.get('project_id', '') or project_id)
    _proj_id = assert_project_id(_proj_id, 'save_task')
    _source = str(task.get('source', '') or source)
    payload = {
        'timestamp': str(task.get('timestamp', '') or task.get('created_at', '') or _now_iso()),
        'updated_at': str(task.get('updated_at', '') or _now_iso()),
        'title': str(task.get('title', '')),
        'description': str(task.get('description', '')),
        'status': str(task.get('status', 'pending')),
        'assigned_to': str(task.get('assigned_to', 'all')),
        'priority': str(task.get('priority', 'medium')),
        'created_by': str(task.get('created_by', 'user')),
        'kanban_status': str(task.get('kanban_status', 'todo')),
        'role': str(task.get('role', '')),
        'claimed_by': str(task.get('claimed_by', '')),
        'tags': task.get('tags', []),
        'project_id': _proj_id,
        'source': _source,
    }
    extra = {
        k: v for k, v in task.items()
        if k not in {'id', 'timestamp', 'updated_at', 'title', 'description', 'status', 'assigned_to',
                     'priority', 'created_by', 'kanban_status', 'role', 'claimed_by', 'tags', 'project_id',
                     'source'}
    }
    execute(
        f"""
        INSERT INTO hive_tasks
            (id, timestamp, updated_at, title, description, status, assigned_to, priority,
             created_by, kanban_status, role, claimed_by, tags, extra, project_id, source)
        VALUES (
            {_sql_text(task_id)}, {_sql_text(payload['timestamp'])}, {_sql_text(payload['updated_at'])},
            {_sql_text(payload['title'])}, {_sql_text(payload['description'])}, {_sql_text(payload['status'])},
            {_sql_text(payload['assigned_to'])}, {_sql_text(payload['priority'])}, {_sql_text(payload['created_by'])},
            {_sql_text(payload['kanban_status'])}, {_sql_text(payload['role'])}, {_sql_text(payload['claimed_by'])},
            {_sql_json(payload['tags'] if isinstance(payload['tags'], list) else [])}, {_sql_json(extra)},
            {_sql_text(_proj_id)}, {_sql_text(_source)}
        )
        ON CONFLICT (id) DO UPDATE SET
            timestamp = EXCLUDED.timestamp,
            updated_at = EXCLUDED.updated_at,
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            status = EXCLUDED.status,
            assigned_to = EXCLUDED.assigned_to,
            priority = EXCLUDED.priority,
            created_by = EXCLUDED.created_by,
            kanban_status = EXCLUDED.kanban_status,
            role = EXCLUDED.role,
            claimed_by = EXCLUDED.claimed_by,
            tags = EXCLUDED.tags,
            extra = EXCLUDED.extra,
            project_id = EXCLUDED.project_id,
            source = EXCLUDED.source;
        """
    )
    return get_task(task_id)


def list_tasks(project_id: str = None) -> list[dict]:
    # project_id 지정 시 해당 프로젝트 태스크만 반환 (project_id='' 구버전 데이터도 포함)
    # project_id 미지정(None) 시 전체 반환 (하위 호환)
    if project_id:
        where = f"WHERE project_id = {_sql_text(project_id)} OR project_id = ''"
    else:
        where = ""
    rows = query_rows(
        f"""
        SELECT id, timestamp, updated_at, title, description, status, assigned_to, priority,
               created_by, kanban_status, role, claimed_by, tags::text AS tags, extra::text AS extra,
               project_id
        FROM hive_tasks
        {where}
        ORDER BY updated_at DESC, timestamp DESC, id DESC;
        """
    )
    result = []
    for row in rows:
        task = {k: row.get(k) for k in (
            'id', 'timestamp', 'updated_at', 'title', 'description', 'status', 'assigned_to',
            'priority', 'created_by', 'kanban_status', 'role', 'claimed_by', 'project_id'
        )}
        task['tags'] = _parse_json_text(row.get('tags'), [])
        task.update(_parse_json_text(row.get('extra'), {}))
        result.append(task)
    return result


def get_task(task_id: str) -> dict | None:
    """단건 태스크 조회 — WHERE id = 로 직접 조회 (O(1), 기존 list_tasks 전체 스캔 제거)"""
    rows = query_rows(
        f"""
        SELECT id, timestamp, updated_at, title, description, status, assigned_to, priority,
               created_by, kanban_status, role, claimed_by, tags::text AS tags, extra::text AS extra,
               project_id
        FROM hive_tasks
        WHERE id = {_sql_text(task_id)}
        LIMIT 1;
        """
    )
    if not rows:
        return None
    row = rows[0]
    task = {k: row.get(k) for k in (
        'id', 'timestamp', 'updated_at', 'title', 'description', 'status', 'assigned_to',
        'priority', 'created_by', 'kanban_status', 'role', 'claimed_by', 'project_id'
    )}
    task['tags'] = _parse_json_text(row.get('tags'), [])
    task.update(_parse_json_text(row.get('extra'), {}))
    return task


_task_update_lock = threading.Lock()

def update_task(task_id: str, updates: dict) -> dict | None:
    # READ-MODIFY-WRITE 전체를 락으로 보호하여 concurrent update 방지
    with _task_update_lock:
        existing = get_task(task_id)
        if not existing:
            return None
        merged = {**existing, **updates}
        merged['id'] = task_id
        merged['updated_at'] = str(updates.get('updated_at', _now_iso()))
        if 'tags' in merged and isinstance(merged['tags'], str):
            merged['tags'] = [tag.strip() for tag in merged['tags'].split(',') if tag.strip()]
        return save_task(merged)


def delete_task(task_id: str) -> bool:
    return execute(f"DELETE FROM hive_tasks WHERE id = {_sql_text(task_id)};")


def bulk_update_tasks(assigned_to: str, statuses: list[str], new_status: str,
                      project_id: str = '') -> int:
    if not statuses:
        return 0
    project_id = assert_project_id(project_id, 'bulk_update_tasks')
    # 프로젝트 누수 차단 — project_id 지정 시 해당 프로젝트 + 빈 값(레거시)만 갱신
    proj_clause = (
        f" AND (project_id = {_sql_text(project_id)} OR project_id = '')"
        if project_id else ""
    )
    execute(
        f"""
        UPDATE hive_tasks
        SET status = {_sql_text(new_status)}, updated_at = {_sql_text(_now_iso())}
        WHERE assigned_to = {_sql_text(assigned_to)}
          AND status IN ({', '.join(_sql_text(status) for status in statuses)})
          {proj_clause};
        """
    )
    return len([task for task in list_tasks(project_id=project_id or None)
                if task.get('assigned_to') == assigned_to and task.get('status') == new_status])


def save_state(state_key: str, payload: dict) -> bool:
    return execute(
        f"""
        INSERT INTO hive_state (state_key, payload, updated_at)
        VALUES ({_sql_text(state_key)}, {_sql_json(payload)}, {_sql_text(_now_iso())})
        ON CONFLICT (state_key) DO UPDATE SET
            payload = EXCLUDED.payload,
            updated_at = EXCLUDED.updated_at;
        """
    )


def load_state(state_key: str, default=None):
    rows = query_rows(
        f"SELECT payload::text AS payload FROM hive_state WHERE state_key = {_sql_text(state_key)} LIMIT 1;"
    )
    if not rows:
        return default
    return _parse_json_text(rows[0].get('payload'), default)


def upsert_skill_chain_row(row: dict, legacy_id: int | None = None,
                            project_id: str = '') -> bool:
    # row dict에 project_id가 있으면 우선 사용
    _proj_id = str(row.get('project_id', '') or project_id)
    _proj_id = assert_project_id(_proj_id, 'upsert_skill_chain_row')
    if legacy_id is not None:
        # 기존 레코드 존재 여부 먼저 확인 (ON CONFLICT + partial unique index 호환 문제 회피)
        existing = query_rows(f"SELECT id FROM hive_skill_chains WHERE legacy_id = {int(legacy_id)} LIMIT 1;")
        if existing:
            return True  # 이미 존재하면 스킵 (레거시 마이그레이션 중복 방지)
        return execute(
            f"""
            INSERT INTO hive_skill_chains
                (legacy_id, session_id, terminal_id, agent, request, skill_num, skill_name,
                 step_order, status, summary, started_at, updated_at, project_id)
            VALUES (
                {legacy_id}, {_sql_text(row.get('session_id', ''))}, {int(row.get('terminal_id', 0) or 0)},
                {_sql_text(row.get('agent', ''))}, {_sql_text(row.get('request', ''))},
                {int(row.get('skill_num', 0) or 0)}, {_sql_text(row.get('skill_name', ''))},
                {int(row.get('step_order', 0) or 0)}, {_sql_text(row.get('status', 'pending'))},
                {_sql_text(row.get('summary', ''))}, {_sql_text(row.get('started_at', ''))},
                {_sql_text(row.get('updated_at', ''))}, {_sql_text(_proj_id)}
            );
            """
        )
    return execute(
        f"""
        INSERT INTO hive_skill_chains
            (session_id, terminal_id, agent, request, skill_num, skill_name, step_order, status, summary, started_at, updated_at, project_id)
        VALUES (
            {_sql_text(row.get('session_id', ''))}, {int(row.get('terminal_id', 0) or 0)},
            {_sql_text(row.get('agent', ''))}, {_sql_text(row.get('request', ''))},
            {int(row.get('skill_num', 0) or 0)}, {_sql_text(row.get('skill_name', ''))},
            {int(row.get('step_order', 0) or 0)}, {_sql_text(row.get('status', 'pending'))},
            {_sql_text(row.get('summary', ''))}, {_sql_text(row.get('started_at', ''))},
            {_sql_text(row.get('updated_at', ''))}, {_sql_text(_proj_id)}
        );
        """
    )


def list_skill_chain_rows() -> list[dict]:
    return query_rows(
        """
        SELECT id, session_id, terminal_id, agent, request, skill_num, skill_name,
               step_order, status, summary, started_at, updated_at
        FROM hive_skill_chains
        ORDER BY updated_at DESC, id DESC;
        """
    )

# ── Paperclip 스타일 오케스트레이션 ──────────────────────────────────────────
# [2026-03-30] 그룹 채팅 대체 — 원자적 체크아웃 + 태스크 코멘트 + 에이전트 하트비트

def atomic_checkout(agent_id: str, task_id: str) -> dict | None:
    """원자적 태스크 체크아웃 — 이미 체크아웃된 태스크는 None 반환.

    SELECT ... FOR UPDATE SKIP LOCKED 패턴으로 동시 접근 시 하나만 성공.
    """
    conn = _get_pg_conn()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            # 트랜잭션 내에서 잠금 획득 시도
            cur.execute(
                "SELECT id, title, description, assigned_to, status, priority "
                "FROM hive_tasks WHERE id = %s "
                "AND (checkout_by IS NULL OR checkout_by = '') "
                "FOR UPDATE SKIP LOCKED;",
                (task_id,)
            )
            row = cur.fetchone()
            if not row:
                return None  # 이미 체크아웃됨 또는 존재하지 않음
            # 체크아웃 마킹
            cur.execute(
                "UPDATE hive_tasks SET checkout_by = %s, checkout_at = now(), "
                "kanban_status = 'working', status = 'in_progress', "
                "updated_at = %s WHERE id = %s;",
                (agent_id, _now_iso(), task_id)
            )
            conn.commit()
            cols = ('id', 'title', 'description', 'assigned_to', 'status', 'priority')
            return dict(zip(cols, row))
    except Exception as e:
        conn.rollback()
        print(f"[pg_store] atomic_checkout 실패: {e}")
        return None


def release_checkout(task_id: str, new_status: str = 'done', result: str = '') -> bool:
    """체크아웃 해제 — 작업 완료 또는 실패 시 호출."""
    return execute(
        f"UPDATE hive_tasks SET checkout_by = NULL, checkout_at = NULL, "
        f"status = {_sql_text(new_status)}, kanban_status = {_sql_text(new_status)}, "
        f"result = {_sql_text(result)}, updated_at = {_sql_text(_now_iso())} "
        f"WHERE id = {_sql_text(task_id)};"
    )


def find_tasks_for_agent(agent_id: str, project_id: str = '') -> list[dict]:
    """에이전트에게 할당된 미처리 태스크 조회 (체크아웃 안 된 것만)."""
    where_parts = [
        f"assigned_to = {_sql_text(agent_id)}",
        "(checkout_by IS NULL OR checkout_by = '')",
        "status NOT IN ('done', 'cancelled', 'blocked')"
    ]
    if project_id:
        where_parts.append(f"(project_id = {_sql_text(project_id)} OR project_id = '')")
    where = " AND ".join(where_parts)
    return query_rows(
        f"SELECT id, title, description, priority, status, kanban_status "
        f"FROM hive_tasks WHERE {where} "
        f"ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
        f"WHEN 'medium' THEN 2 ELSE 3 END, updated_at ASC;"
    )


# ── 태스크 코멘트 CRUD ──────────────────────────────────────────────────────

def add_task_comment(task_id: str, author: str, content: str,
                     project_id: str = '') -> bool:
    """태스크에 코멘트 추가 — 에이전트 간 비동기 통신 채널."""
    project_id = assert_project_id(project_id, 'add_task_comment')
    return execute(
        f"INSERT INTO task_comments (task_id, author, content, project_id) "
        f"VALUES ({_sql_text(task_id)}, {_sql_text(author)}, {_sql_text(content)}, "
        f"{_sql_text(project_id)});"
    )


def list_task_comments(task_id: str, limit: int = 50) -> list[dict]:
    """태스크의 코멘트 목록 조회 (오래된 순)."""
    return query_rows(
        f"SELECT id, task_id, author, content, "
        f"to_char(created_at, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS created_at "
        f"FROM task_comments WHERE task_id = {_sql_text(task_id)} "
        f"ORDER BY created_at ASC LIMIT {int(limit)};"
    )


# ── 에이전트 하트비트 ────────────────────────────────────────────────────────

def record_heartbeat(agent_id: str, status: str = 'idle',
                     current_task: str = None, namespace: str = 'classic',
                     config: dict | None = None) -> bool:
    """에이전트 하트비트 기록 — 상태 갱신 + 카운터 증가.

    namespace: 'classic'(기본), 'pty', 'office' 등.
    config: terminal_id/project_id/last_line 같은 상태 보조 메타데이터.
    """
    import json as _json
    task_val = _sql_text(current_task) if current_task else 'NULL'
    config_val = (
        f"{_sql_text(_json.dumps(config, ensure_ascii=False))}::jsonb"
        if config else "'{}'::jsonb"
    )
    return execute(
        f"INSERT INTO agent_heartbeats (agent_id, status, last_beat, current_task, beat_count, namespace, config) "
        f"VALUES ({_sql_text(agent_id)}, {_sql_text(status)}, now(), {task_val}, 1, {_sql_text(namespace)}, {config_val}) "
        f"ON CONFLICT (agent_id) DO UPDATE SET "
        f"status = {_sql_text(status)}, last_beat = now(), "
        f"current_task = {task_val}, "
        f"beat_count = agent_heartbeats.beat_count + 1, "
        f"namespace = {_sql_text(namespace)}, "
        f"config = agent_heartbeats.config || {config_val};"
    )


def list_agent_status() -> list[dict]:
    """전체 에이전트 하트비트 상태 조회."""
    return query_rows(
        "SELECT agent_id, status, "
        "to_char(last_beat, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS last_beat, "
        "current_task, beat_count, config::text AS config "
        "FROM agent_heartbeats ORDER BY agent_id;"
    )


def trigger_agent(agent_id: str) -> bool:
    """에이전트에게 NOTIFY 전송 — 수동 하트비트 트리거."""
    conn = _get_pg_conn()
    if not conn:
        return False
    try:
        import json as _json
        payload = _json.dumps({'agent': agent_id, 'trigger': 'manual'})
        with conn.cursor() as cur:
            cur.execute(f"NOTIFY task_assigned, '{payload}';")
        conn.commit()
        return True
    except Exception as e:
        print(f"[pg_store] trigger_agent 실패: {e}")
        return False
