"""
FILE: api/pty_api.py
DESCRIPTION: PTY session status and control endpoints used by remote bridges.

REVISION HISTORY:
- 2026-03-12 Claude: Initial extraction for Discord PTY-first remote control
"""

import json

_pty_sessions_getter = None  # callable: () -> dict
_pty_output_getter = None  # callable: () -> dict[str, list[dict]]


def set_pty_sessions_getter(getter) -> None:
    """Register a callback that returns the live PTY session dict."""
    global _pty_sessions_getter
    _pty_sessions_getter = getter


def set_pty_output_getter(getter) -> None:
    """Register a callback that returns recent PTY output buffers."""
    global _pty_output_getter
    _pty_output_getter = getter


def _json_response(handler, payload, status=200) -> None:
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', '*')
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


def _get_sessions() -> dict:
    if _pty_sessions_getter is None:
        return {}
    try:
        return _pty_sessions_getter() or {}
    except Exception:
        return {}


def _get_output_buffers() -> dict:
    if _pty_output_getter is None:
        return {}
    try:
        return _pty_output_getter() or {}
    except Exception:
        return {}


def _snapshot_terminals() -> dict:
    sessions = _get_sessions()
    terminals = {}
    for slot_num in range(1, 9):
        info = sessions.get(str(slot_num))
        terminals[f'T{slot_num}'] = {
            'running': bool(info),
            'agent': (info or {}).get('agent', ''),
            'yolo': bool((info or {}).get('yolo', False)),
            'started': (info or {}).get('started', ''),
            'cwd': (info or {}).get('cwd', ''),
            'last_line': (info or {}).get('last_line', ''),
        }
    return terminals


def _resolve_target(data) -> str:
    target = data.get('target', data.get('terminal_id', ''))
    if target is None:
        return ''
    target_str = str(target).strip().upper()
    if target_str.startswith('T'):
        target_str = target_str[1:]
    return target_str


def handle_get(handler, path: str, params: dict | None = None) -> None:
    if path in ('/api/pty/terminals', '/api/pty/status'):
        _json_response(handler, _snapshot_terminals())
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

        try:
            since = int((params.get('since') or ['0'])[0] or '0')
        except ValueError:
            since = 0

        try:
            limit = int((params.get('limit') or ['80'])[0] or '80')
        except ValueError:
            limit = 80
        limit = max(1, min(limit, 200))

        entries = list(_get_output_buffers().get(target, []))
        filtered = [entry for entry in entries if int(entry.get('seq', 0)) > since]
        filtered = filtered[:limit]
        latest_seq = int(entries[-1].get('seq', 0)) if entries else 0

        _json_response(handler, {
            'terminal_id': f'T{target}',
            'entries': filtered,
            'latest_seq': latest_seq,
            'running': bool(_get_sessions().get(target)),
        })
        return

    _json_response(handler, {'error': 'not_found', 'path': path}, 404)


def handle_post(handler, path: str) -> None:
    if path not in ('/api/pty/interrupt', '/api/pty/terminate'):
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

    sessions = _get_sessions()
    info = sessions.get(target)
    if not info or not info.get('pty'):
        _json_response(handler, {
            'error': 'not_running',
            'terminal_id': f'T{target}',
        }, 404)
        return

    pty = info['pty']

    if path == '/api/pty/interrupt':
        try:
            pty.write('\x03')
            _json_response(handler, {
                'status': 'interrupted',
                'terminal_id': f'T{target}',
            })
        except Exception as exc:
            _json_response(handler, {'error': 'interrupt_failed', 'detail': str(exc)}, 500)
        return

    try:
        pty.terminate(force=True)
    except Exception as exc:
        _json_response(handler, {'error': 'terminate_failed', 'detail': str(exc)}, 500)
        return

    sessions.pop(target, None)
    _json_response(handler, {
        'status': 'terminated',
        'terminal_id': f'T{target}',
    })
