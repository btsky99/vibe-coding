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
# [2026-03-08] Claude: Gemini 세션 실제 작업 표시 — PTY Gemini 현재 지시 내용 보완
#   - _get_gemini_last_task(): Gemini 세션 JSON에서 마지막 사용자 메시지 추출
#   - server.py pty_sessions에 cwd 필드 추가 → 프로젝트별 세션 파일 정확 매핑
#   - PTY 병합: status 이미 running이어도 task 비어있으면 Gemini 마지막 지시로 보완
#   - PTY last_line: 기존 값 있어도 PTY 최신값으로 항상 갱신 (Gemini 응답 실시간 표시)
# [2026-03-08] Claude: PTY 세션 병합 — handle_terminals()에서 pty_sessions도 반영
#   - _pty_sessions_getter 콜백 추가: server.py가 set_pty_sessions_getter()로 주입
#   - PTY로 실행된 Claude/Gemini/Codex도 T1~T8 카드에 running 상태로 표시
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
# [2026-03-08] Claude: [버그수정] _detect_external_gemini 주석 오류 수정
#   - 주석 "60초 이내" → "600초(10분) 이내"로 수정 (실제 코드와 일치)
# [2026-03-05] Claude: 대화형 세션 파이프라인 실시간 추적 추가
#   - _interactive_stages: hive_hook.py가 업데이트하는 인메모리 stage dict
#   - handle_stage_update: POST /api/agent/stage — hook이 stage를 직접 업데이트
#   - handle_terminals에서 interactive stage를 cli_agent 상태보다 우선 적용
#   - 사용자가 이 대화에서 지시 → 모니터링에 분석/수정/완료 단계 실시간 표시
# ------------------------------------------------------------------------
"""

import json
import sys
import threading
import time
from pathlib import Path

# ─── cli_agent 모듈 경로 등록 ─────────────────────────────────────────────────
# [2026-03-08] Claude: [버그수정] 배포(frozen) EXE에서 cli_agent를 못 찾는 버그 수정
#   - Dev 환경: __file__ = .ai_monitor/api/agent_api.py
#               → _BASE_DIR.parent/scripts = root/scripts ← 정상
#   - EXE 환경: __file__ = MEIPASS/api/agent_api.py
#               → _BASE_DIR.parent/scripts = MEIPASS/../scripts ← 존재 안 함! (버그)
#   - 수정: sys.frozen 여부로 분기 — EXE는 MEIPASS/scripts, Dev는 기존 경로 사용
_API_DIR = Path(__file__).resolve().parent
_BASE_DIR = _API_DIR.parent
if getattr(sys, 'frozen', False):
    # PyInstaller EXE: scripts/는 MEIPASS 루트 직하에 있음
    import sys as _sys
    _SCRIPTS_DIR = Path(getattr(_sys, '_MEIPASS', _BASE_DIR)) / 'scripts'
else:
    # 개발 환경: api/../.. = 프로젝트 루트, 거기서 scripts/
    _SCRIPTS_DIR = _BASE_DIR.parent / 'scripts'
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

try:
    import cli_agent
    _CLI_AGENT_AVAILABLE = True
except ImportError as e:
    _CLI_AGENT_AVAILABLE = False
    _CLI_AGENT_ERROR = str(e)


# ── 대화형 세션 파이프라인 단계 인메모리 저장소 ─────────────────────────────────
# hive_hook.py가 UserPromptSubmit/PreToolUse/Stop 훅에서 POST /api/agent/stage로 업데이트.
# 구조: {terminal_id: {stage, task, ts}}
# handle_terminals()에서 cli_agent 상태를 이 값으로 오버라이드하여 대화형 세션을 실시간 표시.
_interactive_stages: dict = {}

# 모든 사용자 지시는 항상 오케스트레이션으로 시작합니다.
FORCE_ORCHESTRATION = True

# ── PTY 세션 getter (server.py에서 주입) ─────────────────────────────────────
# server.py의 pty_sessions dict를 직접 임포트하면 순환 의존성이 생기므로,
# server.py 초기화 시 set_pty_sessions_getter()로 콜백을 주입받아 사용합니다.
_pty_sessions_getter = None  # callable: () -> dict


def set_pty_sessions_getter(getter) -> None:
    """server.py 초기화 시 호출 — pty_sessions 딕셔너리 접근 콜백을 등록합니다."""
    global _pty_sessions_getter
    _pty_sessions_getter = getter


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


def _wrap_orchestrator_task(task: str) -> str:
    """Ensure the task enters Claude through /vibe-orchestrate exactly once."""
    if task.lstrip().startswith('/vibe-orchestrate'):
        return task
    return f'/vibe-orchestrate\n\n{task}'


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

        # 모든 사용자 지시는 오케스트레이터를 먼저 거치도록 강제합니다.
        if FORCE_ORCHESTRATION or cli_choice == 'orchestrate':
            task = _wrap_orchestrator_task(task)
            chosen_cli = 'claude'
            cli_choice = 'claude'
            _routing_reason = 'forced_orchestration'
        elif cli_choice == 'auto':
            chosen_cli, _routing_reason = cli_agent.route_task_with_reason(task)
        else:
            chosen_cli = cli_choice
            _routing_reason = "사용자 지정"

        # 상태를 'running'으로 선점 (Lock 안에서 설정해야 원자적 보장)
        cli_agent._run_status = 'running'
        cli_agent._current_run = {
            'id': 'pending',
            'task': task,
            'cli': chosen_cli,
            'ts': '',
            'cwd': cwd or '',
            'terminal_id': terminal_id,  # 어느 터미널에서 요청했는지 추적
            'routing_reason': _routing_reason,  # 모델 선택 근거 (UI 표시용)
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
        'orchestrated': FORCE_ORCHESTRATION,
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


def _get_gemini_last_task(session_path) -> str:
    """Gemini 세션 JSON 파일에서 마지막 사용자 메시지 텍스트를 반환합니다.

    세션 파일 구조:
        { "messages": [ {"type": "user", "content": [{"text": "..."}]}, ... ] }

    사용자 메시지(type='user')를 역순 탐색하여 첫 번째 텍스트를 반환합니다.
    읽기 실패 시 빈 문자열 반환.
    """
    try:
        import json as _json
        with open(session_path, 'r', encoding='utf-8') as f:
            data = _json.load(f)
        msgs = data.get('messages', [])
        # 역순으로 탐색하여 가장 최근 사용자 메시지 반환
        for m in reversed(msgs):
            if m.get('type') == 'user':
                content = m.get('content', [])
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict):
                            text = c.get('text', '').strip()
                            if text:
                                # 줄바꿈 제거 후 80자 제한
                                return text.replace('\n', ' ')[:80]
                elif isinstance(content, str) and content.strip():
                    return content.strip().replace('\n', ' ')[:80]
    except Exception:
        pass
    return ''


def _detect_external_gemini() -> list[dict]:
    """~/.gemini/tmp/ 세션 파일을 스캔하여 외부 실행 중인 Gemini 세션을 감지합니다.

    최근 60초 이내에 수정된 세션 파일이 있으면 해당 프로젝트의 Gemini가
    외부 터미널에서 활성 상태라고 판단합니다.

    반환값: [{ 'project': str, 'session_file': str, 'ts': str, 'last_task': str }, ...]
    """
    gemini_tmp = Path.home() / '.gemini' / 'tmp'
    if not gemini_tmp.exists():
        return []

    active = []
    now = time.time()
    # 600초(10분) 이내 수정된 세션 파일 탐색
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
                    # 마지막 사용자 메시지를 task로 함께 반환 (UI에 실제 작업 표시용)
                    last_task = _get_gemini_last_task(sf)
                    active.append({
                        'project': proj_dir.name,
                        'session_file': sf.name,
                        'session_path': str(sf),  # PTY 매핑 시 정확한 task 재조회용
                        'ts': sf.stat().st_mtime,
                        'last_task': last_task,
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
            # cli_agent에 미등록된 터미널(T2, T3 등)도 신규 추가
            # 기존 슬롯이 이미 running이면 cli_agent가 추적 중이므로 덮어쓰지 않음
            if tid not in terminals:
                # agent_live.jsonl에 기록이 있지만 cli_agent에 없는 터미널 — 신규 등록
                terminals[tid] = {
                    'status': 'running',
                    'task': started.get('task', ''),
                    'cli': started.get('cli', ''),
                    'run_id': started.get('run_id', ''),
                    'ts': started.get('ts', ''),
                    'last_line': '',
                    'pipeline_stage': 'analyzing',
                }
            elif terminals[tid].get('status') != 'running':
                terminals[tid].update({
                    'status': 'running',
                    'task': started.get('task', ''),
                    'cli': started.get('cli', ''),
                    'run_id': started.get('run_id', ''),
                    'ts': started.get('ts', ''),
                    'last_line': '',
                    'pipeline_stage': 'analyzing',  # 분석 단계부터 시작
                    # external 플래그 미설정 — 이 터미널은 현재 프로젝트 소속
                    # (external=True는 _detect_external_gemini()에서만 설정:
                    #  다른 프로젝트 Gemini 세션 전용 플래그)
                })
        else:
            # done 이벤트가 있고 started보다 나중 → 완료 상태
            if tid not in terminals:
                # 미등록 터미널의 완료 이벤트도 보드에 표시
                terminals[tid] = {
                    'status': 'done',
                    'task': started.get('task', ''),
                    'cli': started.get('cli', ''),
                    'run_id': started.get('run_id', ''),
                    'ts': done.get('ts', ''),
                    'last_line': '',
                    'pipeline_stage': 'done',
                }
            elif not terminals[tid].get('pipeline_stage'):
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
            # idle 또는 done 슬롯 찾기 (T8부터 T5까지만 역순으로)
            # Why: 외부 세션은 T5~T8에만 배치 — T1~T4는 절대 점유 안 함
            # range(8, 4, -1) = T8, T7, T6, T5 (T1~T4 완전 보호)
            target_slot = None
            for i in range(8, 4, -1):
                slot_key = f'T{i}'
                if terminals[slot_key]['status'] in ('idle', 'done'):
                    target_slot = slot_key
                    break

            if target_slot is None:
                break  # 비어 있는 슬롯 없음

            ts_str = datetime.datetime.fromtimestamp(session['ts']).isoformat()
            # 마지막 사용자 지시가 있으면 그것을 task로, 없으면 프로젝트명 표시
            ext_task = session.get('last_task') or f'[외부] {session["project"]} 프로젝트'
            terminals[target_slot].update({
                'status': 'running',
                'task': ext_task,
                'cli': 'gemini',
                'run_id': '',
                'ts': ts_str,
                'last_line': f'Gemini CLI 활성 — {session["session_file"]}',
                'external': True,  # 외부 감지 플래그 (UI 구분용)
            })

    # ── 대화형 세션 파이프라인 오버라이드 ──────────────────────────────────────────
    # hive_hook.py가 업데이트한 interactive stage가 있으면 cli_agent 상태보다 우선 적용.
    # CLI 에이전트가 없는 대화형 세션(Claude Code)도 표시하기 위해
    # terminals에 없는 tid도 신규 항목으로 추가함.
    # 10분 이내의 stage만 유효 (오래된 데이터는 자동 만료).
    now_ts = time.time()
    for tid, info in _interactive_stages.items():
        if now_ts - info.get('ts', 0) > 600:
            continue  # 10분 이상 지난 stage는 만료

        stage = info['pipeline_stage']
        task = info.get('task', '')

        # terminals에 없으면 대화형 세션 항목으로 신규 추가
        # [버그수정 2026-03-08] agent를 info에서 읽도록 수정 (항상 'claude'로 하드코딩하던 버그 제거)
        # hook_bridge.py가 TERMINAL_ID 환경변수에서 에이전트 타입을 함께 전송하면 정확하게 표시됨
        if tid not in terminals:
            inferred_agent = info.get('cli', 'claude')  # hook이 cli 타입을 보낸 경우 사용
            terminals[tid] = {
                'id': tid,
                'status': 'idle',
                'agent': inferred_agent,
                'cli': inferred_agent,
                'task': '',
                'pipeline_stage': 'idle',
                'interactive': True,  # 대화형 세션 구분 플래그 (Claude Code, Codex 등)
            }

        # analyzing/modifying/verifying 단계: status를 running으로 변경 + stage 업데이트
        if stage in ('analyzing', 'modifying', 'verifying'):
            terminals[tid]['pipeline_stage'] = stage
            terminals[tid]['status'] = 'running'
            if task:
                terminals[tid]['task'] = task
            # [버그수정 2026-03-09] 기존 슬롯(T1~T8)도 cli 타입 업데이트
            # 이전 수정(6f05536)은 신규 슬롯 생성 시에만 cli를 설정했으나,
            # 기존 슬롯은 cli=''인 채로 유지되어 잘못된 배지가 표시되는 문제 수정.
            cli_from_hook = info.get('cli', '')
            if cli_from_hook and not terminals[tid].get('cli'):
                terminals[tid]['cli'] = cli_from_hook
        # done 단계: stage만 업데이트 (status는 기존 유지)
        elif stage == 'done':
            terminals[tid]['pipeline_stage'] = 'done'
            terminals[tid]['status'] = 'idle'
            if task:
                terminals[tid]['task'] = task

    # ── PTY 세션 병합 — TerminalSlot에서 직접 실행한 Claude/Gemini/Codex 반영 ────
    # server.py의 pty_sessions는 슬롯 번호(string "1"~"8")를 키로 사용합니다.
    # cli_agent._terminals이 idle 상태인 슬롯에 한해, PTY에서 에이전트가 실행 중이면
    # status='running'으로 오버라이드하여 상황판 카드가 표시되도록 합니다.
    if _pty_sessions_getter is not None:
        try:
            import datetime as _dt
            pty_sessions = _pty_sessions_getter()
            for slot_num in range(1, 9):
                tid = f'T{slot_num}'
                info = pty_sessions.get(str(slot_num))
                if not info:
                    continue
                agent = info.get('agent', '') or ''
                if not agent:
                    continue
                # PTY 세션이 있고 현재 idle/done 상태이면 running으로 표시
                # (이미 cli_agent가 running으로 표시 중이면 유지)
                if terminals[tid]['status'] not in ('running',):
                    terminals[tid]['status'] = 'running'
                    terminals[tid]['cli'] = agent
                    terminals[tid]['ts'] = info.get('started', '')
                    terminals[tid]['pipeline_stage'] = terminals[tid].get('pipeline_stage') or 'analyzing'

                # 모델 정보 병합 — TerminalSlot UI에서 사용 모델 배지 표시용
                if info.get('main_model'):
                    terminals[tid]['main_model'] = info['main_model']
                if info.get('bg_model'):
                    terminals[tid]['bg_model'] = info['bg_model']

                # ── task 보완: Gemini PTY는 세션 파일에서 마지막 지시 항상 갱신 ──────
                # Why: PTY 세션은 task 필드가 없으므로 task가 ''이면 아무것도 표시 안 됨.
                #      Gemini 세션 JSON에서 마지막 사용자 메시지를 읽어 실제 작업을 표시.
                #      대화가 진행되면서 새 지시가 추가되므로 매 폴링마다 갱신 필요.
                #      단, cli_agent나 hive_hook이 이미 task를 설정한 경우는 유지.
                if agent == 'gemini':
                    # cwd로 프로젝트명 추출 → ~/.gemini/tmp/{project}/chats/ 최신 파일 탐색
                    cwd = info.get('cwd', '')
                    pty_task = ''
                    if cwd:
                        project_name = Path(cwd).name
                        gemini_tmp = Path.home() / '.gemini' / 'tmp' / project_name / 'chats'
                        if gemini_tmp.exists():
                            # 최신 세션 파일 찾기 (수정 시간 기준)
                            session_files = sorted(
                                gemini_tmp.glob('session-*.json'),
                                key=lambda p: p.stat().st_mtime,
                                reverse=True,
                            )
                            for sf in session_files[:1]:  # 최신 1개만 확인
                                pty_task = _get_gemini_last_task(sf)
                                break
                    # 세션에서 읽은 task가 있으면 항상 갱신 (대화 진행 중 최신 지시 반영)
                    # 없으면 기존 task 유지 또는 기본 텍스트 설정
                    if pty_task:
                        terminals[tid]['task'] = pty_task
                    elif not terminals[tid].get('task'):
                        terminals[tid]['task'] = f'[PTY] {agent.upper()} 세션'
                elif not terminals[tid].get('task'):
                    # Claude/Codex PTY: 세션 파일 없으므로 기본 텍스트
                    terminals[tid]['task'] = f'[PTY] {agent.upper()} 세션'

                # ── cli 배지 보완: running이었던 슬롯에 cli 정보 없으면 채움 ─────────
                if not terminals[tid].get('cli'):
                    terminals[tid]['cli'] = agent

                # ── PTY last_line 항상 갱신 — Gemini 응답 출력 실시간 표시 ───────────
                # Why: PTY 세션의 last_line이 가장 최신 출력임.
                #      기존 last_line 값이 있어도 PTY 값으로 덮어씌워야 실시간 갱신됨.
                pty_last = info.get('last_line', '')
                if pty_last:
                    terminals[tid]['last_line'] = pty_last
        except Exception:
            pass  # PTY 세션 병합 실패 시 무시 (서버 미실행 등)

    _json_response(handler, terminals)


def handle_stage_update(handler) -> None:
    """POST /api/agent/stage — 대화형 Claude 세션의 파이프라인 단계 실시간 업데이트.

    hive_hook.py의 훅 이벤트마다 호출되어 모니터링 패널에 현재 작업 단계를 표시합니다.
    - UserPromptSubmit → stage: "analyzing"
    - PreToolUse (Edit/Write) → stage: "modifying"
    - PostToolUse → stage: "verifying"
    - Stop → stage: "done"

    요청 본문:
        {"terminal_id": "T2", "stage": "analyzing", "task": "사용자 메시지"}

    응답:
        {"ok": true}
    """
    data = _read_body(handler)
    tid = data.get('terminal_id', 'T0')
    stage = data.get('stage', 'idle')
    task = data.get('task', '')

    # 터미널 ID 정규화 (숫자 "2" → "T2")
    if tid and tid.isdigit():
        tid = f'T{tid}'

    _interactive_stages[tid] = {
        'pipeline_stage': stage,
        'task': task,
        'ts': time.time(),  # epoch 초 — 10분 이내만 유효
    }
    _json_response(handler, {'ok': True})


def handle_live_runs(handler) -> None:
    """GET /api/agent/live-runs — agent_live.jsonl에서 터미널별 실행 히스토리 반환.

    각 터미널의 최근 실행 기록을 최대 20개씩 반환합니다.
    반환 구조: { "T1": [...runs], "T2": [...runs], ... }
    각 run: { run_id, task, cli, status, ts, output_preview }
    """
    live_file = _api_dir.parent / 'data' / 'agent_live.jsonl'
    result: dict[str, list[dict]] = {}

    if not live_file.exists():
        _json_response(handler, result)
        return

    try:
        # ── agent_live.jsonl 파싱 — run_id 단위로 묶음 ────────────────────────
        # started 이벤트로 run을 열고, done/error 이벤트로 닫습니다.
        # output 이벤트는 미리보기 3줄만 캡처합니다.
        runs_by_id: dict[str, dict] = {}
        order: list[str] = []  # 삽입 순서 유지

        with open(live_file, encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue

                rid = ev.get('run_id')
                if not rid:
                    continue
                etype = ev.get('type', '')

                if etype == 'started':
                    # 이스케이프 시퀀스가 섞인 task 문자열 정리
                    raw_task = ev.get('task', '')
                    # ANSI/VT 이스케이프 + OSC 시퀀스 제거 후 의미 있는 텍스트만 추출
                    import re as _re
                    # 1단계: ESC CSI 시퀀스 제거 (\x1b[31m 등)
                    _s = _re.sub(r'\x1b\[[^a-zA-Z]*[a-zA-Z]', '', raw_task)
                    # 2단계: OSC 시퀀스 제거 (]11;rgb:1e1e/...\) — 다음 OSC/CSI 시작까지 매칭
                    _s = _re.sub(r']\d+;[^"\n]*?(?=]|\[|\Z)', '', _s)
                    # 3단계: 이스케이프 없는 CSI 제거 ([?1;2c, [O, [I 등)
                    _s = _re.sub(r'\[[\?]?[0-9;]*[a-zA-Z]', '', _s)
                    # 4단계: 나머지 제어문자 + 백슬래시(\x5c) 제거
                    _s = _re.sub(r'[\x00-\x1f\x7f\x5c]', '', _s)
                    clean_task = _s.strip(" '\"")
                    # 5단계: 의미 있는 텍스트 판별 (한글 or 5자 이상 영문 단어)
                    # → 3자 이하 영문은 'rgb', 'I', 'O' 같은 노이즈도 포함되므로 5자로 제한
                    has_korean = bool(_re.search(r'[가-힣ㄱ-ㅎㅏ-ㅣ]', clean_task))
                    has_words  = bool(_re.search(r'[a-zA-Z]{5,}', clean_task))
                    if not has_korean and not has_words:
                        continue
                    runs_by_id[rid] = {
                        'run_id': rid,
                        'task': clean_task,
                        'cli': ev.get('cli', ''),
                        'terminal_id': ev.get('terminal_id', ''),
                        'status': 'running',
                        'ts': ev.get('ts', ''),
                        'output': [],
                    }
                    if rid not in order:
                        order.append(rid)

                elif etype in ('done', 'error'):
                    if rid in runs_by_id:
                        runs_by_id[rid]['status'] = ev.get('status', etype)
                        if ev.get('terminal_id'):
                            runs_by_id[rid]['terminal_id'] = ev['terminal_id']

                elif etype == 'output':
                    if rid in runs_by_id and len(runs_by_id[rid]['output']) < 3:
                        text = ev.get('line', '').strip()
                        if text:
                            runs_by_id[rid]['output'].append(text)

        # ── 터미널별로 그룹화 (최근 20개, 역순) ─────────────────────────────
        for rid in reversed(order):
            run = runs_by_id[rid]
            tid = run.get('terminal_id') or 'unknown'
            if not tid or not run.get('task'):
                continue  # task 없는 노이즈 제외

            if tid not in result:
                result[tid] = []
            if len(result[tid]) < 20:
                result[tid].append({
                    'run_id': run['run_id'],
                    'task': run['task'],
                    'cli': run['cli'],
                    'status': run['status'],
                    'ts': run['ts'],
                    'output_preview': run['output'],
                })

    except Exception as exc:
        import traceback
        traceback.print_exc()

    _json_response(handler, result)


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
    if path == '/api/agent/live-runs':
        handle_live_runs(handler)
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
    if path == '/api/agent/stage':
        handle_stage_update(handler)
        return True
    return False
