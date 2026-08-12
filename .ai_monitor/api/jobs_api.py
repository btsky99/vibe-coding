"""
FILE: api/jobs_api.py
DESCRIPTION: 일감(job) HTTP 라우트 — Phase 12 Task 53.
  GET  /api/jobs          — 목록(결정 대기 + 최근 이력)
  GET  /api/jobs/detail   — 일감 하나 + 전이 이력
  POST /api/jobs          — 발주
  POST /api/jobs/decide   — 승인/반려
  POST /api/jobs/allow-dir — 이 PC 에서 그 폴더의 기동을 허용

[🔴 이 모듈은 '남의 PC 를 움직이는' 라우트가 아니다]
  발주는 중앙 DB 에 줄 하나를 쓰는 것이고, 실제 실행 여부는 **받는 노드의 게이트**가
  정한다. 그래서 여기에 실행 권한이 실리지 않는다 — 권한 판단은 항상 실행하는 쪽에 둔다.
  allow-dir 는 반대로 **이 PC 안에서만** 유효하다(로컬 127.0.0.1 전용).

[제약] 중앙 미설정/서버 다운에서 500 을 내지 않는다. 화면이 통째로 죽는 것보다
  빈 목록이 낫다 — central_api 와 같은 규약.

REVISION HISTORY:
- 2026-08-12 Claude: 최초 작성 — Phase 12 Task 53.
"""
from __future__ import annotations

import json
from urllib.parse import parse_qs


def _json_response(handler, payload: dict, code: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8')
    handler.send_response(code)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_body(handler) -> dict:
    try:
        length = int(handler.headers.get('Content-Length') or 0)
        if length <= 0:
            return {}
        return json.loads(handler.rfile.read(length).decode('utf-8'))
    except Exception:                                          # noqa: BLE001
        return {}


def _q(parsed_path, key: str, default: str = '') -> str:
    try:
        return (parse_qs(parsed_path.query).get(key) or [default])[0]
    except Exception:                                          # noqa: BLE001
        return default


# ── 조회 ─────────────────────────────────────────────────────────────────────


def list_jobs(handler, parsed_path=None) -> None:
    """GET /api/jobs — 결정 대기와 최근 이력을 **나눠서** 돌려준다.

    [WHY 나누나] 화면의 두 층이 성격이 다르다. 위는 '지금 네가 볼 것'(보통 비어 있음),
      아래는 '지나간 것'(항상 남음). 한 배열로 주면 프론트가 다시 갈라야 하고,
      그 분류 규칙이 두 곳에 생겨 어긋난다.
    """
    from src import pg_jobs

    try:
        limit = max(1, min(int(_q(parsed_path, 'limit', '30') or 30), 100))
    except ValueError:
        limit = 30
    _json_response(handler, {
        'decide': pg_jobs.list_jobs('decide', limit),
        'recent': pg_jobs.list_jobs('', limit),
    })


def job_detail(handler, parsed_path=None) -> None:
    """GET /api/jobs/detail?id=N — 일감 + 전이 이력.

    [WHY 이력을 같이 주나] "어디서 뭐가 잘못됐는지"가 이 화면의 존재 이유다(사용자 요구).
      현재 상태만 보면 오늘 na2js 처럼 '정상'으로 보이는 고장을 못 잡는다.
    """
    from src import pg_jobs

    try:
        jid = int(_q(parsed_path, 'id', '0') or 0)
    except ValueError:
        jid = 0
    if jid <= 0:
        _json_response(handler, {'ok': False, 'error': 'id 필요'}, 400)
        return
    _json_response(handler, {'ok': True, 'job': pg_jobs.get_job(jid),
                             'events': pg_jobs.list_events(jid)})


# ── 발주 ─────────────────────────────────────────────────────────────────────


def create(handler, parsed_path=None) -> None:
    """POST /api/jobs — {node_seq|target_node, instruction, project?, slot?, work_dir?}

    [WHY 번호(node_seq)를 받나] 사람과 화면은 '3번 노드'로 말하지 uuid 를 모른다.
      uuid 를 요구하면 발주할 때마다 명부를 손으로 찾아야 한다 — 여기서 변환한다.
    """
    from src import pg_central, pg_jobs
    from src.node_identity import get_node_id

    body = _read_body(handler)
    instruction = str(body.get('instruction') or '').strip()
    if not instruction:
        _json_response(handler, {'ok': False, 'error': 'instruction 필요'}, 400)
        return

    target = str(body.get('target_node') or '').strip()
    if not target:
        try:
            seq = int(body.get('node_seq') or 0)
        except (TypeError, ValueError):
            seq = 0
        for ref in pg_central.list_node_refs():
            if int(ref.get('node_seq') or 0) == seq:
                target = str(ref.get('node_id') or '')
                break
    if not target:
        # [WHY 400 인가] 명부에 없는 번호로 발주하면 아무도 집지 않아 영원히 queued 다.
        #   조용히 쌓이느니 발주 시점에 거절하는 편이 원인이 드러난다.
        _json_response(handler, {'ok': False, 'error': '대상 노드를 명부에서 못 찾음'}, 400)
        return

    jid = pg_jobs.create_job(
        target_node=target, instruction=instruction,
        project=str(body.get('project') or ''),
        target_slot=int(body.get('slot') or 0),
        work_dir=str(body.get('work_dir') or ''),
        origin_node=get_node_id())
    _json_response(handler, {'ok': bool(jid), 'id': jid}, 200 if jid else 500)


def decide(handler, parsed_path=None) -> None:
    """POST /api/jobs/decide — {id, approve, reason?}"""
    from src import pg_jobs

    body = _read_body(handler)
    try:
        jid = int(body.get('id'))
    except (TypeError, ValueError):
        _json_response(handler, {'ok': False, 'error': 'id 필요'}, 400)
        return
    ok = pg_jobs.decide_job(jid, bool(body.get('approve')),
                            str(body.get('reason') or ''))
    _json_response(handler, {'ok': ok})


def allow_dir(handler, parsed_path=None) -> None:
    """POST /api/jobs/allow-dir — {path} 이 PC 에서 그 폴더의 기동을 허용.

    [🔴 왜 API 로 여는가] 설정 파일을 손으로 고치게 했다가 BOM 한 개로 노드를 통째로
      잃은 전례가 있다(2026-08-11). 판단은 사람이 하되 쓰기는 앱이 한다.
    """
    from src import central_inject

    body = _read_body(handler)
    ok, why = central_inject.allow_launch_dir(str(body.get('path') or ''))
    if not ok:
        _json_response(handler, {'ok': False, 'error': why}, 400)
        return
    enabled, dirs = central_inject.launch_gate()
    _json_response(handler, {'ok': True, 'enabled': enabled, 'allow_dirs': dirs})
