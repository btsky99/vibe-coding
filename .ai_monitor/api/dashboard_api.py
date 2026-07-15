"""
FILE: api/dashboard_api.py
DESCRIPTION: 대시보드/에이전트 라우트 3종 — GET /api/agents(인메모리+PG 병합),
             POST /api/dashboard/launch(dashboard_window.py 네이티브 창 실행),
             POST /api/agents/heartbeat(하트비트 수신 → 인메모리 dict + PG UPSERT).
             인메모리 공유 상태(AGENT_STATUS dict / AGENT_STATUS_LOCK)는 server.py 전역을
             참조 주입받는다 — heartbeat writer와 /api/agents reader가 반드시 동일 객체를 봐야
             상태가 갈리지 않는다(모듈이 사본을 만들면 대시보드가 조용히 빈 값 표시).

REVISION HISTORY:
- 2026-07-16 Claude: [9차 정리] kanban_launch/pg_activity 은퇴 — 소비자였던 오케스트레이션
  보드(TaskBoardPanel)와 server.py 라우트가 은퇴되어 호출자 0. 관제 신규 개발 영구 중단 원칙.
- 2026-07-06 Claude: server.py do_GET/do_POST 인라인 4블록 분리(Phase 2 R5). 공유 dict/lock은
  참조 주입 — heartbeat write와 agents read의 동일 identity 유지가 불변식. DB 헬퍼/launch 헬퍼도
  late-binding 주입(HTTP_PORT는 __main__에서 재설정되므로 호출 시점 값 필요). 로직 원본 verbatim.
- 2026-07-06 Claude: GET '/api/kanban/pg-activity' 인라인 분리(Phase 2 R8). Postgres-first 칸반 —
  run_pg_sql_csv/current_project_id는 wrapper가 호출 시점 주입(PG_PROJECT_DB late-binding 유지).
"""
from __future__ import annotations

import json
import subprocess
import time


def _json_headers(handler) -> None:
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()


def list_agents(handler, agent_status, agent_status_lock, list_agent_status) -> None:
    """GET /api/agents — 인메모리 AGENT_STATUS + PostgreSQL 병합 반환(오케스트레이터용).
    [불변식] agent_status/agent_status_lock은 server.py 전역과 동일 객체여야
      heartbeat가 쓴 최신 상태가 여기서 읽힌다(별도 사본이면 빈 dict).
    """
    _json_headers(handler)
    with agent_status_lock:
        result = dict(agent_status)
    # DB에만 있는 에이전트도 포함 (다른 프로세스가 기록한 경우)
    try:
        for row in list_agent_status():
            aid = row.get('agent_id', '')
            if aid and aid not in result:
                result[aid] = {
                    'status': row.get('status', 'offline'),
                    'task': row.get('current_task'),
                    'last_beat': row.get('last_beat'),
                    'beat_count': row.get('beat_count', 0),
                }
    except Exception:
        pass
    handler.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))


def dashboard_launch(handler, base_dir, http_port, python_runner_cmds) -> None:
    """POST /api/dashboard/launch — dashboard_window.py 네이티브 창 실행(기본 agent 탭).
    [WHY] window.open()이 아닌 PySide6 네이티브 프로세스로 띄워 브라우저 창이 아닌 OS 창을 연다.
    [주의] body 선읽기 금지 위임 규칙 무관 — 이 핸들러가 Content-Length 만큼 직접 소비.
    """
    _json_headers(handler)
    try:
        tab = 'agent'
        content_length = int(handler.headers.get('Content-Length', 0))
        if content_length > 0:
            body = handler.rfile.read(content_length).decode('utf-8')
            payload = json.loads(body or '{}')
            if isinstance(payload, dict):
                tab = str(payload.get('tab', 'agent')).strip().lower() or 'agent'

        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        # Python 스크립트로 대시보드 창 실행
        dashboard_script = base_dir / 'dashboard_window.py'
        python_cmds = python_runner_cmds()
        if not python_cmds:
            raise RuntimeError('Python interpreter not found for dashboard launch')
        subprocess.Popen(
            [python_cmds[0], str(dashboard_script), str(http_port), tab],
            creationflags=_no_window,
            close_fds=True,
        )
        handler.wfile.write(json.dumps({"status": "launched", "tab": tab}).encode('utf-8'))
    except Exception as e:
        handler.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))


def heartbeat(handler, agent_status, agent_status_lock, record_heartbeat, insert_pg_log) -> None:
    """POST /api/agents/heartbeat — 에이전트 실시간 상태 보고 수신 → 인메모리 + PG.
    [불변식] agent_status/agent_status_lock은 server.py 전역과 동일 객체 —
      /api/agents(list_agents)가 같은 dict를 읽어야 하트비트가 반영된다.
    [원본보존] prev 조회가 agent_status[name] 갱신 뒤에 오므로 prev_status는 방금 쓴 값과
      같아져 pg_logs 변경-감지 분기가 사실상 무력. 원본 동작 그대로 — 여기서 고치지 말 것.
    [주의] 지역 상태 문자열은 agent_status_val로 명명 — 주입된 dict 파라미터(agent_status)와
      이름 충돌 회피(원본 로컬명 agent_status를 리네임한 것뿐, 동작 동일).
    """
    _json_headers(handler)
    try:
        content_length = int(handler.headers['Content-Length'])
        data = json.loads(handler.rfile.read(content_length).decode('utf-8'))
        agent_name = data.get('agent')
        if not agent_name:
            handler.wfile.write(json.dumps({"status": "error", "message": "Agent name is required"}).encode('utf-8'))
            return

        agent_status_val = data.get("status", "active")
        agent_task = data.get("task")
        now_ts = time.time()
        with agent_status_lock:
            agent_status[agent_name] = {
                "status": agent_status_val,
                "task": agent_task,
                "last_seen": now_ts,
            }
        # PostgreSQL에도 영구 기록 (재시작 시 복구용)
        try:
            # heartbeat UPSERT는 항상 실행 (상태 갱신)
            record_heartbeat(agent_name, status=agent_status_val,
                             current_task=agent_task)
            # pg_logs는 상태 변경 시에만 기록 (무제한 증가 방지)
            prev = agent_status.get(agent_name, {})
            prev_status = prev.get('status')
            if prev_status != agent_status_val:
                insert_pg_log(
                    agent=agent_name, task=agent_task or '',
                    status=agent_status_val,
                    metadata={'source': 'heartbeat', 'prev': prev_status},
                )
        except Exception:
            pass  # DB 실패해도 인메모리는 유지
        handler.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))
    except Exception as e:
        handler.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
