# -*- coding: utf-8 -*-
"""
# ------------------------------------------------------------------------
# 📄 파일명: api/vibe_api.py
# 📝 설명: cmux 호환 vibe CLI REST API 핸들러.
#          server.py에서 /api/vibe/* 요청을 이 모듈로 위임합니다.
#          vibe_notifications, vibe_agent_state, vibe_agent_logs 테이블을 CRUD합니다.
#
#          [엔드포인트 목록]
#          POST   /api/vibe/notify   → 알림 생성 (vibe_notifications INSERT + pg_notify)
#          POST   /api/vibe/progress → 진행률 설정 (vibe_agent_state UPSERT, key='_progress')
#          DELETE  /api/vibe/progress → 진행률 제거
#          POST   /api/vibe/status   → 사이드바 상태 설정 (vibe_agent_state UPSERT)
#          DELETE  /api/vibe/status   → 사이드바 상태 제거
#          POST   /api/vibe/log      → 로그 추가 (vibe_agent_logs INSERT)
#          DELETE  /api/vibe/log      → 로그 전체 삭제
#          GET    /api/vibe/sidebar  → 에이전트 전체 사이드바 상태 조회
#          GET    /api/vibe/notifications → 알림 목록 조회
#
# REVISION HISTORY:
# [2026-03-18] Claude: 최초 구현 — cmux CLI 미러 API
#   - handle_notify: 알림 생성 + PG NOTIFY 자동 트리거
#   - handle_progress: 진행률 UPSERT/DELETE
#   - handle_status: 사이드바 상태 UPSERT/DELETE
#   - handle_log: 에이전트 로그 INSERT/DELETE
#   - handle_sidebar_state: 전체 상태 조회 (GET)
#   - handle_notifications: 알림 목록 조회 (GET, 최근 50개)
# ------------------------------------------------------------------------
"""

import json
import time


# [중복통합 2026-07-18] _json_response/_read_body는 api/_common.py로 통합 — 패스스루 재노출.
from api._common import json_response as _json_response, read_body as _read_body


def _run_sql(handler, sql, params=None):
    """server.py의 run_pg_sql을 호출합니다.

    [설계 의도] vibe_api는 server.py 모듈의 run_pg_sql / run_pg_sql_csv를
    직접 임포트할 수 없으므로 (순환 의존), handler 객체를 통해
    server 모듈의 전역 함수를 간접 호출합니다.
    """
    # server.py에서 run_pg_sql을 모듈 레벨에서 임포트
    import sys
    from pathlib import Path
    _api_dir = Path(__file__).resolve().parent
    _server_dir = _api_dir.parent
    if str(_server_dir) not in sys.path:
        sys.path.insert(0, str(_server_dir))

    from server import run_pg_sql, run_pg_sql_csv
    return run_pg_sql(sql, params)


def _query_sql(sql, params=None):
    """SELECT 쿼리 실행 후 CSV 결과를 dict 리스트로 반환."""
    import sys
    from pathlib import Path
    _api_dir = Path(__file__).resolve().parent
    _server_dir = _api_dir.parent
    if str(_server_dir) not in sys.path:
        sys.path.insert(0, str(_server_dir))

    from server import run_pg_sql_csv
    return run_pg_sql_csv(sql, params)


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/vibe/notify — 알림 생성
# ═══════════════════════════════════════════════════════════════════════════
def handle_notify(handler):
    """에이전트 알림을 생성합니다. PG 트리거로 vibe_notification 채널에 자동 NOTIFY됩니다.

    요청 본문:
    {
        "agent": "claude",          # 에이전트 이름 (기본: 'unknown')
        "title": "빌드 완료",       # 알림 제목 (필수)
        "body": "테스트 통과",      # 알림 본문 (필수)
        "subtitle": "프로젝트 X",   # 부제목 (선택)
        "source": "cli"             # 소스 (기본: 'cli')
    }
    """
    data = _read_body(handler)
    agent = str(data.get('agent', 'unknown'))
    title = str(data.get('title', ''))
    body = str(data.get('body', ''))
    subtitle = data.get('subtitle')
    source = str(data.get('source', 'cli'))

    if not title or not body:
        _json_response(handler, {'status': 'error', 'message': 'title과 body는 필수입니다'}, 400)
        return

    sql = """
        INSERT INTO vibe_notifications (agent, title, subtitle, body, source)
        VALUES (%s, %s, %s, %s, %s)
    """
    _run_sql(handler, sql, (agent, title, subtitle, body, source))
    _json_response(handler, {'status': 'ok', 'agent': agent, 'title': title})


