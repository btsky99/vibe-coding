"""
FILE: api/office_launch_api.py
DESCRIPTION: 오피스 독립 서버 실행 라우트 3종 — POST /api/office/launch(office_server 프로세스
             스폰 + dashboard_window.py 오피스 창 실행), POST /api/office/restart(서버 재시작),
             POST /api/office/status(서버 생존/포트/PID 조회). 프록시(_proxy_to_office_server)와는
             역할이 다르다 — 프록시는 실행 중인 오피스 서버로 요청을 중계하고, 이 모듈은 그 서버
             프로세스 자체의 수명(spawn/restart/inspect)을 다룬다. 공유 상태(_office_state)와
             실행 헬퍼(_launch/_restart_office_server, _python_runner_cmds)는 server.py 전역을
             참조 주입받는다 — 프록시 라우트와 반드시 동일한 OfficeServerState 객체를 봐야
             생존 판정/포트가 갈리지 않는다.

REVISION HISTORY:
- 2026-07-06 Claude: server.py do_POST 인라인 3블록 분리(Phase 2 R6). exact 3개만 이전 —
  office 프록시 복합조건(_proxy_to_office_server 공유 헬퍼)과 복합조건 라우트는 server.py 잔류.
  공유 상태/헬퍼는 late-binding 주입(호출 시점 해석). 로직 원본 verbatim.
"""
from __future__ import annotations

import json

from infra import proc  # [표준] 콘솔 숨김 subprocess 래퍼 — 인라인 CREATE_NO_WINDOW 금지


def _json_headers(handler) -> None:
    handler.send_response(200)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()


def launch(handler, office_state, launch_office_server, base_dir, python_runner_cmds) -> None:
    """POST /api/office/launch — office_server.py를 별도 프로세스로 시작 → 포트 확인 →
    dashboard_window.py 오피스 창 실행(오피스 서버 포트 전달).
    [불변식] office_state는 server.py 전역(_office_state)과 동일 객체여야 프록시 라우트가
      같은 생존/포트 상태를 읽는다(별도 사본이면 프록시가 죽은 포트로 중계).
    [주의] 이미 살아있으면 서버 재사용 — office_state.alive and office_state.port 검사.
    """
    _json_headers(handler)
    try:
        # 이미 오피스 서버가 실행 중이면 재사용
        if office_state.alive and office_state.port:
            office_port = office_state.port
        else:
            office_port = launch_office_server()
        # 오피스 대시보드 창 실행 (오피스 서버 포트 전달)
        dashboard_script = base_dir / 'dashboard_window.py'
        python_cmds = python_runner_cmds()
        if not python_cmds:
            raise RuntimeError('Python interpreter not found for office launch')
        proc.popen(
            [python_cmds[0], str(dashboard_script), str(office_port), 'office'],
            close_fds=True,
        )
        handler.wfile.write(json.dumps({
            "status": "launched",
            "office_port": office_port,
        }).encode('utf-8'))
    except Exception as e:
        handler.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))


def restart(handler, restart_office_server) -> None:
    """POST /api/office/restart — 오피스 서버 재시작 후 새 포트 반환."""
    _json_headers(handler)
    try:
        new_port = restart_office_server()
        handler.wfile.write(json.dumps({
            "status": "restarted", "office_port": new_port,
        }).encode('utf-8'))
    except Exception as e:
        handler.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))


def status(handler, office_state) -> None:
    """POST /api/office/status — 오피스 서버 생존/포트/PID 조회.
    [불변식] office_state는 프록시 라우트와 동일 객체여야 일관된 생존 판정.
    """
    _json_headers(handler)
    alive = office_state.alive
    handler.wfile.write(json.dumps({
        "running": alive,
        "port": office_state.port if alive else None,
        "pid": office_state.proc.pid if alive and office_state.proc else None,
    }).encode('utf-8'))
