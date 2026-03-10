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
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        q = params.get('q', [''])[0].strip()
        top_k = int(params.get('top', ['20'])[0])
        show_all = params.get('all', ['false'])[0].lower() == 'true'
        project = '' if show_all else PROJECT_ID
        try:
            ensure_schema(DATA_DIR)
            entries = list_memory(q=q, top_k=top_k, project=project, show_all=show_all)
            handler.wfile.write(json.dumps(entries, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        return True

    if path == '/api/project-info':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
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
        handler.send_header('Access-Control-Allow-Origin', '*')
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
            saved = set_memory(
                key=key,
                content=content,
                title=title,
                tags=tags if isinstance(tags, list) else [],
                author=str(data.get('author', 'unknown')),
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
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        try:
            ensure_schema(DATA_DIR)
            delete_memory(str(data.get('key', '')).strip())
            handler.wfile.write(json.dumps({'status': 'success'}, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    if path == '/api/memory/sync':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
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
