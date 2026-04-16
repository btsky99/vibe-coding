"""
FILE: src/zettelkasten.py
DESCRIPTION: Hive Zettelkasten — 카파시 Append-Review-Rescue + 루만 제텔카스텐 융합 메모 시스템.
             원자 노트 CRUD, 분기 번호 생성, 백링크 관리, 중력 침강/rescue 로직.
REVISION HISTORY:
    2026-04-05 — 초기 구현 (카파시 LLM KB + 루만 제텔카스텐 아키텍처)
"""

import json
import re
from datetime import datetime, timezone
from typing import Any

from src.pg_store import execute, execute_raw, query_rows, ensure_schema, _sql_text


# ── 분기 번호(Zettel ID) 생성 ──────────────────────────────────────────────

def _project_prefix(project: str = '') -> str:
    """프로젝트명에서 vault 안전한 접두사를 생성한다.

    예: 'D--vibe-coding' → 'vibe', 'my-project' → 'myproj', '' → ''
    """
    if not project:
        return ''
    # D-- 접두사 제거, 소문자화, 최대 8자
    name = re.sub(r'^[A-Z]--', '', project).lower()
    # 'vibe-coding' → 'vibe' (첫 단어)
    parts = re.split(r'[-_]', name)
    prefix = parts[0][:8] if parts else name[:8]
    return prefix


def _next_zettel_id(parent_id: str = '', project: str = '') -> str:
    """루만식 분기 번호 생성. 프로젝트 접두사 포함.

    예: project='D--vibe-coding' → 'vibe-1', 'vibe-2', 'vibe-2a', 'vibe-2a1'
        parent='vibe-2' → 'vibe-2a'
    """
    ensure_schema()
    prefix = _project_prefix(project)
    sep = '-' if prefix else ''

    if not parent_id:
        # 루트 레벨: 해당 프로젝트 접두사의 가장 큰 숫자 + 1
        pattern = f'^{re.escape(prefix)}{re.escape(sep)}[0-9]+$' if prefix else '^[0-9]+$'
        rows = query_rows(
            f"SELECT id FROM zettel_notes WHERE id ~ {_sql_text(pattern)} "
            f"ORDER BY LENGTH(id) DESC, id DESC LIMIT 10;"
        )
        if rows:
            # 숫자 부분만 추출하여 최대값 찾기
            max_num = 0
            strip_len = len(prefix) + len(sep)
            for r in rows:
                try:
                    num = int(r['id'][strip_len:])
                    max_num = max(max_num, num)
                except ValueError:
                    continue
            return f"{prefix}{sep}{max_num + 1}"
        return f"{prefix}{sep}1"

    # 하위 분기: 기존 루만식 로직 유지
    last_char = parent_id[-1]
    if last_char.isdigit():
        rows = query_rows(
            f"SELECT id FROM zettel_notes WHERE id ~ {_sql_text('^' + re.escape(parent_id) + '[a-z]$')} "
            f"ORDER BY id DESC LIMIT 1;"
        )
        if rows:
            last_branch = rows[0]['id'][-1]
            if last_branch >= 'z':
                return parent_id + 'z1'
            return parent_id + chr(ord(last_branch) + 1)
        return parent_id + 'a'
    else:
        rows = query_rows(
            f"SELECT id, CAST(SUBSTRING(id FROM {len(parent_id) + 1}) AS INT) AS num "
            f"FROM zettel_notes WHERE id ~ {_sql_text('^' + re.escape(parent_id) + '[0-9]+$')} "
            f"ORDER BY num DESC LIMIT 1;"
        )
        if rows:
            suffix = rows[0]['id'][len(parent_id):]
            return parent_id + str(int(suffix) + 1)
        return parent_id + '1'


def generate_zettel_id(parent_id: str = '', project: str = '') -> str:
    """외부에서 호출 가능한 분기 번호 생성 함수."""
    return _next_zettel_id(parent_id, project=project)