# ═══════════════════════════════════════════════════════════════════════════
# POST/DELETE /api/vibe/progress — 진행률 설정/제거
# ═══════════════════════════════════════════════════════════════════════════
def handle_progress(handler, method='POST'):
    """에이전트 진행률을 설정하거나 제거합니다.

    POST 요청: {"agent": "claude", "value": 0.75, "label": "Building..."}
    DELETE 요청: {"agent": "claude"}
    """
    data = _read_body(handler)
    agent = str(data.get('agent', 'unknown'))

    if method == 'DELETE':
        _run_sql(handler, "DELETE FROM vibe_agent_state WHERE agent = %s AND key = '_progress'", (agent,))
        _json_response(handler, {'status': 'ok', 'action': 'cleared'})
        return

    value = str(data.get('value', '0'))
    label = data.get('label', '')
    # progress 데이터를 JSON 문자열로 저장
    progress_json = json.dumps({'value': float(value), 'label': label}, ensure_ascii=False)

    sql = """
        INSERT INTO vibe_agent_state (agent, key, value, updated_at)
        VALUES (%s, '_progress', %s, NOW())
        ON CONFLICT (agent, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
    """
    _run_sql(handler, sql, (agent, progress_json))
    _json_response(handler, {'status': 'ok', 'agent': agent, 'progress': float(value)})


# ═══════════════════════════════════════════════════════════════════════════
# POST/DELETE /api/vibe/status — 사이드바 상태 설정/제거
# ═══════════════════════════════════════════════════════════════════════════
def handle_status(handler, method='POST'):
    """에이전트 사이드바 상태 항목을 설정하거나 제거합니다.

    POST 요청: {"agent": "claude", "key": "build", "value": "running", "icon": "hammer", "color": "#2ecc71"}
    DELETE 요청: {"agent": "claude", "key": "build"}
    """
    data = _read_body(handler)
    agent = str(data.get('agent', 'unknown'))
    key = str(data.get('key', ''))

    if not key:
        _json_response(handler, {'status': 'error', 'message': 'key는 필수입니다'}, 400)
        return

    if method == 'DELETE':
        _run_sql(handler, "DELETE FROM vibe_agent_state WHERE agent = %s AND key = %s", (agent, key))
        _json_response(handler, {'status': 'ok', 'action': 'cleared', 'key': key})
        return

    value = str(data.get('value', ''))
    icon = data.get('icon')
    color = data.get('color')

    sql = """
        INSERT INTO vibe_agent_state (agent, key, value, icon, color, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (agent, key) DO UPDATE
            SET value = EXCLUDED.value, icon = EXCLUDED.icon,
                color = EXCLUDED.color, updated_at = NOW()
    """
    _run_sql(handler, sql, (agent, key, value, icon, color))
    _json_response(handler, {'status': 'ok', 'agent': agent, 'key': key, 'value': value})


