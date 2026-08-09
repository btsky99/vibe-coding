"""
FILE: api/pty_api.py
DESCRIPTION: PTY 세션 상태 및 제어 엔드포인트 — Node PTY 서버 투명 프록시.
  /api/pty/* 요청을 Node PTY 서버로 그대로 전달한다 (패스스루).
  일부 레거시 경로(/api/pty/terminals, /api/pty/output)만 변환 처리하고,
  나머지는 Node PTY 서버의 경로를 그대로 사용한다.
  → Node PTY 서버에 엔드포인트를 추가해도 이 파일 수정 불필요.

REVISION HISTORY:
- 2026-04-12 Claude: 패스스루 프록시로 전면 재작성 (엔드포인트 나열 방식 폐기)
- 2026-03-22 Claude: Node PTY 서버 REST 프록시로 전면 재작성 (pywinpty 직접 접근 제거)
- 2026-03-12 Claude: Initial extraction for Discord PTY-first remote control
"""

import json
import urllib.request
import urllib.error
from urllib.parse import urlencode, urlparse, parse_qs

# Node PTY 서버 REST URL — server.py __main__에서 set_pty_rest_url()로 주입
_node_pty_url = None


def set_pty_rest_url(url: str) -> None:
    """Node PTY 서버의 REST 기본 URL을 설정합니다. (예: http://127.0.0.1:9001)"""
    global _node_pty_url
    _node_pty_url = url


def get_pty_rest_url() -> str:
    """현재 Node PTY REST URL. 아직 주입 전이면 빈 문자열.

    [WHY 게터인가] 슬롯 포트는 런타임에 정해져 import 시점 상수가 될 수 없다. 소비자가
      모듈 전역을 직접 읽으면 import 시점 값(None)이 박히므로 반드시 호출 시점에 읽는다.
    """
    return _node_pty_url or ''


# ── 하위 호환: 기존 getter 방식 유지 (사용하지 않지만 import 에러 방지) ──────
def set_pty_sessions_getter(getter) -> None:
    pass

def set_pty_output_getter(getter) -> None:
    pass


def _node_get(path: str, timeout: float = 3.0):
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


# [중복통합 2026-07-18] _json_response/_read_body는 api/_common.py로 통합 — 패스스루 재노출.
# [동작변경] 기존 pty 사본은 malformed JSON에서 예외를 던졌으나 통합본은 방어형({}) — 회귀 아닌 개선.
from api._common import json_response as _json_response, read_body as _read_body


def _resolve_target(data) -> str:
    target = data.get('target', data.get('terminal_id', ''))
    if target is None:
        return ''
    target_str = str(target).strip().upper()
    if target_str.startswith('T'):
        target_str = target_str[1:]
    return target_str


def _extract_project_id(handler, params: dict | None = None) -> str:
    """Phase 2-5.3a: handler.path 또는 params에서 project_id 쿼리 추출."""
    if params:
        raw = params.get('project_id') or []
        if raw and raw[0]:
            return str(raw[0]).strip()
    try:
        qs = parse_qs(urlparse(handler.path).query)
        raw = qs.get('project_id') or []
        return str(raw[0]).strip() if raw else ''
    except Exception:
        return ''


def handle_get(handler, path: str, params: dict | None = None) -> None:
    """
    GET /api/pty/* → Node PTY 서버로 투명 프록시.
    레거시 경로만 변환하고, 나머지는 그대로 전달.
    Phase 2-5.3a: 모든 경로에 project_id 쿼리 자동 전달.
    """
    project_id = _extract_project_id(handler, params)
    pid_qs = f'&project_id={project_id}' if project_id else ''

    # ── 레거시 경로 변환 ──
    if path in ('/api/pty/terminals', '/api/pty/status'):
        target_path = '/api/pty/sessions'
        if project_id:
            target_path += f'?project_id={project_id}'
        result = _node_get(target_path)
        _json_response(handler, result or {})
        return

    if path == '/api/pty/output':
        # 레거시: query param으로 target 전달 → /api/pty/output/{target} 변환
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
        result = _node_get(f'/api/pty/output/{target}?since={since}&limit={limit}{pid_qs}')
        if result is None:
            _json_response(handler, {
                'terminal_id': f'T{target}',
                'entries': [], 'latest_seq': 0, 'running': False,
            })
        else:
            _json_response(handler, result)
        return

    # ── 패스스루: 그대로 Node PTY 서버로 전달 ──
    # query string 복원
    qs = ''
    if params:
        flat = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in params.items()}
        qs = '?' + urlencode(flat, doseq=True) if flat else ''

    result = _node_get(f'{path}{qs}')
    if result is not None:
        _json_response(handler, result)
    else:
        _json_response(handler, {'error': 'node_pty_unreachable', 'path': path}, 502)


