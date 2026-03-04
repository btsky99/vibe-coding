# -*- coding: utf-8 -*-
"""
# ------------------------------------------------------------------------
# 📄 파일명: api/agent_api.py
# 📝 설명: CLI 오케스트레이터 자율 에이전트 REST API 핸들러.
#          server.py에서 /api/agent/* 요청을 이 모듈로 위임합니다.
#          cli_agent.py의 전역 상태를 통해 Claude Code / Gemini CLI를
#          비대화형 모드로 실행하고 결과를 JSON으로 반환합니다.
#
# 🕒 변경 이력 (REVISION HISTORY):
# [2026-03-04] Claude: 최초 구현
#   - handle_run: POST /api/agent/run — CLI 실행 시작 (백그라운드 스레드)
#   - handle_stop: POST /api/agent/stop — 실행 중인 프로세스 강제 종료
#   - handle_status: GET /api/agent/status — 현재 상태 반환
#   - handle_runs: GET /api/agent/runs — 최근 실행 히스토리 반환
# ------------------------------------------------------------------------
"""

import json
import sys
import threading
from pathlib import Path

# ─── cli_agent 모듈 경로 등록 ─────────────────────────────────────────────────
# api/ 폴더는 .ai_monitor/ 하위, scripts/는 프로젝트 루트 하위
# server.py가 sys.path에 SCRIPTS_DIR을 추가하므로 직접 임포트 가능
# 배포(frozen) 환경 대비 추가 경로 등록
_API_DIR = Path(__file__).resolve().parent
_BASE_DIR = _API_DIR.parent
_SCRIPTS_DIR = _BASE_DIR.parent / 'scripts'
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

try:
    import cli_agent
    _CLI_AGENT_AVAILABLE = True
except ImportError as e:
    _CLI_AGENT_AVAILABLE = False
    _CLI_AGENT_ERROR = str(e)


def _json_response(handler, data: dict | list, status: int = 200) -> None:
    """JSON 응답 공통 헬퍼 — hive_api.py와 동일한 패턴."""
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json;charset=utf-8')
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.end_headers()
    handler.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))


def _read_body(handler) -> dict:
    """POST 요청 본문(JSON)을 파싱하여 반환합니다."""
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        if content_length > 0:
            raw = handler.rfile.read(content_length).decode('utf-8')
            return json.loads(raw)
    except Exception:
        pass
    return {}


def handle_run(handler) -> None:
    """POST /api/agent/run — CLI 자율 실행 시작.

    요청 본문:
        { "task": "지시내용", "cli": "auto|claude|gemini", "cwd": "/path" }

    응답:
        성공: { "status": "started", "cli": "claude", "run_id": "abc12345" }
        오류: { "error": "already_running" | "cli_agent_unavailable" | "empty_task" }
    """
    if not _CLI_AGENT_AVAILABLE:
        _json_response(handler, {'error': 'cli_agent_unavailable',
                                 'detail': _CLI_AGENT_ERROR}, 503)
        return

    data = _read_body(handler)
    task = data.get('task', '').strip()
    cli_choice = data.get('cli', 'auto')
    cwd = data.get('cwd', None)

    # 빈 지시 거부
    if not task:
        _json_response(handler, {'error': 'empty_task'}, 400)
        return

    # 이미 실행 중이면 거부
    current = cli_agent.get_status()
    if current['status'] == 'running':
        _json_response(handler, {'error': 'already_running',
                                 'current': current['current']}, 409)
        return

    # CLI 자동 선택
    if cli_choice == 'auto':
        chosen_cli = cli_agent.route_task(task)
    else:
        chosen_cli = cli_choice

    # 백그라운드 스레드에서 실행 (HTTP 응답을 블로킹하지 않음)
    t = threading.Thread(
        target=cli_agent.run,
        args=(task, cli_choice, cwd),
        daemon=True,
        name=f'cli-agent-{chosen_cli}',
    )
    t.start()

    _json_response(handler, {
        'status': 'started',
        'cli': chosen_cli,
        'run_id': 'pending',  # 실제 run_id는 SSE 이벤트로 전달
        'task': task,
    })


def handle_stop(handler) -> None:
    """POST /api/agent/stop — 실행 중인 CLI 프로세스 강제 종료.

    응답:
        { "status": "stopped" }
    """
    if not _CLI_AGENT_AVAILABLE:
        _json_response(handler, {'error': 'cli_agent_unavailable'}, 503)
        return

    cli_agent.stop()
    _json_response(handler, {'status': 'stopped'})


def handle_status(handler) -> None:
    """GET /api/agent/status — 현재 에이전트 상태 반환.

    응답:
        {
            "status": "idle|running|done|error",
            "current": { "id": "...", "task": "...", "cli": "claude", "ts": "..." } | null
        }
    """
    if not _CLI_AGENT_AVAILABLE:
        _json_response(handler, {
            'status': 'unavailable',
            'error': _CLI_AGENT_ERROR,
        })
        return

    _json_response(handler, cli_agent.get_status())


def handle_runs(handler) -> None:
    """GET /api/agent/runs — 최근 실행 히스토리 반환.

    응답:
        [{ "id": "...", "task": "...", "cli": "claude", "status": "done", "ts": "..." }, ...]
    """
    if not _CLI_AGENT_AVAILABLE:
        _json_response(handler, [])
        return

    runs = cli_agent.get_recent_runs(limit=20)
    _json_response(handler, runs)


def handle_get(handler, path: str) -> bool:
    """GET 요청 라우터 — server.py do_GET에서 호출.

    반환값: 처리했으면 True, 해당 경로 없으면 False.
    """
    if path == '/api/agent/status':
        handle_status(handler)
        return True
    if path == '/api/agent/runs':
        handle_runs(handler)
        return True
    return False


def handle_post(handler, path: str) -> bool:
    """POST 요청 라우터 — server.py do_POST에서 호출.

    반환값: 처리했으면 True, 해당 경로 없으면 False.
    """
    if path == '/api/agent/run':
        handle_run(handler)
        return True
    if path == '/api/agent/stop':
        handle_stop(handler)
        return True
    return False
