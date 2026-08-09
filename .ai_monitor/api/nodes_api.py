"""
FILE: api/nodes_api.py
DESCRIPTION: 상태판(독립 창 + tui.py)의 데이터 공급 라우트 4종.
  GET  /api/nodes/remote        — ssh config 별칭 + 아픽스 서버 조회(생존/접속) 병합
  GET  /api/nodes/consoles      — 화면에 떠 있는 콘솔 창 목록 + 소속 판정
  POST /api/nodes/console/kill  — 콘솔 창 안전 종료(3중 재검증)
  POST /api/nodes/check-cli     — 원격 노드의 claude/codex 설치 점검(온디맨드)

[WHY ssh 목록을 여기서 다시 파싱하지 않는가 — 중복 금지]
  ~/.ssh/config 파싱은 pty-server의 remote_hosts.js가 단독 소유한다(별칭 화이트리스트가
  원격 spawn의 보안 경계이기도 하다). 파이썬에서 재구현하면 두 목록이 갈리는 순간
  "UI엔 보이는데 실행은 거부되는" 상태가 된다. → pty_api 프록시로 그 목록을 그대로 받아
  서버 조회 결과만 덧붙인다.

[🔴 alive와 reachable을 합치지 말 것]
  alive(하트비트=살아 있나)와 reachable(역터널=조종 가능한가)은 조치가 정반대인 별개
  사실이다. 프론트 편의를 위해 여기서 하나로 뭉개면 원인 진단이 불가능해진다 —
  이유는 infra/node_status.py 헤더 참조. 세 값(true/false/null)을 그대로 내려보낸다.

[제약] check-cli는 SSH 왕복(수 초)이라 폴링 대상이 아니다. 프론트는 사용자가 버튼을
  눌렀을 때만 호출하고 결과를 자기 상태에 캐시한다(node_status 모듈 헤더 참조).

REVISION HISTORY:
- 2026-08-02 Claude: 최초 작성 — 정체불명 콘솔 창 식별 + 원격 노드 상태판.
"""
from __future__ import annotations

import json
import os

from infra import console_scan, node_status


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


def remote(handler) -> None:
    """GET /api/nodes/remote — 원격 노드 카드용 통합 목록.

    [불변식] alias는 remote_hosts.js가 실제로 파싱해낸 값만 내려간다 — 프론트가 이 alias로
      원격 실행을 요청하고, Node 쪽이 같은 화이트리스트로 2차 검증한다.
    """
    _json_headers(handler)
    try:
        from api import pty_api
        hosts_res = pty_api._node_get('/api/pty/remote/hosts') or {}
        hosts = hosts_res.get('hosts') or []
        modes = hosts_res.get('modes') or []
        ssh_available = hosts_res.get('sshAvailable', False)

        probe = node_status.server_probe()
        merged = []
        for h in hosts:
            merged.append({
                **h,
                # 세 값 그대로: True=확인됨 / False=아님 / None=판정 불가
                'alive': node_status.is_alive(probe, h),
                'reachable': node_status.is_reachable(probe, h),
                'heartbeatAge': node_status.heartbeat_age(probe, h),
            })

        _write(handler, {
            'hosts': merged,
            'modes': modes,
            'sshAvailable': ssh_available,
            'server': {
                'available': probe.get('available', False),
                'heartbeatAvailable': probe.get('heartbeat_available', False),
                'error': probe.get('error', ''),
                'staleAfterSec': node_status.STALE_AFTER_SEC,
            },
            'local': node_status.local_summary(),
        })
    except Exception as e:
        _write(handler, {'hosts': [], 'modes': [], 'sshAvailable': False, 'error': str(e)})


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


def check_cli(handler) -> None:
    """POST /api/nodes/check-cli — {alias} 노드에 claude/codex가 있는지 SSH로 1회 확인."""
    body = _read_body(handler)
    _json_headers(handler)
    alias = str(body.get('alias') or '').strip()
    if not alias:
        _write(handler, {'ok': False, 'error': 'alias가 필요해.'})
        return
    # [보안] 임의 문자열로 ssh를 부르지 않는다 — remote_hosts.js가 파싱한 별칭만 허용.
    known: set[str] = set()
    try:
        from api import pty_api
        for h in ((pty_api._node_get('/api/pty/remote/hosts') or {}).get('hosts') or []):
            if h.get('alias'):
                known.add(h['alias'])
            known.update(h.get('aliases') or [])
    except Exception:
        pass
    if alias not in known:
        _write(handler, {'ok': False, 'error': 'ssh config에 없는 별칭이야.'})
        return
    _write(handler, {'alias': alias, **node_status.check_remote_clis(alias)})
