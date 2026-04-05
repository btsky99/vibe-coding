"""
FILE: api/zettel_api.py
DESCRIPTION: Hive Zettelkasten REST API 핸들러.
             카파시 + 루만 융합 메모 시스템의 HTTP 엔드포인트.
REVISION HISTORY:
    2026-04-05 — 초기 구현
"""

import json
from pathlib import Path

from src.pg_store import ensure_schema
from src.zettelkasten import (
    create_note, get_note, update_note, delete_note, list_notes,
    add_link, remove_link, get_graph, rescue_note, apply_gravity,
    get_stats, generate_zettel_id,
)


def _json_response(handler, data: dict | list, status: int = 200):
    """공용 JSON 응답 헬퍼."""
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    handler.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode('utf-8'))


def _error(handler, msg: str, status: int = 400):
    _json_response(handler, {'status': 'error', 'message': msg}, status)


def handle_get(handler, path: str, params: dict,
               DATA_DIR: Path, PROJECT_ID: str, **_kw) -> bool:
    """GET 요청 처리."""

    # 노트 목록
    if path == '/api/zettel/notes':
        ensure_schema(DATA_DIR)
        notes = list_notes(
            project=params.get('project', [''])[0] or '',
            note_type=params.get('type', [''])[0],
            author=params.get('author', [''])[0],
            include_archived=params.get('archived', ['false'])[0].lower() == 'true',
            q=params.get('q', [''])[0],
            order_by=params.get('order', ['updated_at'])[0],
            limit=int(params.get('limit', ['50'])[0]),
            offset=int(params.get('offset', ['0'])[0]),
        )
        _json_response(handler, notes)
        return True

    # 단일 노트 조회
    if path.startswith('/api/zettel/note/'):
        note_id = path.split('/api/zettel/note/')[-1]
        if not note_id:
            _error(handler, 'note_id 필수')
            return True
        ensure_schema(DATA_DIR)
        note = get_note(note_id)
        if not note:
            _error(handler, '노트를 찾을 수 없음', 404)
            return True
        _json_response(handler, note)
        return True

    # 지식 그래프
    if path == '/api/zettel/graph':
        ensure_schema(DATA_DIR)
        project = params.get('project', [''])[0]
        limit = int(params.get('limit', ['200'])[0])
        graph = get_graph(project=project, limit=limit)
        _json_response(handler, graph)
        return True

    # 통계
    if path == '/api/zettel/stats':
        ensure_schema(DATA_DIR)
        project = params.get('project', [''])[0]
        stats = get_stats(project=project)
        _json_response(handler, stats)
        return True

    # 중력 침강 대상 목록
    if path == '/api/zettel/gravity':
        ensure_schema(DATA_DIR)
        days = int(params.get('days', ['30'])[0])
        sunk = apply_gravity(days_threshold=days, archive=False)
        _json_response(handler, sunk)
        return True

    # 분기 번호 미리보기
    if path == '/api/zettel/next-id':
        ensure_schema(DATA_DIR)
        parent = params.get('parent', [''])[0]
        _json_response(handler, {'next_id': generate_zettel_id(parent)})
        return True

    return False


def handle_post(handler, path: str, data: dict,
                DATA_DIR: Path, PROJECT_ID: str, **_kw) -> bool:
    """POST 요청 처리."""

    # 노트 생성
    if path == '/api/zettel/notes':
        title = str(data.get('title', '')).strip()
        if not title:
            _error(handler, 'title 필수')
            return True
        ensure_schema(DATA_DIR)
        tags = data.get('tags', [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(',') if t.strip()]
        note = create_note(
            title=title,
            content=str(data.get('content', '')),
            note_type=str(data.get('note_type', 'fleeting')),
            author=str(data.get('author', 'unknown')),
            project=str(data.get('project', PROJECT_ID)) or PROJECT_ID,
            tags=tags,
            source_ref=str(data.get('source_ref', '')),
            parent_id=str(data.get('parent_id', '')),
            custom_id=str(data.get('id', '')),
        )
        if not note:
            _error(handler, '노트 생성 실패', 500)
            return True
        _json_response(handler, {'status': 'success', 'note': note}, 201)
        return True

    # 노트 수정 (delete/rescue/link 경로는 제외)
    if path.startswith('/api/zettel/note/') and not path.endswith('/link') \
       and not path.endswith('/rescue') and not path.endswith('/delete'):
        note_id = path.split('/api/zettel/note/')[-1]
        ensure_schema(DATA_DIR)
        tags = data.get('tags')
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(',') if t.strip()]
            data['tags'] = tags
        note = update_note(note_id, **{k: v for k, v in data.items()
                                       if k in ('title', 'content', 'note_type', 'tags', 'source_ref', 'archived')})
        if not note:
            _error(handler, '노트를 찾을 수 없음', 404)
            return True
        _json_response(handler, {'status': 'success', 'note': note})
        return True

    # 링크 추가
    if path == '/api/zettel/link':
        source = str(data.get('source_id', '')).strip()
        target = str(data.get('target_id', '')).strip()
        if not source or not target:
            _error(handler, 'source_id, target_id 필수')
            return True
        ensure_schema(DATA_DIR)
        ok = add_link(
            source_id=source,
            target_id=target,
            link_type=str(data.get('link_type', 'relates_to')),
            created_by=str(data.get('created_by', 'system')),
        )
        _json_response(handler, {'status': 'success' if ok else 'error'})
        return True

    # Rescue (재부상)
    if path.endswith('/rescue') and '/api/zettel/note/' in path:
        note_id = path.replace('/rescue', '').split('/api/zettel/note/')[-1]
        ensure_schema(DATA_DIR)
        note = rescue_note(note_id)
        if not note:
            _error(handler, '노트를 찾을 수 없음', 404)
            return True
        _json_response(handler, {'status': 'success', 'note': note})
        return True

    # 노트 삭제 (POST 방식 — server.py에 DELETE 핸들러 없음)
    if path.startswith('/api/zettel/note/') and path.endswith('/delete'):
        note_id = path.replace('/delete', '').split('/api/zettel/note/')[-1]
        ensure_schema(DATA_DIR)
        ok = delete_note(note_id)
        _json_response(handler, {'status': 'success' if ok else 'error'})
        return True

    # 링크 삭제 (POST 방식)
    if path == '/api/zettel/link/delete':
        source = str(data.get('source_id', '')).strip()
        target = str(data.get('target_id', '')).strip()
        if not source or not target:
            _error(handler, 'source_id, target_id 필수')
            return True
        ensure_schema(DATA_DIR)
        ok = remove_link(source, target, str(data.get('link_type', '')))
        _json_response(handler, {'status': 'success' if ok else 'error'})
        return True

    # 중력 침강 실행 (아카이브)
    if path == '/api/zettel/gravity':
        days = int(data.get('days', 30))
        ensure_schema(DATA_DIR)
        archived = apply_gravity(days_threshold=days, archive=True)
        _json_response(handler, {'status': 'success', 'archived_count': len(archived), 'notes': archived})
        return True

    return False