# ── CRUD ───────────────────────────────────────────────────────────────────

def create_note(title: str, content: str = '', note_type: str = 'fleeting',
                author: str = 'unknown', project: str = '', tags: list | None = None,
                source_ref: str = '', parent_id: str = '',
                custom_id: str = '') -> dict | None:
    """원자 노트 생성. 분기 번호 자동 생성 또는 custom_id 지정 가능."""
    ensure_schema()
    zettel_id = custom_id or _next_zettel_id(parent_id, project=project)
    now = datetime.now(timezone.utc).isoformat()
    tags_json = json.dumps(tags or [], ensure_ascii=False)

    ok = execute(
        f"INSERT INTO zettel_notes (id, title, content, note_type, author, project, tags, source_ref, created_at, updated_at) "
        f"VALUES ({_sql_text(zettel_id)}, {_sql_text(title)}, {_sql_text(content)}, "
        f"{_sql_text(note_type)}, {_sql_text(author)}, {_sql_text(project)}, "
        f"{_sql_text(tags_json)}::jsonb, {_sql_text(source_ref)}, "
        f"{_sql_text(now)}, {_sql_text(now)});"
    )
    if not ok:
        return None
    return _get_note_raw(zettel_id)


def _get_note_raw(note_id: str) -> dict | None:
    """내부 호출용 노트 조회 (access_count 미증가)."""
    rows = query_rows(
        f"SELECT *, tags::text AS tags_text FROM zettel_notes WHERE id = {_sql_text(note_id)};"
    )
    if not rows:
        return None
    row = rows[0]
    row['tags'] = _parse_tags(row.pop('tags_text', '[]'))
    row['links'] = get_links(note_id)
    row['backlinks'] = get_backlinks(note_id)
    return row


def get_note(note_id: str) -> dict | None:
    """외부 API용 노트 조회 + access_count 증가."""
    ensure_schema()
    execute(f"UPDATE zettel_notes SET access_count = access_count + 1 WHERE id = {_sql_text(note_id)};")
    return _get_note_raw(note_id)


def update_note(note_id: str, **kwargs) -> dict | None:
    """노트 필드 업데이트. 허용 필드: title, content, note_type, tags, source_ref, archived."""
    ensure_schema()
    allowed = {'title', 'content', 'note_type', 'tags', 'source_ref', 'archived'}
    sets = []
    for k, v in kwargs.items():
        if k not in allowed:
            continue
        if k == 'tags':
            sets.append(f"tags = {_sql_text(json.dumps(v, ensure_ascii=False))}::jsonb")
        elif k == 'archived':
            sets.append(f"archived = {'TRUE' if v else 'FALSE'}")
        else:
            sets.append(f"{k} = {_sql_text(str(v))}")
    if not sets:
        return _get_note_raw(note_id)
    now = datetime.now(timezone.utc).isoformat()
    sets.append(f"updated_at = {_sql_text(now)}")
    execute(f"UPDATE zettel_notes SET {', '.join(sets)} WHERE id = {_sql_text(note_id)};")
    return _get_note_raw(note_id)


def delete_note(note_id: str) -> bool:
    """노트 삭제 (CASCADE로 링크도 함께 삭제)."""
    ensure_schema()
    return execute(f"DELETE FROM zettel_notes WHERE id = {_sql_text(note_id)};")