def handle_post(handler, path: str) -> None:
    """
    POST /api/pty/* → Node PTY 서버로 투명 프록시.
    레거시 경로만 변환하고, 나머지는 그대로 전달.
    Phase 2-5.3a: 모든 경로에 project_id 쿼리 자동 전달.
    """
    project_id = _extract_project_id(handler)
    pid_qs = f'?project_id={project_id}' if project_id else ''

    # ── 레거시 경로 변환 (body에 target이 있는 경우 → URL path로 변환) ──
    if path in ('/api/pty/interrupt', '/api/pty/terminate', '/api/pty/write'):
        try:
            data = _read_body(handler)
        except Exception as exc:
            _json_response(handler, {'error': 'invalid_json', 'detail': str(exc)}, 400)
            return

        target = _resolve_target(data)
        if not target:
            _json_response(handler, {'error': 'missing_target'}, 400)
            return

        # body에 project_id가 있으면 우선 사용 (외부 connector 호출 호환)
        body_pid = str(data.get('project_id') or '').strip()
        if body_pid:
            pid_qs = f'?project_id={body_pid}'

        if path == '/api/pty/write':
            result = _node_post(f'/api/pty/write/{target}{pid_qs}', data)
        else:
            action = 'interrupt' if path == '/api/pty/interrupt' else 'terminate'
            result = _node_post(f'/api/pty/{action}/{target}{pid_qs}')

        if result is None:
            _json_response(handler, {'error': 'node_pty_unreachable'}, 502)
        elif 'error' in result:
            status = 404 if result.get('error') == 'not_running' else 500
            _json_response(handler, result, status)
        else:
            _json_response(handler, result)
        return

    # ── 패스스루: 그대로 Node PTY 서버로 전달 ──
    try:
        data = _read_body(handler)
    except Exception as exc:
        _json_response(handler, {'error': 'invalid_json', 'detail': str(exc)}, 400)
        return

    result = _node_post(path, data)
    if result is None:
        _json_response(handler, {'error': 'node_pty_unreachable'}, 502)
    elif 'error' in result:
        status = 404 if result.get('error') == 'not_running' else 500
        _json_response(handler, result, status)
    else:
        _json_response(handler, result)


def _node_delete(path: str, timeout: float = 5.0):
    """Node PTY 서버에 DELETE 요청을 보내고 JSON 응답을 반환합니다."""
    if not _node_pty_url:
        return None
    try:
        req = urllib.request.Request(f"{_node_pty_url}{path}", method='DELETE')
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode('utf-8'))
        except Exception:
            return {'error': str(e)}
    except Exception as e:
        return {'error': str(e)}


def handle_delete(handler, path: str) -> None:
    """
    DELETE /api/pty/* → Node PTY 서버로 투명 프록시.
    Phase 2-5.3a: project_id 쿼리 자동 전달.
    """
    project_id = _extract_project_id(handler)
    pid_qs = f'?project_id={project_id}' if project_id else ''
    result = _node_delete(f'{path}{pid_qs}')
    if result is None:
        _json_response(handler, {'error': 'node_pty_unreachable'}, 502)
    elif 'error' in result:
        status = 400 if result.get('error') == 'missing_project_id' else 500
        _json_response(handler, result, status)
    else:
        _json_response(handler, result)
