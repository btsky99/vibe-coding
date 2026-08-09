"""
FILE: api/central_api.py
DESCRIPTION: 중앙 대화(아픽스 서버) HTTP 라우트 5종 — Task 26.
  GET  /api/central/status    — 설정/연결/리스너 상태 + 미수신 개수
  GET  /api/central/messages  — 최근 대화 조회(커서 불변 — 화면용)
  GET  /api/central/poll      — 대기 신호가 있을 때만 수신(커서 전진)
  POST /api/central/send      — 메시지 발신
  POST /api/central/ack       — 커서 수동 확정(advance=false 로 받은 경우)

[🔴 이 모듈에 원격 실행을 절대 넣지 않는다]
  설계 고정 사항이다(ai_monitor_plan.md Task 26). 중앙 서버는 여러 PC가 붙는 공용
  지점이고, 여기에 실행 엔드포인트가 하나라도 생기면 중앙 DB 계정 하나가 모든 노드에
  대한 원격 코드 실행 권한이 된다. 대화는 되돌릴 수 있지만 실행은 되돌릴 수 없다.
  실행이 필요하면 LAN 브리지의 3중 게이트(페어링+토글+승인팝업)를 쓴다.

[제약] 모든 라우트는 중앙 미설정/서버 다운에서 200 + 빈 데이터로 응답한다. 500을 내면
  프론트가 중앙을 안 쓰는 사용자에게도 에러 배지를 띄운다 — '안 쓰는 기능'과 '고장'은
  다른 상태다.

REVISION HISTORY:
- 2026-08-09 Claude: 신규. Task 26 — 대화 전용 라우트.
"""
from __future__ import annotations

from api._common import json_response as _json_response
from api._common import read_body as _read_body

# 한 번에 받아갈 수 있는 최대치. [WHY 상한인가] 오래 꺼져 있던 노드가 켜지면 밀린 메시지가
#   한꺼번에 온다. 상한이 없으면 첫 응답이 수 MB가 되어 WebView가 멈춘다. 남은 것은
#   다음 poll에서 이어 받는다(커서가 id 기준이라 이어받기가 자연스럽다).
_MAX_LIMIT = 200


def _q(parsed_path, key: str, default: str = '') -> str:
    """쿼리스트링 단일 값. [제약] parse_qs는 값이 없으면 키 자체가 없다."""
    from urllib.parse import parse_qs
    try:
        return (parse_qs(parsed_path.query).get(key) or [default])[0]
    except Exception:
        return default


def _limit(parsed_path, default: int = 50) -> int:
    try:
        return max(1, min(_MAX_LIMIT, int(_q(parsed_path, 'limit', str(default)))))
    except (TypeError, ValueError):
        return default


def status(handler, parsed_path=None) -> None:
    """GET /api/central/status — 프론트가 중앙 섹션을 그릴지 판단하는 유일한 근거.

    [불변식] enabled(설정 있음)와 connected(지금 붙음)를 분리해 내려보낸다. 합치면
      '설정 안 함'과 '서버 죽음'이 같은 회색으로 그려져, 진짜 장애가 묻힌다
      (feedback_observability_first).
    """
    from src import pg_central, central_listener
    from src.node_identity import get_node_id

    enabled = pg_central.is_central_enabled()
    payload = {
        'enabled': enabled,
        'connected': False,
        'node_id': '',
        'pending': 0,
        'listener': central_listener.snapshot(),
    }
    if enabled:
        payload['node_id'] = get_node_id()
        payload['connected'] = pg_central.get_central_conn() is not None
        if payload['connected']:
            payload['pending'] = pg_central.pending_count(_q(parsed_path, 'agent') if parsed_path else '')
    _json_response(handler, payload)


def messages(handler, parsed_path=None) -> None:
    """GET /api/central/messages?limit=50 — 화면용 최근 대화. 커서를 밀지 않는다."""
    from src import pg_central
    rows = pg_central.list_recent(limit=_limit(parsed_path))
    _json_response(handler, {'messages': rows, 'count': len(rows)})


def poll(handler, parsed_path=None) -> None:
    """GET /api/central/poll?agent=claude:T1 — 대기 신호가 있을 때만 원격을 조회한다.

    [WHY 신호 없으면 즉시 반환하는가] 프론트는 이 로컬 엔드포인트를 짧은 주기로 두드릴 수
      있어야 한다. 매번 원격 DB까지 가면 터널 왕복 비용이 폴링 주기만큼 곱해져, NOTIFY를
      도입한 이유가 사라진다. 원격 조회는 리스너가 신호를 세운 순간에만 일어난다.
    [제약] fetch가 실패하면 신호를 되돌린다 — 신호를 소비만 하고 못 받아오면 그 메시지는
      다음 NOTIFY까지 잠든다(NOTIFY는 저장되지 않는다).
    """
    from src import pg_central, central_listener

    agent = _q(parsed_path, 'agent') if parsed_path else ''
    force = (_q(parsed_path, 'force') if parsed_path else '') in ('1', 'true')

    if not pg_central.is_central_enabled():
        _json_response(handler, {'messages': [], 'count': 0, 'signalled': False})
        return

    signalled = central_listener.consume_pending()
    if not (signalled or force):
        _json_response(handler, {'messages': [], 'count': 0, 'signalled': False})
        return

    rows = pg_central.fetch_new(agent_id=agent, limit=_limit(parsed_path))
    if not rows and signalled and pg_central.get_central_conn() is None:
        central_listener.raise_pending()     # 조회 자체가 불가능했다 — 신호 보존
    _json_response(handler, {'messages': rows, 'count': len(rows), 'signalled': signalled})


def send(handler, parsed_path=None) -> None:
    """POST /api/central/send — {content, to_node?, to_agent?, from_agent?}

    [제약] to_node를 비우면 브로드캐스트다. 프론트가 실수로 빈 문자열을 보내는 일이 잦아
      기본을 브로드캐스트로 둔 것은 의도적 — 대화가 아무에게도 안 가는 것보다 낫다.
    """
    from src import pg_central

    body = _read_body(handler)
    content = str(body.get('content') or '').strip()
    if not content:
        _json_response(handler, {'ok': False, 'error': 'content 비어 있음'}, 400)
        return

    mid = pg_central.send_message(
        content,
        to_node=str(body.get('to_node') or ''),
        to_agent=str(body.get('to_agent') or ''),
        from_agent=str(body.get('from_agent') or 'claude'),
    )
    if mid is None:
        # 400이 아니다 — 요청은 정상이고 중앙이 없거나 과속 상한에 걸렸을 뿐이다.
        _json_response(handler, {'ok': False, 'id': None,
                                 'error': '중앙 미설정 또는 발신 실패'})
        return
    _json_response(handler, {'ok': True, 'id': mid})


def ack(handler, parsed_path=None) -> None:
    """POST /api/central/ack — {message_id, agent?} 커서 수동 확정."""
    from src import pg_central

    body = _read_body(handler)
    try:
        mid = int(body.get('message_id'))
    except (TypeError, ValueError):
        _json_response(handler, {'ok': False, 'error': 'message_id 필요'}, 400)
        return
    ok = pg_central.ack_upto(mid, agent_id=str(body.get('agent') or ''))
    _json_response(handler, {'ok': ok})