def list_notes(project: str = '', note_type: str = '', author: str = '',
               include_archived: bool = False, q: str = '',
               order_by: str = 'updated_at', limit: int = 50,
               offset: int = 0) -> list[dict]:
    """노트 목록 조회. 필터링 + 검색 + 페이지네이션."""
    ensure_schema()
    conditions = []
    if not include_archived:
        conditions.append("archived = FALSE")
    if project:
        conditions.append(f"project = {_sql_text(project)}")
    if note_type:
        conditions.append(f"note_type = {_sql_text(note_type)}")
    if author:
        conditions.append(f"author = {_sql_text(author)}")
    if q:
        q_escaped = _sql_text(f'%{q}%')
        conditions.append(f"(title ILIKE {q_escaped} OR content ILIKE {q_escaped})")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    valid_orders = {'updated_at', 'created_at', 'access_count', 'last_rescued_at', 'title'}
    order_col = order_by if order_by in valid_orders else 'updated_at'
    direction = 'ASC' if order_col == 'title' else 'DESC'

    rows = query_rows(
        f"SELECT *, tags::text AS tags_text FROM zettel_notes {where} "
        f"ORDER BY {order_col} {direction} NULLS LAST "
        f"LIMIT {int(limit)} OFFSET {int(offset)};"
    )
    for row in rows:
        row['tags'] = _parse_tags(row.pop('tags_text', '[]'))
    return rows


# ── 백링크 관리 ────────────────────────────────────────────────────────────

def add_link(source_id: str, target_id: str, link_type: str = 'relates_to',
             created_by: str = 'system') -> bool:
    """두 노트 간 링크 생성."""
    ensure_schema()
    return execute(
        f"INSERT INTO zettel_links (source_id, target_id, link_type, created_by) "
        f"VALUES ({_sql_text(source_id)}, {_sql_text(target_id)}, "
        f"{_sql_text(link_type)}, {_sql_text(created_by)}) "
        f"ON CONFLICT (source_id, target_id, link_type) DO NOTHING;"
    )


def remove_link(source_id: str, target_id: str, link_type: str = '') -> bool:
    """링크 삭제."""
    ensure_schema()
    if link_type:
        return execute(
            f"DELETE FROM zettel_links WHERE source_id = {_sql_text(source_id)} "
            f"AND target_id = {_sql_text(target_id)} AND link_type = {_sql_text(link_type)};"
        )
    return execute(
        f"DELETE FROM zettel_links WHERE source_id = {_sql_text(source_id)} "
        f"AND target_id = {_sql_text(target_id)};"
    )


def get_links(note_id: str) -> list[dict]:
    """이 노트에서 나가는 링크 목록."""
    return query_rows(
        f"SELECT l.target_id AS id, l.link_type, n.title "
        f"FROM zettel_links l JOIN zettel_notes n ON l.target_id = n.id "
        f"WHERE l.source_id = {_sql_text(note_id)};"
    )


def get_backlinks(note_id: str) -> list[dict]:
    """이 노트로 들어오는 백링크 목록."""
    return query_rows(
        f"SELECT l.source_id AS id, l.link_type, n.title "
        f"FROM zettel_links l JOIN zettel_notes n ON l.source_id = n.id "
        f"WHERE l.target_id = {_sql_text(note_id)};"
    )


def get_graph(project: str = '', limit: int = 200) -> dict:
    """전체 노트 그래프 반환 (nodes + edges). UI 시각화용."""
    ensure_schema()
    proj_filter = f"WHERE project = {_sql_text(project)}" if project else ""
    nodes = query_rows(
        f"SELECT id, title, note_type, author, access_count, archived, tags::text AS tags_text "
        f"FROM zettel_notes {proj_filter} "
        f"ORDER BY updated_at DESC LIMIT {int(limit)};"
    )
    for n in nodes:
        n['tags'] = _parse_tags(n.pop('tags_text', '[]'))

    node_ids = [n['id'] for n in nodes]
    edges = []
    if node_ids:
        id_list = ', '.join(_sql_text(nid) for nid in node_ids)
        edges = query_rows(
            f"SELECT source_id, target_id, link_type, created_by "
            f"FROM zettel_links WHERE source_id IN ({id_list}) OR target_id IN ({id_list});"
        )
    return {'nodes': nodes, 'edges': edges}


# ── 카파시식 중력 침강 + Rescue ────────────────────────────────────────────

