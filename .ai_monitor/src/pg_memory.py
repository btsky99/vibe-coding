# ────────────────────────────────────────────────────────────────────────────
# 📄 파일명: src/pg_memory.py
# 📝 설명: 하이브 메모리(hive_memory) CRUD + zettel 승격 + 세션 로그 + 채팅 + 지식 회상
#          (pg_store.py 분할 3/6)
# 🕒 변경 이력:
# [2026-06-10] Claude — pg_store.py 분할로 신설 (1500줄 규칙 준수)
#   - [WHY] zettelkasten 모듈은 함수 내부 지연 import — zettelkasten.py가
#     pg_store(파사드)를 모듈 레벨에서 import 하므로 역방향은 지연이 안전.
# ────────────────────────────────────────────────────────────────────────────
import os

from infra.project_context import assert_project_id
from src.pg_base import (
    _now_iso,
    _parse_json_text,
    _run_psql,
    _sql_json,
    _sql_text,
    execute,
    query_rows,
)


def list_memory(q: str = '', top_k: int = 20, project_id: str = '', show_all: bool = False,
                author: str = '', include_zettel: bool = False) -> list[dict]:
    """하이브 메모리 조회. include_zettel=True면 zettel_notes(정제 지식)도 합쳐 반환.

    반환 항목에 `source: 'hive' | 'zettel'` 필드를 붙여 UI에서 구분 가능.
    zettel 결과는 `note_type`(fleeting/permanent 등)도 함께 담김.
    """
    filters = []
    if project_id and not show_all:
        # 현재 프로젝트 + 글로벌(__global__) 항목 모두 반환 (크로스 프로젝트 지식 공유)
        filters.append(f"(project_id = {_sql_text(project_id)} OR project_id = '__global__')")
    # 작성자 필터 — 'claude-t1'처럼 정확 매칭, 'claude' 처럼 prefix 매칭 둘 다 지원
    author_norm = (author or '').strip().lower()
    if author_norm:
        filters.append(
            f"(LOWER(author) = {_sql_text(author_norm)} "
            f"OR LOWER(author) LIKE {_sql_text(author_norm + '-%')})"
        )
    # 만료된 항목 제외 (expires_at이 NULL이거나 현재 시각 이후인 것만)
    filters.append(f"(expires_at IS NULL OR expires_at > {_sql_text(_now_iso())})")
    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ''
    if q:
        q_sql = _sql_text(q)
        query = f"""
        SELECT key, title, content, author, project_id, created_at, updated_at, tags::text AS tags
        FROM hive_memory
        {where_sql} {'AND' if where_sql else 'WHERE'}
            (
                LOWER(key) LIKE LOWER('%' || {q_sql} || '%')
                OR LOWER(title) LIKE LOWER('%' || {q_sql} || '%')
                OR LOWER(content) LIKE LOWER('%' || {q_sql} || '%')
                OR tags::text LIKE '%' || {q_sql} || '%'
            )
        ORDER BY updated_at DESC
        LIMIT {int(top_k)};
        """
    else:
        query = f"""
        SELECT key, title, content, author, project_id, created_at, updated_at, tags::text AS tags
        FROM hive_memory
        {where_sql}
        ORDER BY updated_at DESC
        LIMIT {int(top_k)};
        """
    rows = query_rows(query)
    for row in rows:
        row['tags'] = _parse_json_text(row.get('tags'), [])
        row['source'] = 'hive'

    # C.1 — 지식 저장소(zettel_notes) 통합 조회.
    # hive_memory와 시그니처를 맞춰 key/content/author/updated_at 필드로 정규화한 뒤
    # updated_at 내림차순 병합. 검색어가 없으면 zettel이 activity 많아 hive를
    # 밀어내지 않도록 각 소스에서 절반씩만 가져와 섞음.
    if include_zettel:
        try:
            from src.zettelkasten import list_notes
        except ImportError:
            from .zettelkasten import list_notes  # type: ignore
        # zettel 쪽 필터도 비슷하게 적용. project_id는 show_all일 때 빈 문자열.
        zettel_project_id = '' if show_all or not project_id else project_id
        # 검색어 있으면 hit 전량, 없으면 hive가 밀리지 않게 균형 배분 (절반씩)
        if q:
            zettel_limit = int(top_k) * 2
            hive_rows_kept = rows
        else:
            half = max(1, int(top_k) // 2)
            zettel_limit = half
            hive_rows_kept = rows[:half]
        notes = list_notes(
            project_id=zettel_project_id,
            author=author_norm if author_norm else '',
            q=q or '',
            limit=zettel_limit,
        )
        rows = list(hive_rows_kept)
        for note in notes:
            updated = note.get('updated_at')
            created = note.get('created_at')
            # hive_memory는 'YYYY-MM-DDTHH:MM:SS' 형식, zettel은 datetime 객체.
            # 문자열 비교 정렬이 일관되도록 공백 구분자를 'T'로 통일.
            updated_str = str(updated)[:19].replace(' ', 'T') if updated else ''
            created_str = str(created)[:19].replace(' ', 'T') if created else ''
            rows.append({
                'key': note.get('id', ''),
                'title': note.get('title', ''),
                'content': note.get('content', ''),
                'tags': note.get('tags', []) or [],
                'author': note.get('author', 'unknown'),
                'project_id': note.get('project_id', ''),
                'created_at': created_str,
                'updated_at': updated_str,
                'source': 'zettel',
                'note_type': note.get('note_type', 'fleeting'),
                'access_count': note.get('access_count', 0),
            })
        # updated_at 내림차순 재정렬 후 top_k 절단
        rows.sort(key=lambda r: r.get('updated_at', ''), reverse=True)
        rows = rows[:int(top_k)]

    return rows


def get_memory(key: str) -> dict | None:
    rows = query_rows(
        f"SELECT key, title, content, author, project_id, created_at, updated_at, tags::text AS tags "
        f"FROM hive_memory WHERE key = {_sql_text(key)} LIMIT 1;"
    )
    if not rows:
        return None
    row = rows[0]
    row['tags'] = _parse_json_text(row.get('tags'), [])
    return row


# 작성자 식별자 정규화 — 모호한 기본값('unknown','agent',빈값)일 때 env 우선 승격.
# 우선순위: 명시된 author(모호 아님) > HIVE_AGENT_ID env > 'unknown'
# 포맷: 소문자화 + 공백 제거 (예: 'claude-t1', 'gemini', 'user')
_AMBIGUOUS_AUTHORS = {'', 'unknown', 'agent', 'none', 'null'}


def _resolve_author(author: str | None) -> str:
    raw = (author or '').strip().lower()
    if raw and raw not in _AMBIGUOUS_AUTHORS:
        return raw
    env_val = (os.environ.get('HIVE_AGENT_ID', '') or '').strip().lower()
    if env_val and env_val not in _AMBIGUOUS_AUTHORS:
        return env_val
    return 'unknown'


def set_memory(
    key: str,
    content: str,
    title: str = '',
    tags: list | None = None,
    author: str | None = None,
    project_id: str = '',
    created_at: str = '',
    updated_at: str = '',
    ttl_days: int | None = None,
) -> dict | None:
    if not key or content is None:
        return None
    project_id = assert_project_id(project_id, 'set_memory')
    author = _resolve_author(author)
    existing = get_memory(key)
    created_value = existing.get('created_at', '') if existing else (created_at or updated_at or _now_iso())
    updated_value = updated_at or _now_iso()
    title_value = title or key
    # TTL 만료 시각 계산 — ttl_days 지정 시 updated_at + N일
    expires_value = None
    if ttl_days and ttl_days > 0:
        import datetime as _dt
        expires_value = (_dt.datetime.fromisoformat(updated_value) + _dt.timedelta(days=ttl_days)).isoformat()
    execute(
        f"""
        INSERT INTO hive_memory (key, title, content, tags, author, project_id, created_at, updated_at, expires_at)
        VALUES (
            {_sql_text(key)},
            {_sql_text(title_value)},
            {_sql_text(content)},
            {_sql_json(tags or [])},
            {_sql_text(author)},
            {_sql_text(project_id)},
            {_sql_text(created_value)},
            {_sql_text(updated_value)},
            {_sql_text(expires_value)}
        )
        ON CONFLICT (key) DO UPDATE SET
            title = EXCLUDED.title,
            content = EXCLUDED.content,
            tags = EXCLUDED.tags,
            author = EXCLUDED.author,
            project_id = EXCLUDED.project_id,
            updated_at = EXCLUDED.updated_at,
            expires_at = EXCLUDED.expires_at;
        """
    )

    # C.3 — 승격 유도 태그가 있으면 zettel_notes에 자동 승격. 실패는 조용히 무시.
    tag_set = {str(t).lower() for t in (tags or [])}
    if tag_set & _PROMOTION_TAGS:
        try:
            promote_to_zettel(key)
        except Exception:
            pass

    return get_memory(key)


def delete_memory(key: str) -> bool:
    return execute(f"DELETE FROM hive_memory WHERE key = {_sql_text(key)};")


# ── C.3 — hive_memory → zettel_notes 승격 ─────────────────────────────────

# 자동 승격 유도 태그 — set_memory 시 이들 태그가 있으면 즉시 zettel로도 저장
_PROMOTION_TAGS = {'learning', 'insight', 'knowledge', 'permanent', '지식', '교훈'}
# tags에 'permanent'/'영구'가 있으면 permanent로, 아니면 fleeting으로 승격
_PERMANENT_TAGS = {'permanent', '영구'}


def promote_to_zettel(key: str, note_type: str = '') -> dict | None:
    """hive_memory 항목을 zettel_notes로 승격한다.

    원본은 유지(작업 흔적 보존), zettel 쪽에 `source_ref`로 원본 key 기록.
    동일 source_ref가 이미 있으면 중복 승격 방지.
    note_type 미지정 시 tags 기반 자동 결정(_PERMANENT_TAGS → permanent, 나머지 fleeting).
    """
    entry = get_memory(key)
    if not entry:
        return None

    # 중복 승격 방지 — 같은 hive key가 이미 zettel source_ref로 쓰였는지 확인
    existing = query_rows(
        f"SELECT id FROM zettel_notes WHERE source_ref = {_sql_text(f'hive:{key}')} LIMIT 1;"
    )
    if existing:
        return _get_existing_zettel(existing[0]['id'])

    # note_type 자동 결정
    tags = entry.get('tags') or []
    tag_set = {str(t).lower() for t in tags}
    if not note_type:
        note_type = 'permanent' if tag_set & _PERMANENT_TAGS else 'fleeting'

    try:
        from src.zettelkasten import create_note
    except ImportError:
        from .zettelkasten import create_note  # type: ignore

    note = create_note(
        title=entry.get('title') or key,
        content=entry.get('content', ''),
        note_type=note_type,
        author=entry.get('author', 'unknown'),
        project_id=entry.get('project_id', ''),
        tags=tags,
        source_ref=f'hive:{key}',
    )
    return note


def _get_existing_zettel(note_id: str) -> dict | None:
    rows = query_rows(
        f"SELECT *, tags::text AS tags_text FROM zettel_notes WHERE id = {_sql_text(note_id)};"
    )
    if not rows:
        return None
    row = rows[0]
    row['tags'] = _parse_json_text(row.pop('tags_text', '[]'), [])
    return row


# ── C.4 — fleeting → permanent 자동 승격 ─────────────────────────────────────
# 승격 조건 (B안, OR 결합):
#   1) 생존형: 생성 N일 경과 + access_count ≥ M회 (버려지지 않고 재사용됨)
#   2) 허브형: 링크 degree ≥ K (다른 노트와 많이 연결된 지식 허브)
#   3) 명시형: tags에 permanent/영구 포함 (사용자 수동 마킹)
_AUTO_PROMOTE_MIN_AGE_DAYS = 7
_AUTO_PROMOTE_MIN_ACCESS = 2
_AUTO_PROMOTE_MIN_DEGREE = 3


def _auto_promote_where_clause() -> str:
    """fleeting → permanent 승격 대상 zettel_notes 행을 고르는 WHERE 절.

    호출부에서 `FROM zettel_notes zn` 별칭을 쓴다고 가정.
    """
    age_days = _AUTO_PROMOTE_MIN_AGE_DAYS
    min_access = _AUTO_PROMOTE_MIN_ACCESS
    min_degree = _AUTO_PROMOTE_MIN_DEGREE
    return (
        "zn.note_type = 'fleeting' "
        "AND (zn.archived IS NOT TRUE) "
        "AND ("
        f"(zn.created_at < NOW() - INTERVAL '{age_days} days' AND zn.access_count >= {min_access}) "
        "OR EXISTS ("
        "  SELECT 1 FROM ("
        "    SELECT source_id AS nid FROM zettel_links "
        "    UNION ALL "
        "    SELECT target_id AS nid FROM zettel_links"
        "  ) l "
        f"  WHERE l.nid = zn.id GROUP BY l.nid HAVING COUNT(*) >= {min_degree}"
        ") "
        "OR zn.tags @> '[\"permanent\"]'::jsonb "
        "OR zn.tags @> '[\"영구\"]'::jsonb"
        ")"
    )


def preview_auto_promote() -> list[dict]:
    """승격 대상(fleeting) 노트 목록을 반환 — dry-run 용."""
    sql = (
        "SELECT zn.id, zn.title, zn.access_count, zn.created_at, "
        "       zn.tags::text AS tags_text "
        "FROM zettel_notes zn "
        f"WHERE {_auto_promote_where_clause()} "
        "ORDER BY zn.created_at ASC;"
    )
    rows = query_rows(sql)
    for r in rows:
        r['tags'] = _parse_json_text(r.pop('tags_text', '[]'), [])
    return rows


def auto_promote_fleeting() -> int:
    """조건을 만족하는 fleeting 노트를 permanent로 일괄 승격한다.

    반환값: 승격된 노트 수 (psql은 UPDATE 행 수 직접 반환 안 해서
            사전 COUNT로 추정).
    """
    count_rows = query_rows(
        "SELECT COUNT(*) AS n FROM zettel_notes zn "
        f"WHERE {_auto_promote_where_clause()};"
    )
    n = int(count_rows[0].get('n', 0)) if count_rows else 0
    if n == 0:
        return 0

    # UPDATE는 서브쿼리로 대상 id를 뽑아서 적용 — WHERE 절 구조상
    # zn 별칭 UPDATE가 psql에서 까다로워서 ID 서브쿼리 방식 사용
    subquery = (
        "SELECT zn.id FROM zettel_notes zn "
        f"WHERE {_auto_promote_where_clause()}"
    )
    ok = execute(
        f"UPDATE zettel_notes SET note_type = 'permanent', updated_at = NOW() "
        f"WHERE id IN ({subquery});"
    )
    return n if ok else 0


def cleanup_expired_memory() -> int:
    """expires_at이 현재 시각보다 이전인 메모리 항목을 삭제합니다.
    워치독 루프 또는 서버 기동 시 호출하여 오래된 데이터를 자동 정리합니다.
    반환값: 삭제된 행 수 (파싱 실패 시 0)
    """
    ok, output = _run_psql(
        f"DELETE FROM hive_memory WHERE expires_at IS NOT NULL AND expires_at < {_sql_text(_now_iso())};",
        timeout=10
    )
    return 0  # psql은 DELETE 행 수를 직접 반환하지 않아 0 리턴 (동작은 수행됨)


def upsert_session_log(
    session_id: str,
    terminal_id: str = '',
    project_id: str = '',
    agent: str = '',
    trigger_msg: str = '',
    status: str = '',
    commit_hash: str = '',
    files_changed: list | None = None,
    ts_start: str = '',
    ts_end: str = '',
    legacy_source: str | None = None,
    legacy_id: int | None = None,
) -> bool:
    project_id = assert_project_id(project_id, 'upsert_session_log')
    if legacy_source and legacy_id is not None:
        # SELECT-first: partial unique index와 ON CONFLICT 호환 문제 회피
        existing = query_rows(
            f"SELECT id FROM hive_sessions WHERE legacy_source = {_sql_text(legacy_source)} "
            f"AND legacy_id = {legacy_id} LIMIT 1;"
        )
        if existing:
            return True  # 이미 존재하면 스킵 (레거시 마이그레이션 중복 방지)
        return execute(
            f"""
            INSERT INTO hive_sessions
                (legacy_source, legacy_id, session_id, terminal_id, project_id, agent, trigger_msg,
                 status, commit_hash, files_changed, ts_start, ts_end)
            VALUES (
                {_sql_text(legacy_source)}, {legacy_id}, {_sql_text(session_id)}, {_sql_text(terminal_id)},
                {_sql_text(project_id)}, {_sql_text(agent)}, {_sql_text(trigger_msg)}, {_sql_text(status)},
                {_sql_text(commit_hash)}, {_sql_json(files_changed or [])}, {_sql_text(ts_start or _now_iso())},
                {_sql_text(ts_end or '')}
            );
            """
        )
    return execute(
        f"""
        INSERT INTO hive_sessions
            (session_id, terminal_id, project_id, agent, trigger_msg, status, commit_hash, files_changed, ts_start, ts_end)
        VALUES (
            {_sql_text(session_id)}, {_sql_text(terminal_id)}, {_sql_text(project_id)}, {_sql_text(agent)},
            {_sql_text(trigger_msg)}, {_sql_text(status)}, {_sql_text(commit_hash)},
            {_sql_json(files_changed or [])}, {_sql_text(ts_start or _now_iso())}, {_sql_text(ts_end or '')}
        );
        """
    )


def list_session_logs(limit: int = 200) -> list[dict]:
    rows = query_rows(
        f"""
        SELECT id, session_id, terminal_id, project_id, agent, trigger_msg, status, commit_hash,
               files_changed::text AS files_changed, ts_start, ts_end
        FROM hive_sessions
        ORDER BY ts_start DESC, id DESC
        LIMIT {int(limit)};
        """
    )
    for row in rows:
        row['files_changed'] = _parse_json_text(row.get('files_changed'), [])
    return rows


def get_agent_last_seen(agent_names: list[str] | None = None) -> dict[str, str | None]:
    """
    에이전트별 마지막 활동 시각 반환 (ISO 문자열).

    두 소스를 종합하여 가장 최근 시각을 선택한다:
      1) hive_sessions.ts_start — PTY 세션 시작 시각 (기존 소스)
      2) agent_heartbeats.last_beat — 에이전트 하트비트 (실시간 추적)

    Why: hive_sessions는 PTY 터미널 세션에만 기록되어 Claude Code CLI 등
    외부 클라이언트 활동을 놓침. agent_heartbeats는 서버가 주기적으로
    갱신하는 실시간 소스이므로 더 정확한 alive 판정 가능.
    scripts/orchestrator.py의 pick_best_agent가 이 함수 결과로 죽은
    에이전트를 후보에서 제외하는데, 구 로직은 claude도 36일 idle로
    판정해 모든 'all' 태스크가 영원히 적체되던 문제 수정.
    """
    agent_names = agent_names or []
    result: dict[str, str | None] = {name: None for name in agent_names}

    # 채널 1: hive_sessions (PTY 세션 기록)
    try:
        rows = query_rows(
            "SELECT LOWER(agent) AS agent_name, MAX(ts_start) AS last_seen "
            "FROM hive_sessions GROUP BY LOWER(agent) ORDER BY last_seen DESC;"
        )
        for row in rows:
            agent_name = row.get('agent_name', '')
            for wanted in agent_names:
                if wanted in agent_name:
                    seen = row.get('last_seen')
                    if seen and (result.get(wanted) is None or str(seen) > str(result[wanted])):
                        result[wanted] = str(seen)
    except Exception:
        pass

    # 채널 2: agent_heartbeats (실시간 하트비트 — 더 신선한 소스)
    try:
        hb_rows = query_rows(
            "SELECT LOWER(agent_id) AS agent_name, "
            "to_char(last_beat, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS last_seen "
            "FROM agent_heartbeats ORDER BY last_beat DESC;"
        )
        for row in hb_rows:
            agent_name = row.get('agent_name', '')
            for wanted in agent_names:
                if wanted in agent_name:
                    seen = row.get('last_seen')
                    if seen and (result.get(wanted) is None or str(seen) > str(result[wanted])):
                        result[wanted] = str(seen)
    except Exception:
        pass

    return result

# ── 실시간 채팅 (hive_memory 기반) ────────────────────────────────────────────
# 채팅 메시지를 hive_memory에 저장 (tag: ["chat"])
# key 형식: chat:{timestamp}:{sender}
# LISTEN/NOTIFY 트리거가 자동으로 'hive_realtime' 채널에 알림

def send_chat(sender: str, content: str, project_id: str = '') -> dict | None:
    """실시간 채팅 메시지 전송 — hive_memory에 저장 + NOTIFY 자동 발생."""
    project_id = assert_project_id(project_id, 'send_chat')
    import time as _t
    key = f"chat:{_t.strftime('%Y%m%d-%H%M%S')}:{sender}:{id(_t)}"
    return set_memory(
        key=key,
        title=f"[{sender}] {content[:50]}",
        content=content[:2000],
        tags=["chat"],
        author=sender,
        project_id=project_id,
        ttl_days=7,  # 채팅 메시지는 7일 후 자동 삭제
    )


def get_chat_history(limit: int = 20) -> list[dict]:
    """최근 채팅 메시지 조회 (오래된 순)."""
    rows = query_rows(
        f"""
        SELECT key, content, author, updated_at
        FROM hive_memory
        WHERE tags @> '["chat"]'::jsonb
        ORDER BY updated_at DESC
        LIMIT {limit};
        """
    )
    # 오래된 순으로 뒤집기
    messages = []
    for row in reversed(rows):
        messages.append({
            "sender": row.get("author", ""),
            "content": row.get("content", ""),
            "ts": row.get("updated_at", ""),
        })
    return messages


def get_chat_context(limit: int = 10) -> str:
    """에이전트용 채팅 컨텍스트 프롬프트 생성."""
    messages = get_chat_history(limit)
    if not messages:
        return "(대화 없음)"
    return "\n".join(f"[{m['sender']}] {m['content']}" for m in messages)

# ── C.2 — 지식 회상 (zettel_notes + hive_memory 통합) ──────────────────────

def recall_knowledge_summary(query: str, limit: int = 5) -> str:
    """사용자 프롬프트와 관련된 누적 지식(zettel + hive)을 요약 텍스트로 반환.

    recall_context_summary(agent_experience 기반)를 보완 — 이쪽은 "작업 결과"가
    아니라 "정제된 지식"이 대상. 에이전트가 과거 배운 것/합의/가이드를 세션
    첫 턴부터 참조하도록 주입한다.

    작성자 태그(B.2)와 맞물려 "누가 남긴 지식"인지 구분 표시.
    """
    if not query or not query.strip():
        return ""

    # 2자 이상 키워드 추출 (한글/영어 공통)
    import re as _re_k
    keywords = [w for w in _re_k.split(r'\s+', query.strip()) if len(w) >= 2][:4]
    if not keywords:
        return ""

    # ILIKE OR 조합 — 짧은 쿼리도 놓치지 않도록
    or_parts = []
    for kw in keywords:
        safe_kw = _sql_text(f'%{kw}%')
        or_parts.append(f"(title ILIKE {safe_kw} OR content ILIKE {safe_kw})")
    where_ilike = " OR ".join(or_parts)

    # zettel_notes (archived=FALSE만, access_count 높은 것 우선).
    # 자동 캡처물("세션 요약:", "📄 파일 설명")은 브리핑 노이즈 — 사람/에이전트가
    # 의도적으로 쓴 지식만 우선. 매칭 없으면 fallback으로 자동 캡처물도 허용.
    zettel_rows = query_rows(
        f"SELECT id, title, author, note_type, access_count "
        f"FROM zettel_notes "
        f"WHERE archived = FALSE "
        f"  AND title NOT LIKE '세션 요약:%' "
        f"  AND title NOT LIKE '📄 %' "
        f"  AND ({where_ilike}) "
        f"ORDER BY access_count DESC, updated_at DESC "
        f"LIMIT {int(limit)};"
    )
    if not zettel_rows:
        # fallback — 지식 우선 필터로 0건이면 자동 캡처물도 포함해 재조회
        zettel_rows = query_rows(
            f"SELECT id, title, author, note_type, access_count "
            f"FROM zettel_notes "
            f"WHERE archived = FALSE AND ({where_ilike}) "
            f"ORDER BY access_count DESC, updated_at DESC "
            f"LIMIT {int(limit)};"
        )

    # hive_memory (만료되지 않은 것만, 최근순)
    now = _now_iso()
    hive_rows = query_rows(
        f"SELECT key, title, author "
        f"FROM hive_memory "
        f"WHERE (expires_at IS NULL OR expires_at > {_sql_text(now)}) "
        f"  AND ({where_ilike}) "
        f"ORDER BY updated_at DESC "
        f"LIMIT {int(limit)};"
    )

    if not zettel_rows and not hive_rows:
        return ""

    lines = [f"[지식 회상] '{query[:50]}'와 관련된 누적 지식 "
             f"{len(zettel_rows) + len(hive_rows)}건 (zettel {len(zettel_rows)} + hive {len(hive_rows)}):"]

    for r in zettel_rows:
        title = (r.get('title') or r.get('id', ''))[:60]
        author = r.get('author', 'unknown')
        nt = r.get('note_type', 'fleeting')
        ac = r.get('access_count', 0) or 0
        lines.append(f"  🧠 [{nt}] {title} — by {author} (참조 {ac}회)")

    for r in hive_rows:
        title = (r.get('title') or r.get('key', ''))[:60]
        author = r.get('author', 'unknown')
        lines.append(f"  💾 {title} — by {author}")

    return "\n".join(lines)