# ═══════════════════════════════════════════════════════════════════════════
# POST/DELETE /api/vibe/log — 에이전트 로그
# ═══════════════════════════════════════════════════════════════════════════
def handle_log(handler, method='POST'):
    """에이전트 로그를 추가하거나 전체 삭제합니다.

    POST 요청: {"agent": "claude", "message": "Task done", "level": "success", "source": "build"}
    DELETE 요청: {"agent": "claude"} — 해당 에이전트 로그 전체 삭제
    """
    data = _read_body(handler)
    agent = str(data.get('agent', 'unknown'))

    if method == 'DELETE':
        _run_sql(handler, "DELETE FROM vibe_agent_logs WHERE agent = %s", (agent,))
        _json_response(handler, {'status': 'ok', 'action': 'cleared'})
        return

    message = str(data.get('message', ''))
    level = str(data.get('level', 'info'))
    source = data.get('source')

    if not message:
        _json_response(handler, {'status': 'error', 'message': 'message는 필수입니다'}, 400)
        return

    sql = """
        INSERT INTO vibe_agent_logs (agent, message, level, source)
        VALUES (%s, %s, %s, %s)
    """
    _run_sql(handler, sql, (agent, message, level, source))
    _json_response(handler, {'status': 'ok', 'agent': agent, 'level': level})


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/vibe/sidebar — 전체 사이드바 상태 조회
# ═══════════════════════════════════════════════════════════════════════════
def handle_sidebar_state(handler):
    """모든 에이전트의 사이드바 상태를 조회합니다. cmux sidebar-state 미러.

    응답:
    {
        "agents": {
            "claude": {
                "status": {"build": {"value": "running", "icon": "hammer", "color": "#2ecc71"}},
                "progress": {"value": 0.75, "label": "Building..."},
                "recent_logs": [{"message": "...", "level": "info", "created_at": "..."}],
                "unread_notifications": 3
            }
        }
    }
    """
    result: dict = {}

    # 1. 에이전트 상태 조회
    state_rows = _query_sql(
        "SELECT agent, key, value, icon, color FROM vibe_agent_state ORDER BY agent, key"
    )
    for row in state_rows:
        agent = row.get('agent', 'unknown')
        if agent not in result:
            result[agent] = {'status': {}, 'progress': None, 'recent_logs': [], 'unread_notifications': 0}

        key = row.get('key', '')
        if key == '_progress':
            try:
                result[agent]['progress'] = json.loads(row.get('value', '{}'))
            except (json.JSONDecodeError, TypeError):
                result[agent]['progress'] = {'value': 0, 'label': ''}
        else:
            result[agent]['status'][key] = {
                'value': row.get('value', ''),
                'icon': row.get('icon'),
                'color': row.get('color'),
            }

    # 2. 미읽음 알림 수 조회
    notif_rows = _query_sql(
        "SELECT agent, COUNT(*) as cnt FROM vibe_notifications WHERE is_read = FALSE GROUP BY agent"
    )
    for row in notif_rows:
        agent = row.get('agent', 'unknown')
        if agent not in result:
            result[agent] = {'status': {}, 'progress': None, 'recent_logs': [], 'unread_notifications': 0}
        try:
            result[agent]['unread_notifications'] = int(row.get('cnt', 0))
        except (ValueError, TypeError):
            pass

    # 3. 최근 로그 5개 조회 (에이전트별)
    log_rows = _query_sql("""
        SELECT agent, message, level, source, created_at
        FROM vibe_agent_logs
        ORDER BY created_at DESC LIMIT 20
    """)
    for row in log_rows:
        agent = row.get('agent', 'unknown')
        if agent not in result:
            result[agent] = {'status': {}, 'progress': None, 'recent_logs': [], 'unread_notifications': 0}
        if len(result[agent]['recent_logs']) < 5:
            result[agent]['recent_logs'].append({
                'message': row.get('message', ''),
                'level': row.get('level', 'info'),
                'source': row.get('source'),
                'created_at': row.get('created_at', ''),
            })

    _json_response(handler, {'status': 'ok', 'agents': result})


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/vibe/notifications — 알림 목록 조회
# ═══════════════════════════════════════════════════════════════════════════
def handle_notifications(handler):
    """최근 알림 50개를 조회합니다.

    응답: {"notifications": [{"id": 1, "agent": "claude", "title": "...", ...}]}
    """
    rows = _query_sql("""
        SELECT id, agent, title, subtitle, body, source, is_read, created_at
        FROM vibe_notifications
        ORDER BY created_at DESC LIMIT 50
    """)
    _json_response(handler, {'status': 'ok', 'notifications': rows})
