"""
FILE: api/memory_api.py
DESCRIPTION: Postgres-first memory API handlers.
"""

import json
import time
from pathlib import Path

from src.pg_store import (
    ensure_schema,
    list_memory,
    set_memory,
    delete_memory,
    migrate_legacy_data,
)


def handle_get(handler, path: str, params: dict,
               DATA_DIR: Path, PROJECT_ID: str, PROJECT_ROOT: Path,
               _memory_conn, _embed, _cosine_sim,
               __version__: str) -> bool:
    if path == '/api/memory':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        q = params.get('q', [''])[0].strip()
        top_k = int(params.get('top', ['20'])[0])
        show_all = params.get('all', ['false'])[0].lower() == 'true'
        author = params.get('author', [''])[0].strip()
        include_zettel = params.get('include_zettel', ['false'])[0].lower() == 'true'
        project = '' if show_all else PROJECT_ID
        try:
            ensure_schema(DATA_DIR)
            entries = list_memory(
                q=q, top_k=top_k, project=project, show_all=show_all,
                author=author, include_zettel=include_zettel,
            )
            handler.wfile.write(json.dumps(entries, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        return True

    if path == '/api/project-info':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        handler.wfile.write(json.dumps({
            'project_id': PROJECT_ID,
            'project_name': PROJECT_ROOT.name,
            'project_root': str(PROJECT_ROOT).replace('\\', '/'),
            'version': __version__,
        }, ensure_ascii=False).encode('utf-8'))
        return True

    return False


def handle_post(handler, path: str, data: dict,
                DATA_DIR: Path, PROJECT_ID: str,
                _memory_conn, _embed) -> bool:
    if path == '/api/memory/set':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            key = str(data.get('key', '')).strip()[:200]
            content = str(data.get('content', '')).strip()
            if not key or not content:
                handler.wfile.write(json.dumps(
                    {'status': 'error', 'message': 'key and content are required'}
                ).encode('utf-8'))
                return True

            now = time.strftime('%Y-%m-%dT%H:%M:%S')
            title = str(data.get('title', key)).strip()[:300]
            project = str(data.get('project', PROJECT_ID)).strip() or PROJECT_ID
            tags = data.get('tags', [])
            if isinstance(tags, str):
                tags = [tag.strip() for tag in tags.split(',') if tag.strip()]

            ensure_schema(DATA_DIR)
            # author 미지정 시 None 전달 — pg_store._resolve_author()가 env 우선 처리
            author_raw = data.get('author')
            saved = set_memory(
                key=key,
                content=content,
                title=title,
                tags=tags if isinstance(tags, list) else [],
                author=str(author_raw) if author_raw else None,
                project=project,
                created_at=now,
                updated_at=now,
            )
            handler.wfile.write(json.dumps(
                {'status': 'success', 'entry': saved or {}}, ensure_ascii=False
            ).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    if path == '/api/memory/delete':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            ensure_schema(DATA_DIR)
            delete_memory(str(data.get('key', '')).strip())
            handler.wfile.write(json.dumps({'status': 'success'}, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    if path == '/api/memory/share':
        # 크로스 프로젝트 지식 공유 — 현재 프로젝트 메모리를 글로벌로 승격
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            key = str(data.get('key', '')).strip()
            if not key:
                handler.wfile.write(json.dumps(
                    {'status': 'error', 'message': 'key is required'}
                ).encode('utf-8'))
                return True

            from src.pg_store import get_memory
            ensure_schema(DATA_DIR)
            entry = get_memory(key)
            if not entry:
                handler.wfile.write(json.dumps(
                    {'status': 'error', 'message': 'Memory entry not found'}
                ).encode('utf-8'))
                return True

            # project를 __global__로 변경하여 모든 프로젝트에서 접근 가능하게 함
            saved = set_memory(
                key=key,
                content=entry.get('content', ''),
                title=entry.get('title', key),
                tags=entry.get('tags', []),
                author=entry.get('author', 'unknown'),
                project='__global__',
                updated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
            )
            handler.wfile.write(json.dumps(
                {'status': 'success', 'entry': saved or {}, 'message': f'"{key}" 글로벌 공유 완료'},
                ensure_ascii=False
            ).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    if path == '/api/memory/sync':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
        handler.end_headers()
        try:
            ensure_schema(DATA_DIR)
            migrate_legacy_data(DATA_DIR)
            handler.wfile.write(json.dumps(
                {'status': 'ok', 'message': 'legacy memory migrated to PostgreSQL', 'merged': 0, 'skipped': 0},
                ensure_ascii=False
            ).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    return False
