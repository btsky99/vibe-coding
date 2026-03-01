"""
FILE: api/mcp_api.py
DESCRIPTION: /api/mcp/* 엔드포인트 핸들러 모듈.
             MCP(Model Context Protocol) 카탈로그 조회, Smithery 레지스트리 검색,
             MCP 설치/제거/API키 관리 기능을 담당합니다.
             server.py에서 MCP 관련 로직을 분리하여 유지보수성을 향상시킵니다.

REVISION HISTORY:
- 2026-03-01 Claude: server.py에서 분리 — mcp/* API 핸들러 담당
"""

import json
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode


def handle_get(handler, path: str, params: dict,
               _smithery_api_key, _mcp_config_path) -> bool:
    """GET 요청 처리 — /api/mcp/catalog, /api/mcp/apikey,
    /api/mcp/search, /api/mcp/installed 담당.

    반환값: 경로가 처리됐으면 True, 해당 없으면 False.
    """

    # ── /api/mcp/catalog ──────────────────────────────────────────────────
    if path == '/api/mcp/catalog':
        # 내장 큐레이션 MCP 서버 목록 — 외부 의존 없이 바로 반환
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        catalog = [
            {
                "name": "context7",
                "package": "@upstash/context7-mcp",
                "description": "최신 라이브러리 공식 문서를 실시간으로 조회합니다",
                "category": "문서",
                "args": [],
            },
            {
                "name": "github",
                "package": "@modelcontextprotocol/server-github",
                "description": "GitHub API — 이슈, PR, 저장소 조회·관리",
                "category": "개발",
                "requiresEnv": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
                "args": [],
            },
            {
                "name": "memory",
                "package": "@modelcontextprotocol/server-memory",
                "description": "세션 간 메모리를 유지합니다 (지식 그래프 기반)",
                "category": "AI",
                "args": [],
            },
            {
                "name": "fetch",
                "package": "@modelcontextprotocol/server-fetch",
                "description": "URL에서 웹페이지 내용을 가져와 마크다운으로 변환합니다",
                "category": "검색",
                "args": [],
            },
            {
                "name": "playwright",
                "package": "@playwright/mcp",
                "description": "Playwright 브라우저 자동화 — 스크린샷, 폼 입력, 클릭",
                "category": "브라우저",
                "args": [],
            },
            {
                "name": "sequential-thinking",
                "package": "@modelcontextprotocol/server-sequential-thinking",
                "description": "복잡한 문제를 단계적으로 분해하여 사고합니다",
                "category": "AI",
                "args": [],
            },
            {
                "name": "sqlite",
                "package": "@modelcontextprotocol/server-sqlite",
                "description": "SQLite 데이터베이스에 직접 쿼리합니다",
                "category": "DB",
                "args": [],
            },
            {
                "name": "brave-search",
                "package": "@modelcontextprotocol/server-brave-search",
                "description": "Brave Search API로 웹 검색합니다",
                "category": "검색",
                "requiresEnv": ["BRAVE_API_KEY"],
                "args": [],
            },
        ]
        handler.wfile.write(json.dumps(catalog, ensure_ascii=False).encode('utf-8'))
        return True

    # ── /api/mcp/apikey (GET) ─────────────────────────────────────────────
    elif path == '/api/mcp/apikey':
        # Smithery API 키 조회 — 저장된 키의 마스킹 처리
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        key = _smithery_api_key()
        masked = (key[:6] + '…' + key[-4:]) if len(key) > 12 else ('*' * len(key) if key else '')
        handler.wfile.write(json.dumps({'has_key': bool(key), 'masked': masked}).encode('utf-8'))
        return True

    # ── /api/mcp/search ───────────────────────────────────────────────────
    elif path == '/api/mcp/search':
        # Smithery 레지스트리 검색 — ?q=...&page=1&pageSize=20
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        q       = params.get('q',        [''])[0].strip()
        page    = int(params.get('page',     ['1'])[0])
        page_sz = int(params.get('pageSize', ['20'])[0])
        api_key = _smithery_api_key()
        if not api_key:
            handler.wfile.write(json.dumps({
                'error': 'NO_KEY',
                'message': 'Smithery API 키가 설정되지 않았습니다'
            }).encode('utf-8'))
            return True
        if not q:
            handler.wfile.write(json.dumps({
                'servers': [],
                'pagination': {'currentPage': 1, 'totalPages': 0, 'totalCount': 0}
            }).encode('utf-8'))
            return True
        try:
            query_str = urlencode({'q': q, 'page': page, 'pageSize': page_sz})
            req = urllib.request.Request(
                f'https://registry.smithery.ai/servers?{query_str}',
                headers={'Authorization': f'Bearer {api_key}', 'Accept': 'application/json'},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            handler.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
        except urllib.error.HTTPError as e:
            code = e.code
            msg = 'API 키가 유효하지 않습니다' if code == 401 else f'Smithery API 오류 ({code})'
            handler.wfile.write(json.dumps({'error': f'HTTP_{code}', 'message': msg}).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'error': 'NETWORK', 'message': str(e)}).encode('utf-8'))
        return True

    # ── /api/mcp/installed ────────────────────────────────────────────────
    elif path == '/api/mcp/installed':
        # 설치 현황 조회 — ?tool=claude|gemini&scope=global|project
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        tool  = params.get('tool',  ['claude'])[0]
        scope = params.get('scope', ['global'])[0]
        config_path = _mcp_config_path(tool, scope)
        try:
            if config_path.exists():
                data = json.loads(config_path.read_text(encoding='utf-8'))
                installed = list(data.get('mcpServers', {}).keys())
            else:
                installed = []
            handler.wfile.write(json.dumps({'installed': installed}, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'installed': [], 'error': str(e)}).encode('utf-8'))
        return True

    return False