def rescue_note(note_id: str) -> dict | None:
    """오래된 노트를 '재부상'시킨다. last_rescued_at 갱신 + access_count 리셋."""
    ensure_schema()
    now = datetime.now(timezone.utc).isoformat()
    execute(
        f"UPDATE zettel_notes SET last_rescued_at = {_sql_text(now)}, "
        f"updated_at = {_sql_text(now)}, archived = FALSE "
        f"WHERE id = {_sql_text(note_id)};"
    )
    return _get_note_raw(note_id)


def apply_gravity(days_threshold: int = 30, archive: bool = False) -> list[dict]:
    """일정 기간 접근되지 않은 노트를 찾아 반환. archive=True이면 자동 아카이브.

    카파시식 '중력 침강': 오래되고 안 쓰이는 노트는 자연스럽게 가라앉는다.
    """
    ensure_schema()
    days_threshold = max(1, min(days_threshold, 3650))  # 1일 ~ 10년 범위 제한
    sunk = query_rows(
        f"SELECT id, title, note_type, access_count, updated_at, tags::text AS tags_text "
        f"FROM zettel_notes "
        f"WHERE archived = FALSE "
        f"AND note_type != 'permanent' "
        f"AND updated_at < NOW() - INTERVAL '{int(days_threshold)} days' "
        f"ORDER BY access_count ASC, updated_at ASC LIMIT 50;"
    )
    for row in sunk:
        row['tags'] = _parse_tags(row.pop('tags_text', '[]'))

    if archive and sunk:
        ids = ', '.join(_sql_text(r['id']) for r in sunk)
        execute(f"UPDATE zettel_notes SET archived = TRUE WHERE id IN ({ids});")

    return sunk


def get_stats(project: str = '') -> dict:
    """제텔카스텐 통계: 노트/링크 수, 유형별 분포, 최다 연결 노트."""
    ensure_schema()
    proj_filter = f"WHERE project = {_sql_text(project)}" if project else ""
    proj_filter_and = f"AND project = {_sql_text(project)}" if project else ""

    total = query_rows(f"SELECT COUNT(*) AS cnt FROM zettel_notes {proj_filter};")
    by_type = query_rows(
        f"SELECT note_type, COUNT(*) AS cnt FROM zettel_notes {proj_filter} GROUP BY note_type ORDER BY cnt DESC;"
    )
    link_count = query_rows("SELECT COUNT(*) AS cnt FROM zettel_links;")
    # 가장 많이 연결된 노트 (hub)
    hubs = query_rows(
        f"SELECT n.id, n.title, "
        f"(SELECT COUNT(*) FROM zettel_links WHERE source_id = n.id OR target_id = n.id) AS link_cnt "
        f"FROM zettel_notes n WHERE archived = FALSE {proj_filter_and} "
        f"ORDER BY link_cnt DESC LIMIT 5;"
    )
    return {
        'total_notes': total[0]['cnt'] if total else 0,
        'total_links': link_count[0]['cnt'] if link_count else 0,
        'by_type': by_type,
        'top_hubs': hubs,
    }


# ── 유사 노트 탐지 ────────────────────────────────────────────────────────

