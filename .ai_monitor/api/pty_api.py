"""
FILE: api/pty_api.py
DESCRIPTION: PTY 세션 상태 및 제어 엔드포인트 — Node PTY 서버 REST 프록시.
  프론트엔드와 Discord 브릿지가 기존 /api/pty/* URL을 그대로 사용할 수 있도록
  Node PTY 서버(pty-server.js)의 REST API를 투명하게 프록시합니다.

REVISION HISTORY:
- 2026-03-22 Claude: Node PTY 서버 REST 프록시로 전면 재작성 (pywinpty 직접 접근 제거)
- 2026-03-12 Claude: Initial extraction for Discord PTY-first remote control
"""

import json
import urllib.request
import urllib.error

# Node PTY 서버 REST URL — server.py __main__에서 set_pty_rest_url()로 주입
_node_pty_url = None


def set_pty_rest_url(url: str) -> None:
    """Node PTY 서버의 REST 기본 URL을 설정합니다. (예: http://127.0.0.1:9001)"""
    global _node_pty_url
    _node_pty_url = url


# ── 하위 호환: 기존 getter 방식 유지 (사용하지 않지만 import 에러 방지) ──────
def set_pty_sessions_getter(getter) -> None:
    """[Deprecated] Node PTY 전환으로 더 이상 사용하지 않음. set_pty_rest_url() 사용."""
    pass

def set_pty_output_getter(getter) -> None:
    """[Deprecated] Node PTY 전환으로 더 이상 사용하지 않음. set_pty_rest_url() 사용."""
    pass


def _node_get(path: str, timeout: float = 2.0):
    """Node PTY 서버에 GET 요청을 보내고 JSON 응답을 반환합니다."""
    if not _node_pty_url:
        return None
    try:
        req = urllib.request.Request(f"{_node_pty_url}{path}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return None


def _node_post(path: str, data: dict = None, timeout: float = 5.0):
    """Node PTY 서버에 POST 요청을 보내고 JSON 응답을 반환합니다."""
    if not _node_pty_url:
        return None
    try:
        payload = json.dumps(data or {}).encode('utf-8')
        req = urllib.request.Request(
            f"{_node_pty_url}{path}",
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode('utf-8'))
        except Exception:
            return {'error': str(e)}
    except Exception as e:
        return {'error': str(e)}


def _json_response(handler, payload, status=200) -> None:
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()
    handler.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))


def _read_body(handler):
    content_length = int(handler.headers.get('Content-Length', 0))
    if not content_length:
        return {}
    raw = handler.rfile.read(content_length)
    if not raw:
        return {}
    return json.loads(raw.decode('utf-8'))


def _resolve_target(data) -> str:
    target = data.get('target', data.get('terminal_id', ''))
    if target is None:
        return ''
    target_str = str(target).strip().upper()
    if target_str.startswith('T'):
        target_str = target_str[1:]
    return target_str


def handle_get(handler, path: str, params: dict | None = None) -> None:
    """프론트엔드/Discord 브릿지의 GET 요청을 Node PTY 서버로 프록시합니다."""

    if path in ('/api/pty/terminals', '/api/pty/status'):
        # Node PTY 서버에서 세션 스냅샷 조회
        result = _node_get('/api/pty/sessions')
        _json_response(handler, result or {})
        return

    if path == '/api/pty/models':
        # CLI별 사용 가능한 모델 목록 조회 (오피스 워크스페이스 프로필용)
        result = _node_get('/api/pty/models')
        _json_response(handler, result or {})
        return

    if path == '/api/pty/output':
        params = params or {}
        target = _resolve_target({
            'terminal_id': (params.get('terminal_id') or [''])[0],
            'target': (params.get('target') or [''])[0],
        })
        if not target:
            _json_response(handler, {'error': 'missing_target'}, 400)
            return

        since = (params.get('since') or ['0'])[0]
        limit = (params.get('limit') or ['80'])[0]

        # Node PTY 서버로 출력 버퍼 조회 프록시
        result = _node_get(f'/api/pty/output/{target}?since={since}&limit={limit}')
        if result is None:
            _json_response(handler, {
                'terminal_id': f'T{target}',
                'entries': [],
                'latest_seq': 0,
                'running': False,
            })
        else:
            _json_response(handler, result)
        return

    _json_response(handler, {'error': 'not_found', 'path': path}, 404)


def handle_post(handler, path: str) -> None:
    """프론트엔드/Discord 브릿지의 POST 요청을 Node PTY 서버로 프록시합니다."""

    if path not in ('/api/pty/interrupt', '/api/pty/terminate', '/api/pty/write'):
        _json_response(handler, {'error': 'not_found', 'path': path}, 404)
        return

    try:
        data = _read_body(handler)
    except Exception as exc:
        _json_response(handler, {'error': 'invalid_json', 'detail': str(exc)}, 400)
        return

    target = _resolve_target(data)
    if not target:
        _json_response(handler, {'error': 'missing_target'}, 400)
        return

    # Node PTY 서버의 해당 엔드포인트로 프록시
    if path == '/api/pty/write':
        # PTY write: 텔레그램 → 기존 터미널에 텍스트 주입
        result = _node_post(f'/api/pty/write/{target}', data)
    else:
        action = 'interrupt' if path == '/api/pty/interrupt' else 'terminate'
        result = _node_post(f'/api/pty/{action}/{target}')

    if result is None:
        _json_response(handler, {'error': 'node_pty_unreachable'}, 502)
    elif 'error' in result:
        status = 404 if result['error'] == 'not_running' else 500
        _json_response(handler, result, status)
    else:
        _json_response(handler, result)
