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
# [2026-03-05] Claude: 터미널 상태 감지 범위 확장
#   - _merge_live_file_status: idle만 → idle+done 슬롯도 running으로 갱신 허용
#   - handle_terminals 외부 Gemini 매핑: idle만 → idle+done 슬롯도 허용
#   - 이전 작업이 done으로 끝난 터미널에 새 Gemini 실행이 시작돼도 상황판에 표시
# [2026-03-05] Claude: 외부 Gemini 감지 기능 추가
#   - _detect_external_gemini(): ~/.gemini/tmp/*/chats/ 600초 이내 수정 파일 스캔
#   - _merge_live_file_status(): agent_live.jsonl 읽어 터미널별 상태 병합
#   - handle_terminals(): 감지된 외부 Gemini + agent_live.jsonl 상태 오버레이
#   - 대시보드 API 없이 터미널에서 직접 실행된 Gemini도 상황판에 표시
# [2026-03-04] Claude: 레이스 컨디션 수정
#   - _run_gate Lock 추가: 상태 체크 → 스레드 시작 구간을 원자적으로 보호
#   - 동시 요청 시 중복 실행 방지 (동일 태스크 여러 번 실행 버그 수정)
# ------------------------------------------------------------------------
"""

import json
import sys
import threading
import time
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
    terminal_id = data.get('terminal_id', 'T1')  # 요청 터미널 식별자 (기본값: T1, T1~T8만 유효)
    # "2" → "T2" 정규화: 숫자만 오면 T 접두사 자동 추가 (hook_bridge TERMINAL_ID 미설정 케이스)
    if terminal_id and terminal_id.isdigit():
        terminal_id = f'T{terminal_id}'

    # 빈 지시 거부
    if not task:
        _json_response(handler, {'error': 'empty_task'}, 400)
        return

    # cli_agent._status_lock 안에서 체크 → 상태 예약 → 스레드 시작을 원자적으로 수행
    # Lock 해제 전에 _run_status를 'running'으로 설정하므로 다음 요청은
    # Lock 획득 시 이미 'running'을 보게 되어 중복 실행이 완전히 차단됨
    with cli_agent._status_lock:
        # 이미 실행 중이면 거부
        if cli_agent._run_status == 'running':
            _json_response(handler, {'error': 'already_running',
                                     'current': cli_agent._current_run}, 409)
            return

        # CLI 자동 선택
        # 'orchestrate' 요청: vibe-orchestrate 스킬을 Claude에게 지시로 래핑
        # Claude가 /vibe-orchestrate 스킬을 인식하여 자동으로 스킬 체인 수립
        if cli_choice == 'orchestrate':
            task = f'/vibe-orchestrate\n\n{task}'
            chosen_cli = 'claude'
            cli_choice = 'claude'
        elif cli_choice == 'auto':
            chosen_cli = cli_agent.route_task(task)
        else:
            chosen_cli = cli_choice

        # 상태를 'running'으로 선점 (Lock 안에서 설정해야 원자적 보장)
        cli_agent._run_status = 'running'
        cli_agent._current_run = {
            'id': 'pending',
            'task': task,
            'cli': chosen_cli,
            'ts': '',
            'cwd': cwd or '',
            'terminal_id': terminal_id,  # 어느 터미널에서 요청했는지 추적
        }

    # 백그라운드 스레드에서 실행 (Lock 밖에서 시작해야 run() 내부 Lock 획득 가능)
    t = threading.Thread(
        target=cli_agent.run,
        args=(task, cli_choice, cwd, terminal_id),
        daemon=True,
        name=f'cli-agent-{chosen_cli}',
    )
    t.start()

    _json_response(handler, {
        'status': 'started',
        'cli': chosen_cli,
        'run_id': 'pending',  # 실제 run_id는 SSE 이벤트로 전달
        'task': task,
        'terminal_id': terminal_id,
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


def _detect_external_gemini() -> list[dict]:
    """~/.gemini/tmp/ 세션 파일을 스캔하여 외부 실행 중인 Gemini 세션을 감지합니다.

    최근 60초 이내에 수정된 세션 파일이 있으면 해당 프로젝트의 Gemini가
    외부 터미널에서 활성 상태라고 판단합니다.

    반환값: [{ 'project': str, 'session_file': str, 'ts': str }, ...]
    """
    gemini_tmp = Path.home() / '.gemini' / 'tmp'
    if not gemini_tmp.exists():
        return []

    active = []
    now = time.time()
    # 60초 이내 수정된 세션 파일 탐색
    for proj_dir in gemini_tmp.iterdir():
        if not proj_dir.is_dir():
            continue
        chats_dir = proj_dir / 'chats'
        if not chats_dir.exists():
            continue
        for sf in sorted(chats_dir.glob('session-*.json'), reverse=True):
            try:
                mtime = sf.stat().st_mtime
                if now - mtime <= 600:  # 600초(10분) 이내 수정 = 활성 세션
                    active.append({
                        'project': proj_dir.name,
                        'session_file': sf.name,
                        'ts': sf.stat().st_mtime,
                    })
                    break  # 프로젝트당 최신 1개만
            except OSError:
                continue
    return active


def _merge_live_file_status(terminals: dict) -> None:
    """agent_live.jsonl의 최근 이벤트를 읽어 터미널별 상태를 병합합니다.

    agent_shell.py(T1~T8.bat)가 직접 실행한 Gemini/Claude 작업은
    cli_agent._terminals 메모리에 반영되지 않습니다.
    이 함수는 agent_live.jsonl의 최근 이벤트를 분석하여
    각 터미널의 실제 상태(running/done/error)를 덮어씁니다.

    판단 규칙:
    - 터미널별로 가장 최근 started 이벤트를 찾음
    - 그 이후에 done 이벤트가 없으면 running으로 표시
    - 최근 10분(600초) 이내 이벤트만 고려 (오래된 이력 무시)
    """
    import datetime as _dt

    # agent_live.jsonl 경로: .ai_monitor/data/agent_live.jsonl
    _api_dir = Path(__file__).resolve().parent
    live_file = _api_dir.parent / 'data' / 'agent_live.jsonl'
    if not live_file.exists():
        return

    try:
        lines = live_file.read_text(encoding='utf-8').strip().splitlines()
    except Exception:
        return

    now = time.time()
    cutoff = 600  # 10분 이내 이벤트만 처리

    # 터미널별 최근 상태를 추적할 임시 딕셔너리
    # { 'T1': {'last_started': {...}, 'last_done': {...}} }
    terminal_events: dict = {}

    for line in lines[-500:]:  # 마지막 500줄만 처리 (성능 보호)
        try:
            ev = json.loads(line)
        except Exception:
            continue

        # agent_shell.py는 'terminal' 키를, cli_agent.py는 'terminal_id' 키를 사용
        tid = ev.get('terminal') or ev.get('terminal_id', '')
        if not tid or not tid.startswith('T'):
            continue

        ts_str = ev.get('ts', '')
        if not ts_str:
            continue

        # ISO 타임스탬프를 epoch 초로 변환 (시간 범위 필터링용)
        try:
            ts_epoch = _dt.datetime.fromisoformat(ts_str).timestamp()
        except Exception:
            continue

        if now - ts_epoch > cutoff:
            continue  # 10분 이전 이벤트 무시

        if tid not in terminal_events:
            terminal_events[tid] = {'last_started': None, 'last_done': None}

        ev_type = ev.get('type', '')
        if ev_type == 'started':
            terminal_events[tid]['last_started'] = ev
        elif ev_type in ('done', 'stopped', 'error'):
            # done 이벤트는 started 이후에만 유효하도록 ts 비교
            current_done = terminal_events[tid].get('last_done')
            if current_done is None or ts_str > current_done.get('ts', ''):
                terminal_events[tid]['last_done'] = ev

    # 수집한 이벤트로 terminals 딕셔너리 업데이트
    for tid, evs in terminal_events.items():
        started = evs.get('last_started')
        done = evs.get('last_done')

        if started is None:
            continue

        # started가 done보다 나중이면 → 아직 실행 중
        if done is None or started.get('ts', '') > done.get('ts', ''):
            # idle 또는 done 슬롯에 덮어씀 (cli_agent가 running으로 추적 중인 슬롯만 보호)
            # 이전 작업이 done으로 끝난 슬롯도 새 실행이 시작되면 running으로 갱신해야 함
            if tid in terminals and terminals[tid].get('status') != 'running':
                terminals[tid].update({
                    'status': 'running',
                    'task': started.get('task', ''),
                    'cli': started.get('cli', ''),
                    'run_id': started.get('run_id', ''),
                    'ts': started.get('ts', ''),
                    'last_line': '',
                    'pipeline_stage': 'analyzing',  # 외부 실행: 분석 단계부터 시작
                    'external': True,  # agent_live.jsonl 기반 감지 플래그
                })
        else:
            # done 이벤트가 있고 started보다 나중 → 완료 상태
            # pipeline_stage가 없으면 done으로 기본 설정
            if tid in terminals and not terminals[tid].get('pipeline_stage'):
                terminals[tid]['pipeline_stage'] = 'done'


def handle_terminals(handler) -> None:
    """GET /api/agent/terminals — T1~T8 터미널별 에이전트 상태 반환.

    상황판(AgentPanel 상황판 탭)이 3초마다 폴링합니다.
    외부 터미널에서 직접 실행 중인 Gemini도 감지하여 반영합니다.

    응답:
        {
            "T1": { "status": "running", "task": "...", "cli": "claude", "ts": "...", "last_line": "..." },
            "T2": { "status": "idle", ... },
            ...
            "T8": { "status": "done", ... }
        }
    """
    if not _CLI_AGENT_AVAILABLE:
        # cli_agent 미사용 시 8개 터미널 idle 반환
        _json_response(handler, {
            f'T{i}': {'status': 'idle', 'task': '', 'cli': '', 'run_id': '', 'ts': '', 'last_line': ''}
            for i in range(1, 9)
        })
        return

    terminals = cli_agent.get_terminals()

    # ── agent_live.jsonl 기반 터미널 상태 병합 (agent_shell.py 실행 감지) ───────
    # T1.bat ~ T8.bat를 통해 agent_shell.py로 실행한 Gemini/Claude는
    # cli_agent._terminals 메모리에 반영되지 않으므로, 로그 파일에서 읽어 병합합니다.
    _merge_live_file_status(terminals)

    # ── 외부 실행 중인 Gemini 세션 감지 및 오버레이 ──────────────────────────
    # 대시보드 API를 통하지 않고 직접 터미널에서 실행된 Gemini를 감지합니다.
    # 감지된 세션은 이미 idle 상태인 가장 낮은 번호 터미널 슬롯에 매핑합니다.
    external_sessions = _detect_external_gemini()
    if external_sessions:
        import datetime
        for session in external_sessions:
            # idle 또는 done 슬롯 찾기 (T1부터 순서대로)
            # 이전 작업이 done으로 끝난 슬롯도 외부 Gemini 감지로 재사용 가능
            target_slot = None
            for i in range(1, 9):
                slot_key = f'T{i}'
                if terminals[slot_key]['status'] in ('idle', 'done'):
                    target_slot = slot_key
                    break

            if target_slot is None:
                break  # 비어 있는 슬롯 없음

            ts_str = datetime.datetime.fromtimestamp(session['ts']).isoformat()
            terminals[target_slot].update({
                'status': 'running',
                'task': f'[외부] {session["project"]} 프로젝트',
                'cli': 'gemini',
                'run_id': '',
                'ts': ts_str,
                'last_line': f'Gemini CLI 활성 — {session["session_file"]}',
                'external': True,  # 외부 감지 플래그 (UI 구분용)
            })

    _json_response(handler, terminals)


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
    if path == '/api/agent/terminals':
        handle_terminals(handler)
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
