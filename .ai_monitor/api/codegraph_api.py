"""
FILE: api/codegraph_api.py
DESCRIPTION: 코드 인텔리전스 REST API 핸들러.
             tree-sitter AST 인덱싱 + BM25 검색 + 코드 그래프 시각화.
REVISION HISTORY:
    2026-04-14 — 초기 구현. MindVault 영감 기반 코드 그래프 시스템
"""

import json
from pathlib import Path

from src.pg_store import ensure_schema
from src.code_indexer import (
    register_project, list_projects, index_project, get_indexing_status,
)
from src.code_search import search_code, get_graph_data, get_impact_analysis


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

    # 프로젝트 목록 조회
    if path == '/api/codegraph/projects':
        ensure_schema(DATA_DIR)
        projects = list_projects()
        _json_response(handler, projects)
        return True

    # BM25 코드 검색
    if path == '/api/codegraph/search':
        ensure_schema(DATA_DIR)
        q = params.get('q', [''])[0]
        pid = params.get('project_id', [''])[0]
        ntype = params.get('node_type', [''])[0]
        limit = int(params.get('limit', ['30'])[0])

        results = search_code(
            query=q,
            project_id=int(pid) if pid else None,
            node_type=ntype or None,
            limit=limit,
        )
        _json_response(handler, results)
        return True

    # 코드 그래프 데이터
    if path == '/api/codegraph/graph':
        ensure_schema(DATA_DIR)
        pid = params.get('project_id', [''])[0]
        if not pid:
            _error(handler, 'project_id 필수')
            return True
        data = get_graph_data(int(pid))
        _json_response(handler, data)
        return True

    # 영향 분석
    if path == '/api/codegraph/impact':
        ensure_schema(DATA_DIR)
        node_id = params.get('node_id', [''])[0]
        depth = int(params.get('depth', ['3'])[0])
        if not node_id:
            _error(handler, 'node_id 필수')
            return True
        data = get_impact_analysis(int(node_id), depth=depth)
        _json_response(handler, data)
        return True

    # 인덱싱 상태 조회
    if path == '/api/codegraph/status':
        pid = params.get('project_id', [''])[0]
        if not pid:
            _error(handler, 'project_id 필수')
            return True
        status = get_indexing_status(int(pid))
        _json_response(handler, status)
        return True

    return False


def handle_post(handler, path: str, data: dict,
                DATA_DIR: Path, PROJECT_ID: str, **_kw) -> bool:
    """POST 요청 처리."""

    # 프로젝트 등록
    if path == '/api/codegraph/register':
        ensure_schema(DATA_DIR)
        name = data.get('name', '')
        root_path = data.get('root_path', '')
        if not root_path:
            _error(handler, 'root_path 필수')
            return True
        if not name:
            name = Path(root_path).name

        pid = register_project(name, root_path)
        if pid is None:
            _error(handler, '프로젝트 등록 실패', 500)
            return True
        _json_response(handler, {'status': 'ok', 'project_id': pid, 'name': name})
        return True

    # 인덱싱 실행
    if path == '/api/codegraph/index':
        ensure_schema(DATA_DIR)
        pid = data.get('project_id')
        root_path = data.get('root_path', '')

        if not pid and not root_path:
            _error(handler, 'project_id 또는 root_path 필수')
            return True

        # root_path로 프로젝트 조회/등록
        if not pid and root_path:
            name = data.get('name', '') or Path(root_path).name
            pid = register_project(name, root_path)

        if not pid:
            _error(handler, '프로젝트를 찾을 수 없음', 404)
            return True

        # root_path 조회
        if not root_path:
            from src.pg_store import query_rows
            rows = query_rows(f"SELECT root_path FROM code_projects WHERE id = {int(pid)} LIMIT 1;")
            if rows:
                root_path = rows[0]['root_path']
            else:
                _error(handler, '프로젝트를 찾을 수 없음', 404)
                return True

        background = data.get('background', True)
        result = index_project(int(pid), root_path, background=background)
        _json_response(handler, result)
        return True

    return False
