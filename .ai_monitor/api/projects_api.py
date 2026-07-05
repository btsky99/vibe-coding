"""
FILE: api/projects_api.py
DESCRIPTION: 최근 프로젝트 목록 API — projects.json에 최근 연 프로젝트 경로를 MRU(최대 20개)로
             관리한다. GET=목록 반환, POST=경로 추가(최상단). server.py do_GET/do_POST에서 위임.

REVISION HISTORY:
- 2026-07-05 Claude: server.py '/api/projects' GET/POST 블록 분리(long-tail 라운드). 로직 원본 동일.
"""
from __future__ import annotations

import json
from pathlib import Path


def _load(projects_file: Path) -> list:
    if projects_file.exists():
        try:
            with open(projects_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def handle_get(handler, projects_file: Path) -> None:
    """GET /api/projects — 최근 프로젝트 경로 목록 반환."""
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    handler.wfile.write(json.dumps(_load(projects_file)).encode('utf-8'))


def handle_post(handler, projects_file: Path) -> None:
    """POST /api/projects — {path} 를 MRU 최상단에 추가(중복 제거, 최대 20개)."""
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    try:
        data = json.loads(handler.rfile.read(int(handler.headers['Content-Length'])).decode('utf-8'))
        new_path = data.get('path', '').strip().replace('\\', '/')
        if not new_path:
            handler.wfile.write(json.dumps({"error": "Invalid path"}).encode('utf-8'))
            return

        projects = _load(projects_file)
        if new_path in projects:
            projects.remove(new_path)
        projects.insert(0, new_path)   # 최신 프로젝트를 위로
        projects = projects[:20]       # 최대 20개
        with open(projects_file, 'w', encoding='utf-8') as f:
            json.dump(projects, f, ensure_ascii=False, indent=2)

        handler.wfile.write(json.dumps({"status": "success", "projects": projects}).encode('utf-8'))
    except Exception as e:
        handler.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