def handle_post(handler, path: str, data: dict,
                _smithery_api_key_setter,  # DATA_DIR / 'smithery_config.json' Path
                _mcp_config_path) -> bool:
    """POST 요청 처리 — /api/mcp/apikey, /api/mcp/install, /api/mcp/uninstall 담당.

    _smithery_api_key_setter: smithery_config.json Path 객체
    (쓰기 경로로 사용, server.py의 _SMITHERY_CFG 전달)

    반환값: 처리됐으면 True, 해당 없으면 False.
    """

    # ── /api/mcp/apikey (POST) — Smithery API 키 저장 ────────────────────
    if path == '/api/mcp/apikey':
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        try:
            api_key = str(data.get('api_key', '')).strip()
            _smithery_api_key_setter.write_text(
                json.dumps({'api_key': api_key}, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
            handler.wfile.write(json.dumps({'status': 'success'}).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    # ── /api/mcp/install ─────────────────────────────────────────────────
    elif path == '/api/mcp/install':
        # MCP 설치 — config 파일의 mcpServers 키에 엔트리 추가
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        try:
            tool    = str(data.get('tool',    'claude'))
            scope   = str(data.get('scope',   'global'))
            name    = str(data.get('name',    ''))
            package = str(data.get('package', ''))
            req_env = data.get('requiresEnv', [])

            if not name or not package:
                handler.wfile.write(json.dumps({'status': 'error', 'message': 'name·package 필수'}).encode('utf-8'))
                return True

            config_path = _mcp_config_path(tool, scope)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
            if 'mcpServers' not in config:
                config['mcpServers'] = {}

            # mcpServers 엔트리 구성 (필수 환경변수가 있으면 플레이스홀더 삽입)
            entry: dict = {"command": "npx", "args": ["-y", package]}
            if req_env:
                entry["env"] = {k: f"<YOUR_{k}>" for k in req_env}
            config['mcpServers'][name] = entry

            config_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
            msg = f"MCP '{name}' 설치 완료 → {config_path}"
            if req_env:
                msg += f" | 환경변수 필요: {', '.join(req_env)}"
            handler.wfile.write(json.dumps({'status': 'success', 'message': msg}).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    # ── /api/mcp/uninstall ───────────────────────────────────────────────
    elif path == '/api/mcp/uninstall':
        # MCP 제거 — config 파일의 mcpServers 에서 해당 키 삭제
        handler.send_response(200)
        handler.send_header('Content-Type', 'application/json;charset=utf-8')
        handler.send_header('Access-Control-Allow-Origin', '*')
        handler.end_headers()
        try:
            tool  = str(data.get('tool',  'claude'))
            scope = str(data.get('scope', 'global'))
            name  = str(data.get('name',  ''))

            if not name:
                handler.wfile.write(json.dumps({'status': 'error', 'message': 'name 필수'}).encode('utf-8'))
                return True

            config_path = _mcp_config_path(tool, scope)
            if not config_path.exists():
                handler.wfile.write(json.dumps({'status': 'error', 'message': '설정 파일 없음'}).encode('utf-8'))
                return True

            config  = json.loads(config_path.read_text(encoding='utf-8'))
            servers = config.get('mcpServers', {})
            if name in servers:
                del servers[name]
                config['mcpServers'] = servers
                config_path.write_text(
                    json.dumps(config, ensure_ascii=False, indent=2),
                    encoding='utf-8'
                )
                handler.wfile.write(json.dumps({'status': 'success', 'message': f"MCP '{name}' 제거 완료"}).encode('utf-8'))
            else:
                handler.wfile.write(json.dumps({'status': 'error', 'message': f"'{name}' 항목 없음"}).encode('utf-8'))
        except Exception as e:
            handler.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode('utf-8'))
        return True

    return False
