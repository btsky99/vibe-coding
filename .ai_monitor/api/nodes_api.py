"""
FILE: api/nodes_api.py
DESCRIPTION: 상태판(독립 창 + tui.py)의 콘솔 창 라우트 2종 — 전부 **이 PC 안**의 사실만 다룬다.
  GET  /api/nodes/consoles      — 화면에 떠 있는 콘솔 창 목록 + 소속 판정
  POST /api/nodes/console/kill  — 콘솔 창 안전 종료(3중 재검증)

[제약] consoles는 CIM 스냅샷(~700ms)이라 무겁다 — 상태판은 5초 주기로만 부른다.
  더 잦게 부르면 스캔이 겹쳐 서버 응답 전체가 늘어진다.

REVISION HISTORY:
- 2026-08-02 Claude: 최초 작성 — 정체불명 콘솔 창 식별 + 원격 노드 상태판.
- 2026-08-14 Claude: 아픽스 계층 철거 — remote/check-cli 제거. 원격 노드 조회(node_status)가
  사라져 이 파일은 로컬 콘솔 창 전용이 됐다. 원격 상태가 다시 필요하면 아픽스 리포에 둘 것.
"""
from __future__ import annotations

import json
import os

from infra import console_scan


def _json_headers(handler) -> None:
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()


def _write(handler, payload: dict) -> None:
    handler.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))


def _read_body(handler) -> dict:
    """POST 본문을 dict로 읽는다. 라우트가 직접 소비해야 하므로 여기서 처리."""
    try:
        length = int(handler.headers.get('Content-Length', 0) or 0)
        if length <= 0:
            return {}
        raw = handler.rfile.read(length).decode('utf-8')
        parsed = json.loads(raw or '{}')
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def consoles(handler) -> None:
    """GET /api/nodes/consoles — 화면에 떠 있는 콘솔 창 목록.

    [WHY server_pid를 여기서 넘기는가] console_scan은 '이 서버의 자손'을 owned로 본다.
      멀티 인스턴스(개발본 + 설치본 동시 실행)에서 os.getpid()는 각자 자기 자신이라
      인스턴스마다 owned 판정이 올바르게 갈린다.
    """
    _json_headers(handler)
    try:
        items = console_scan.scan(server_pid=os.getpid())
        _write(handler, {
            'supported': console_scan.IS_WINDOWS,
            'consoles': items,
            'counts': {
                'owned': sum(1 for c in items if c['owner'] == 'owned'),
                'slot': sum(1 for c in items if c['owner'] == 'slot'),
                'foreign': sum(1 for c in items if c['owner'] == 'foreign'),
            },
        })
    except Exception as e:
        _write(handler, {'supported': False, 'consoles': [], 'error': str(e)})


def console_kill(handler) -> None:
    """POST /api/nodes/console/kill — {pid, created, exe} 3중 일치 시에만 트리 종료.

    [🔴 불변식] created/exe를 프론트가 조회 시점 값 그대로 되돌려줘야 한다. 이 값이 빠지면
      console_scan.kill이 mismatch로 거부한다 — PID 재사용 오폭을 막는 유일한 장치라
      "편의상 pid만 받기"로 완화하면 안 된다.
    """
    body = _read_body(handler)
    _json_headers(handler)
    try:
        pid = int(body.get('pid') or 0)
    except (TypeError, ValueError):
        pid = 0
    if not pid:
        _write(handler, {'ok': False, 'reason': 'bad_request', 'message': 'pid가 필요해.'})
        return
    result = console_scan.kill(
        pid=pid,
        created=str(body.get('created') or ''),
        exe=str(body.get('exe') or ''),
    )
    _write(handler, result)