def find_similar(content: str, tags: list | None = None,
                 exclude_id: str = '', limit: int = 5) -> list[dict]:
    """태그 교집합 + 키워드 ILIKE 매칭으로 유사 노트를 탐지한다.

    1순위: 태그가 겹치는 노트 (태그 교집합 크기 내림차순)
    2순위: 본문 키워드가 겹치는 노트
    """
    ensure_schema()
    if not content and not tags:
        return []

    # 키워드 추출: 내용에서 의미 있는 단어 (3자 이상) 상위 5개
    keywords = _extract_keywords(content, max_words=5)
    tags = tags or []

    # 제외 조건
    exclude_clause = f"AND id != {_sql_text(exclude_id)}" if exclude_id else ""

    results = []

    # 1) 태그 교집합 매칭
    if tags:
        tags_json = json.dumps(tags, ensure_ascii=False)
        tag_rows = query_rows(
            f"SELECT id, title, note_type, tags::text AS tags_text, "
            f"  (SELECT COUNT(*) FROM jsonb_array_elements_text(tags) t "
            f"   WHERE t.value = ANY(ARRAY(SELECT jsonb_array_elements_text({_sql_text(tags_json)}::jsonb)))) AS tag_overlap "
            f"FROM zettel_notes "
            f"WHERE archived = FALSE {exclude_clause} "
            f"ORDER BY tag_overlap DESC, updated_at DESC "
            f"LIMIT {int(limit)};"
        )
        for row in tag_rows:
            row['tags'] = _parse_tags(row.pop('tags_text', '[]'))
            row['similarity_reason'] = 'tag_overlap'
            if int(row.get('tag_overlap', 0)) > 0:
                results.append(row)

    # 2) 키워드 ILIKE 매칭 (태그 매칭이 부족할 때 보충)
    if len(results) < limit and keywords:
        existing_ids = {r['id'] for r in results}
        ilike_conditions = ' OR '.join(
            f"(title ILIKE {_sql_text(f'%{kw}%')} OR content ILIKE {_sql_text(f'%{kw}%')})"
            for kw in keywords
        )
        kw_rows = query_rows(
            f"SELECT id, title, note_type, tags::text AS tags_text "
            f"FROM zettel_notes "
            f"WHERE archived = FALSE {exclude_clause} AND ({ilike_conditions}) "
            f"ORDER BY updated_at DESC "
            f"LIMIT {int(limit)};"
        )
        for row in kw_rows:
            if row['id'] not in existing_ids:
                row['tags'] = _parse_tags(row.pop('tags_text', '[]'))
                row['similarity_reason'] = 'keyword_match'
                results.append(row)

    return results[:limit]


def _extract_keywords(text: str, max_words: int = 5) -> list[str]:
    """텍스트에서 의미 있는 키워드를 추출한다 (3자 이상, 불용어 제외)."""
    if not text:
        return []
    # 한글/영문 단어 추출
    words = re.findall(r'[가-힣a-zA-Z_]{3,}', text)
    # 불용어 제거
    stopwords = {
        'the', 'and', 'for', 'from', 'with', 'that', 'this', 'are', 'was', 'not',
        'def', 'import', 'return', 'class', 'self', 'none', 'true', 'false',
        '있는', '하는', '없는', '되는', '위한', '대한', '통해', '이번',
    }
    filtered = [w for w in words if w.lower() not in stopwords]
    # 빈도순 정렬 후 상위 N개
    from collections import Counter
    counted = Counter(filtered)
    return [word for word, _ in counted.most_common(max_words)]


def refine_note(note_id: str, new_title: str = '', new_content: str = '',
                new_type: str = 'permanent', new_tags: list | None = None) -> dict | None:
    """fleeting/literature 노트를 permanent로 승격한다. 내용 정제 + 유형 변경."""
    ensure_schema()
    note = _get_note_raw(note_id)
    if not note:
        return None

    updates = {'note_type': new_type}
    if new_title:
        updates['title'] = new_title
    if new_content:
        updates['content'] = new_content
    if new_tags is not None:
        updates['tags'] = new_tags

    return update_note(note_id, **updates)


def auto_link(note_id: str, content: str = '', tags: list | None = None,
              created_by: str = 'auto') -> list[dict]:
    """노트 생성 후 유사 노트를 찾아 자동으로 링크를 생성한다."""
    similar = find_similar(content, tags, exclude_id=note_id, limit=3)
    linked = []
    for s in similar:
        if add_link(note_id, s['id'], link_type='relates_to', created_by=created_by):
            linked.append(s)
    return linked


# ── 유틸리티 ───────────────────────────────────────────────────────────────

def _parse_tags(tags_text: str) -> list:
    """JSONB tags 필드 파싱."""
    try:
        return json.loads(tags_text) if tags_text else []
    except (json.JSONDecodeError, TypeError):
        return []
