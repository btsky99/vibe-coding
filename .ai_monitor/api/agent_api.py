# -*- coding: utf-8 -*-
"""
# ------------------------------------------------------------------------
# 📄 파일명: api/agent_api.py
# 📝 설명: CLI 오케스트레이터 자율 에이전트 REST API 핸들러.
#          server.py에서 /api/agent/* 요청을 이 모듈로 위임합니다.
#          cli_agent.py의 전역 상태를 통해 Claude Code / Antigravity CLI를
#          비대화형 모드로 실행하고 결과를 JSON으로 반환합니다.
#
# 🕒 변경 이력 (REVISION HISTORY):
# [2026-07-16] Claude: [로드맵 ③] handle_chat 코덱스 회상 주입 — codex는 훅이 없어
#   중계 시점 접두 주입이 상한선. claude/antigravity는 자체 훅 주입이라 제외(이중 주입 금지).
# [2026-07-15] Claude: handle_run에 project_id 꼬리표 — 크로스 프로젝트 간섭 수정.
#   _current_run.project_id로 훅이 "다른 프로젝트 실행 중"을 판별, 로그 메타에도 기록.
# [2026-03-25] Claude: stderr 데드락 수정 — handle_chat() subprocess stderr=DEVNULL
#   - stderr 버퍼 풀 → 자식 프로세스 block → stdout 멈춤 교착 방지
# [2026-03-08] Claude: Gemini 세션 실제 작업 표시 — PTY Gemini 현재 지시 내용 보완
#   - (제거 2026-06-11) _get_gemini_last_task — agy 대화는 비공개 포맷이라 파싱 불가
#   - server.py pty_sessions에 cwd 필드 추가 → 프로젝트별 세션 파일 정확 매핑
#   - PTY 병합: status 이미 running이어도 task 비어있으면 Antigravity 마지막 지시로 보완
#   - PTY last_line: 기존 값 있어도 PTY 최신값으로 항상 갱신 (Antigravity 응답 실시간 표시)
# [2026-03-08] Claude: PTY 세션 병합 — handle_terminals()에서 pty_sessions도 반영
#   - _pty_sessions_getter 콜백 추가: server.py가 set_pty_sessions_getter()로 주입
#   - PTY로 실행된 Claude/Antigravity/Codex도 T1~T8 카드에 running 상태로 표시
# [2026-03-04] Claude: 최초 구현
#   - handle_run: POST /api/agent/run — CLI 실행 시작 (백그라운드 스레드)
#   - handle_stop: POST /api/agent/stop — 실행 중인 프로세스 강제 종료
#   - handle_status: GET /api/agent/status — 현재 상태 반환
#   - handle_runs: GET /api/agent/runs — 최근 실행 히스토리 반환
# [2026-03-05] Claude: 터미널 상태 감지 범위 확장
#   - _merge_live_file_status: idle만 → idle+done 슬롯도 running으로 갱신 허용
#   - handle_terminals 외부 Antigravity 매핑: idle만 → idle+done 슬롯도 허용
#   - 이전 작업이 done으로 끝난 터미널에 새 Antigravity 실행이 시작돼도 상황판에 표시
# [2026-03-05] Claude: 외부 Gemini 감지 기능 추가
#   - _detect_external_gemini(): agy conversations/ mtime 스캔 (antigravity_adapter 경유)
#   - _merge_live_file_status(): agent_live.jsonl 읽어 터미널별 상태 병합
#   - handle_terminals(): 감지된 외부 Antigravity + agent_live.jsonl 상태 오버레이
#   - 대시보드 API 없이 터미널에서 직접 실행된 Antigravity도 상황판에 표시
# [2026-03-04] Claude: 레이스 컨디션 수정
#   - _run_gate Lock 추가: 상태 체크 → 스레드 시작 구간을 원자적으로 보호
#   - 동시 요청 시 중복 실행 방지 (동일 태스크 여러 번 실행 버그 수정)
# [2026-03-08] Claude: [버그수정] _detect_external_gemini 주석 오류 수정
#   - 주석 "60초 이내" → "600초(10분) 이내"로 수정 (실제 코드와 일치)
# [2026-05-02] Codex: PTY 슬롯 heartbeat 엔드포인트 추가
#   - node-pty 세션을 claude:T1/antigravity:T2/codex:T3 단위로 agent_heartbeats에 기록
#   - 사용자가 PTY에 입력한 지시와 최신 출력 줄을 config에 저장하여 하이브 상태 복구 보완
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
# [2026-04-10] Claude: frozen 모드 분기 실제 구현 (기존 주석만 있고 코드가 없었음)
#   - Dev:    _SCRIPTS_DIR = .ai_monitor/../../scripts = 프로젝트 루트/scripts ✓
#   - Frozen: _SCRIPTS_DIR = MEIPASS/scripts ✓ (spec datas에 포함됨)
if getattr(sys, 'frozen', False):
    _SCRIPTS_DIR = Path(sys._MEIPASS) / 'scripts'
else:
    _SCRIPTS_DIR = _BASE_DIR.parent / 'scripts'
# [2026-03-24] 배포 범용화: scripts 폴더가 없으면 sys.path 추가 skip
if _SCRIPTS_DIR.exists() and str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

try:
    import cli_agent
    _CLI_AGENT_AVAILABLE = True
except ImportError as e:
    _CLI_AGENT_AVAILABLE = False
    _CLI_AGENT_ERROR = str(e)

# pg_store 활동 로깅 — 에이전트 시작/중지를 pg_logs에 영구 기록
try:
    from src.pg_store import insert_pg_log, record_heartbeat, list_agent_status
    _PG_LOG_AVAILABLE = True
except ImportError:
    _PG_LOG_AVAILABLE = False


# ── 대화형 세션 파이프라인 단계 인메모리 저장소 ─────────────────────────────────
# hive_hook.py가 UserPromptSubmit/PreToolUse/Stop 훅에서 POST /api/agent/stage로 업데이트.
# 구조: {terminal_id: {stage, task, ts}}
# handle_terminals()에서 cli_agent 상태를 이 값으로 오버라이드하여 대화형 세션을 실시간 표시.
_interactive_stages: dict = {}

# 모든 사용자 지시는 항상 오케스트레이션으로 시작합니다.
FORCE_ORCHESTRATION = True

# ── 채팅 모드 세션 관리 (cokacdir 패턴) ─────────────────────────────────────
# 터미널별 채팅 세션: session_id, 진행 중 프로세스, 대화 히스토리
# 구조: { "T1": { "session_id": "abc...", "proc": subprocess|None, "history": [...], "cli": "claude" } }
import subprocess as _sp
import asyncio as _asyncio
from infra import proc as _proc  # [표준] 콘솔 숨김 subprocess 래퍼 — 인라인 CREATE_NO_WINDOW 금지

_chat_sessions: dict = {}
_chat_sessions_lock = threading.Lock()

# ── 채팅 메시지 버스 (대시보드 ↔ 텔레그램 양방향 동기화) ──────────────────────
# 터미널별 메시지 배열 + 시퀀스 카운터. 양쪽 클라이언트가 since 파라미터로 폴링.
# 구조: { "T1": [ {seq, source, role, content, ts, tg_user?}, ... ] }
_chat_bus: dict = {}
_chat_bus_seq: dict = {}       # 터미널별 다음 시퀀스 번호
_chat_bus_lock = threading.Lock()
_CHAT_BUS_MAX = 200            # 터미널당 메시지 상한

def _bus_append(terminal_id: str, source: str, role: str, content: str, tg_user: str = None) -> int:
    """메시지 버스에 메시지 추가. 200개 초과 시 오래된 것 삭제. seq 반환.

    Args:
        terminal_id: "T1"~"T8"
        source: "dashboard" | "telegram" — 메시지 발신 채널
        role: "user" | "assistant" | "tool" — 발화자 역할
        content: 메시지 본문
        tg_user: 텔레그램 사용자 이름 (source=="telegram"일 때)
    Returns:
        할당된 시퀀스 번호
    """
    with _chat_bus_lock:
        if terminal_id not in _chat_bus:
            _chat_bus[terminal_id] = []
            _chat_bus_seq[terminal_id] = 1
        seq = _chat_bus_seq[terminal_id]
        _chat_bus_seq[terminal_id] = seq + 1
        msg = {
            'seq': seq,
            'source': source,
            'role': role,
            'content': content,
            'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }
        if tg_user:
            msg['tg_user'] = tg_user
        _chat_bus[terminal_id].append(msg)
        # 상한 초과 시 앞에서 삭제
        if len(_chat_bus[terminal_id]) > _CHAT_BUS_MAX:
            _chat_bus[terminal_id] = _chat_bus[terminal_id][-_CHAT_BUS_MAX:]
        return seq

# ── PTY 세션 조회 (Node PTY 서버 REST API) ─────────────────────────────────────
# [변경 2026-03-22] Python pywinpty 직접 접근 → Node PTY 서버 REST 프록시로 전환.
# server.py 초기화 시 set_pty_rest_url()로 Node PTY 서버 URL을 주입받습니다.
import urllib.request
import urllib.error

_node_pty_url = None  # Node PTY 서버 REST URL (예: http://127.0.0.1:9001)


def set_pty_rest_url(url: str) -> None:
    """Node PTY 서버의 REST 기본 URL을 설정합니다."""
    global _node_pty_url
    _node_pty_url = url


def set_pty_sessions_getter(getter) -> None:
    """[Deprecated] 하위 호환용 — Node PTY 전환으로 사용하지 않음."""
    pass


def _get_pty_sessions_from_node() -> dict:
    """Node PTY 서버에서 세션 스냅샷을 REST로 조회합니다.
    반환 형식: {'T1': {running, agent, ...}, 'T2': {...}, ...}
    """
    if not _node_pty_url:
        return {}
    try:
        req = urllib.request.Request(f"{_node_pty_url}/api/pty/sessions")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return {}


# [중복통합 2026-07-18] _json_response/_read_body는 api/_common.py로 통합 — 패스스루 재노출.
from api._common import json_response as _json_response, read_body as _read_body


def _wrap_orchestrator_task(task: str) -> str:
    """Ensure the task enters Claude through /vibe-orchestrate exactly once."""
    if task.lstrip().startswith('/vibe-orchestrate'):
        return task
    return f'/vibe-orchestrate\n\n{task}'


def handle_run(handler) -> None:
    """POST /api/agent/run — CLI 자율 실행 시작.

    요청 본문:
        { "task": "지시내용", "cli": "auto|claude|antigravity", "cwd": "/path" }

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
    source = data.get('source', 'dashboard')  # 요청 출처: "dashboard" | "telegram" | "hook"
    # [2026-07-15] 프로젝트 꼬리표 — hook_bridge가 전달. 없고 cwd만 있으면 슬러그 파생.
    # 이게 없으면 다른 프로젝트발 지시가 실행/로그 양쪽에서 이 서버 프로젝트로 오인됨.
    project_id = (data.get('project_id') or '').strip()
    if not project_id and cwd:
        try:
            from infra.project_context import slugify
            project_id = slugify(Path(cwd))
        except Exception:
            project_id = ''
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
        # 텔레그램 요청(source=telegram)은 오케스트레이션 우회 — 직접 에이전트 실행
        if (FORCE_ORCHESTRATION or cli_choice == 'orchestrate') and source != 'telegram':
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
            'project_id': project_id,  # 어느 프로젝트발 지시인지 — 409 응답에서 훅이 경계 판정에 사용
            'routing_reason': _routing_reason,  # 모델 선택 근거 (UI 표시용)
            'source': source,  # 요청 출처 (telegram/dashboard/hook)
        }

    # 백그라운드 스레드에서 실행 (Lock 밖에서 시작해야 run() 내부 Lock 획득 가능)
    t = threading.Thread(
        target=cli_agent.run,
        args=(task, cli_choice, cwd, terminal_id),
        daemon=True,
        name=f'cli-agent-{chosen_cli}',
    )
    t.start()

    # PostgreSQL에 에이전트 시작 기록 (영구 로그 + heartbeat)
    if _PG_LOG_AVAILABLE:
        try:
            record_heartbeat(chosen_cli, status='running', current_task=task[:200])
            insert_pg_log(agent=chosen_cli, task=task[:200], status='started',
                          terminal_id=terminal_id,
                          metadata={'source': source, 'routing': _routing_reason,
                                    'project_id': project_id})
        except Exception:
            pass

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

    # 중지 전 현재 실행 중인 CLI 이름 캡처 (로그 기록용)
    stopped_cli = 'unknown'
    try:
        current = cli_agent._current_run
        if current and current.get('cli'):
            stopped_cli = current['cli']
    except Exception:
        pass
    cli_agent.stop()
    # PostgreSQL에 에이전트 중지 기록
    if _PG_LOG_AVAILABLE:
        try:
            record_heartbeat(stopped_cli, status='idle')
            insert_pg_log(agent=stopped_cli, task='', status='stopped',
                          metadata={'source': 'manual_stop'})
        except Exception:
            pass
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


def _detect_external_antigravity() -> list[dict]:
    """외부 실행 중인 Antigravity(agy) 세션을 감지합니다.

    [2026-06-11] agy 전환: 구 Gemini CLI의 ~/.gemini/tmp/{project}/chats/ 는 폐기.
    agy는 ~/.gemini/antigravity-cli/conversations/*.db|.pb (UUID 평면 구조)라
    프로젝트 단위 매칭 불가 — 전역 활성 여부만 반환한다 (어댑터 실측 주석 참조).

    반환값: [{ 'project': str, 'session_file': str, 'ts': float, 'last_task': str }, ...]
    """
    try:
        from antigravity_adapter import detect_external_sessions
        sessions = detect_external_sessions(within_sec=600)
    except Exception:
        return []
    now = time.time()
    return [{
        'project': '',  # agy 대화는 프로젝트 메타 미노출 — UI는 빈 값 허용
        'session_file': Path(s['path']).name,
        'session_path': s['path'],
        'ts': now - s['mtime_age_sec'],
        'last_task': '',  # 대화 내용은 sqlite/pb 포맷 — 파싱 비지원 (포맷 비공개)
    } for s in sessions[:1]]  # 최신 1건만 (구버전과 동일 정책)


def _merge_live_file_status(terminals: dict) -> None:
    """agent_live.jsonl의 최근 이벤트를 읽어 터미널별 상태를 병합합니다.

    agent_shell.py(T1~T8.bat)가 직접 실행한 Antigravity/Claude 작업은
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
                    # (external=True는 _detect_external_antigravity()에서만 설정:
                    #  다른 프로젝트 Antigravity 세션 전용 플래그)
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


def _merge_pty_heartbeats(terminals: dict) -> None:
    """agent_heartbeats(namespace='pty')의 슬롯별 현재 작업을 터미널 카드에 병합."""
    if not _PG_LOG_AVAILABLE:
        return
    try:
        rows = list_agent_status()
    except Exception:
        return

    now = time.time()
    for row in rows:
        if row.get('config') is None:
            continue
        if ':T' not in str(row.get('agent_id', '')):
            continue
        try:
            cfg = json.loads(row.get('config') or '{}')
        except Exception:
            cfg = {}
        if cfg.get('source') != 'pty':
            continue

        tid = str(cfg.get('terminal_id') or '').upper()
        if not tid.startswith('T'):
            continue

        last_beat = str(row.get('last_beat') or '')
        try:
            beat_ts = time.mktime(time.strptime(last_beat[:19], '%Y-%m-%dT%H:%M:%S'))
            is_fresh = now - beat_ts <= 45
        except Exception:
            is_fresh = True

        status = row.get('status') or 'running'
        if status == 'running' and not is_fresh:
            status = 'idle'

        if tid not in terminals:
            terminals[tid] = {
                'status': status,
                'task': '',
                'cli': cfg.get('agent', ''),
                'run_id': '',
                'ts': last_beat,
                'last_line': '',
                'pipeline_stage': 'idle',
            }

        task = row.get('current_task') or ''
        if task:
            terminals[tid]['task'] = task
        if cfg.get('agent') and not terminals[tid].get('cli'):
            terminals[tid]['cli'] = cfg.get('agent')
        if cfg.get('last_line'):
            terminals[tid]['last_line'] = cfg.get('last_line')
        terminals[tid]['heartbeat_agent_id'] = row.get('agent_id')
        terminals[tid]['heartbeat_ts'] = last_beat
        if status == 'running':
            terminals[tid]['status'] = 'running'
            terminals[tid]['pipeline_stage'] = terminals[tid].get('pipeline_stage') or 'analyzing'


def handle_terminals(handler) -> None:
    """GET /api/agent/terminals — T1~T8 터미널별 에이전트 상태 반환.

    상황판(AgentPanel 상황판 탭)이 3초마다 폴링합니다.
    외부 터미널에서 직접 실행 중인 Antigravity도 감지하여 반영합니다.

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
    # T1.bat ~ T8.bat를 통해 agent_shell.py로 실행한 Antigravity/Claude는
    # cli_agent._terminals 메모리에 반영되지 않으므로, 로그 파일에서 읽어 병합합니다.
    _merge_live_file_status(terminals)
    _merge_pty_heartbeats(terminals)

    # ── 외부 실행 중인 Antigravity 세션 감지 및 오버레이 ──────────────────────────
    # 대시보드 API를 통하지 않고 직접 터미널에서 실행된 Antigravity를 감지합니다.
    # 감지된 세션은 이미 idle 상태인 가장 낮은 번호 터미널 슬롯에 매핑합니다.
    external_sessions = _detect_external_antigravity()
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
                'cli': 'antigravity',
                'run_id': '',
                'ts': ts_str,
                'last_line': f'Antigravity CLI 활성 — {session["session_file"]}',
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

    # ── PTY 세션 병합 — TerminalSlot에서 직접 실행한 Claude/Antigravity/Codex 반영 ────
    # [변경 2026-03-22] Node PTY 서버의 REST API에서 세션 스냅샷을 조회합니다.
    # cli_agent._terminals이 idle 상태인 슬롯에 한해, PTY에서 에이전트가 실행 중이면
    # status='running'으로 오버라이드하여 상황판 카드가 표시되도록 합니다.
    _pty_snap = _get_pty_sessions_from_node()
    if _pty_snap:
        try:
            import datetime as _dt
            for slot_num in range(1, 9):
                tid = f'T{slot_num}'
                info = _pty_snap.get(tid)
                if not info or not info.get('running'):
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

                # [2026-06-11] agy 전환: 구 Gemini CLI의 ~/.gemini/tmp/{project}/chats/
                # 마지막 지시 추출 경로 제거 — agy 대화는 비공개 sqlite/pb 포맷이라 파싱 불가.
                # 모든 PTY 에이전트가 동일하게 기본 텍스트 사용 (task는 hive_hook이 설정 시 유지).
                if not terminals[tid].get('task'):
                    terminals[tid]['task'] = f'[PTY] {agent.upper()} 세션'

                # ── cli 배지 보완: running이었던 슬롯에 cli 정보 없으면 채움 ─────────
                if not terminals[tid].get('cli'):
                    terminals[tid]['cli'] = agent

                # ── PTY last_line 항상 갱신 — Antigravity 응답 출력 실시간 표시 ───────────
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
    - UserPromptSubmit → stage: "analyzing" (지시 수신)
    - PreToolUse (Read/Glob/Grep/Search/Agent) → stage: "analyzing" (파일 분석)
    - PreToolUse (Edit/Write) → stage: "modifying" (코드 수정)
    - PreToolUse (Bash) → stage: "verifying" (명령 실행/테스트/빌드)
    - Stop → stage: "done" (응답 완료)

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


def handle_heartbeat(handler) -> None:
    """POST /api/agent/heartbeat — PTY/외부 런타임의 슬롯별 하트비트 기록.

    PTY 서버는 Python 프로세스 내부 상태를 직접 만질 수 없으므로 이 엔드포인트를 통해
    pg_store.record_heartbeat()를 재사용한다. agent_id는 claude:T1처럼 슬롯까지 포함해야
    같은 CLI가 여러 터미널에서 실행될 때 current_task가 서로 덮이지 않는다.
    """
    if not _PG_LOG_AVAILABLE:
        _json_response(handler, {'ok': False, 'error': 'pg_store_unavailable'}, 503)
        return

    data = _read_body(handler)
    agent = str(data.get('agent') or '').strip().lower()
    terminal_id = str(data.get('terminal_id') or '').strip().upper()
    agent_id = str(data.get('agent_id') or '').strip()
    status = str(data.get('status') or 'running').strip().lower()
    current_task = str(data.get('current_task') or '').strip()
    project_id = str(data.get('project_id') or '').strip()
    cwd = str(data.get('cwd') or '').strip()
    last_line = str(data.get('last_line') or '').strip()

    if terminal_id and terminal_id.isdigit():
        terminal_id = f'T{terminal_id}'
    if not agent_id and agent and terminal_id:
        agent_id = f'{agent}:{terminal_id}'
    if not agent_id:
        _json_response(handler, {'ok': False, 'error': 'missing_agent_id'}, 400)
        return

    if status not in ('idle', 'running', 'done', 'error', 'offline'):
        status = 'running'

    config = {
        'agent': agent,
        'terminal_id': terminal_id,
        'project_id': project_id,
        'cwd': cwd,
        'last_line': last_line[:200],
        'source': 'pty',
    }
    ok = record_heartbeat(
        agent_id,
        status=status,
        current_task=current_task[:300] if current_task else None,
        namespace='pty',
        config=config,
    )
    _json_response(handler, {'ok': bool(ok), 'agent_id': agent_id})


def handle_live_runs(handler) -> None:
    """GET /api/agent/live-runs — agent_live.jsonl에서 터미널별 실행 히스토리 반환.

    각 터미널의 최근 실행 기록을 최대 20개씩 반환합니다.
    반환 구조: { "T1": [...runs], "T2": [...runs], ... }
    각 run: { run_id, task, cli, status, ts, output_preview }
    """
    _api_dir = Path(__file__).resolve().parent
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


# ═══════════════════════════════════════════════════════════════════════════════
#  채팅 모드 API (cokacdir 패턴 — CLI spawn + SSE 스트리밍)
# ═══════════════════════════════════════════════════════════════════════════════

# 프로젝트 루트 경로 (CLI spawn의 cwd로 사용)
# frozen 모드에서는 exe 옆 디렉터리(설치 경로)를 프로젝트 루트로 사용
if getattr(sys, 'frozen', False):
    _project_root = str(Path(sys.executable).resolve().parent)
else:
    _project_root = str(_BASE_DIR.parent)


def _build_chat_cmd(cli: str, session_id: str | None, yolo: bool = False, message: str = '') -> list[str]:
    """에이전트별 CLI 명령 구성 (cokacdir 패턴).

    [에이전트별 명령]
    - claude: claude --verbose --output-format stream-json [--resume SID] [--dangerously-skip-permissions] -p "메시지"
      → -p는 프롬프트 텍스트를 인자로 받으므로 반드시 -p message 순서로 배치.
        stdin=DEVNULL 사용 (stdin 파이프 불필요).
    - gemini: gemini -m gemini-3.1-pro [--resume SID] [-y]
    - codex:  codex --full-auto [--resume SID]

    Args:
        cli: 에이전트 종류 ("claude" | "antigravity" | "codex")
        session_id: 기존 세션 ID (--resume용, None이면 새 세션)
        yolo: YOLO 모드 (권한 자동 승인)
        message: 전달할 메시지 (claude -p 인자로 직접 전달)
    """
    if cli == 'claude':
        # -p는 프롬프트 텍스트를 인자로 받으므로 다른 플래그를 먼저 배치하고
        # -p message를 마지막에 추가해야 함.
        # 잘못된 순서: claude -p --verbose ... message → -p가 --verbose를 프롬프트로 해석
        # 올바른 순서: claude --verbose ... -p message → -p가 실제 메시지를 받음
        cmd = ['claude', '--verbose', '--output-format', 'stream-json']
        if session_id:
            cmd += ['--resume', session_id]
        if yolo:
            cmd.append('--dangerously-skip-permissions')
        # -p 플래그와 메시지를 연속 배치 (-p는 프롬프트를 인자로 받음)
        if message:
            cmd += ['-p', message]
    elif cli == 'antigravity':
        # [2026-06-11] Antigravity(agy) 전환 — 'gemini-3.1-pro' 모델 지정 제거 (6/18 종료로
        # 존재하지 않는 모델, agy 기본 모델 사용). --resume → --conversation, -y → 권한 스킵.
        # [제약] agy TUI는 파이프 stdin 채팅을 보장하지 않음 (실측: -p 파이프 캡처 결함과 동일 계열)
        from antigravity_adapter import find_agy
        cmd = [find_agy()]
        if session_id:
            cmd += ['--conversation', session_id]
        if yolo:
            cmd.append('--dangerously-skip-permissions')
    elif cli == 'codex':
        cmd = ['codex', '--full-auto']
        if session_id:
            cmd += ['--resume', session_id]
    else:
        cmd = [cli]
    return cmd


def _codex_recall_prefix(message: str, server_port: int) -> str:
    """코덱스 중계분에 접두할 회상 v2 요약 — 실패/무관련이면 '' (주입 생략).

    [WHY] 코덱스는 훅 시스템이 없어 자동 회상 주입이 구조적으로 불가 —
      대시보드/오피스 공용 중계 지점(handle_chat)이 유일한 주입 통로 (로드맵 ③).
      hive_hook(claude)·antigravity_hook(BeforeAgent)과 같은 recall_client 경로를
      재사용해 3에이전트 회상이 한 곳(recall-smart)으로 수렴한다.
    [제약] 서버 자신은 VIBE_SERVER_PORT env 미보유(daemons.py:115는 자식에게만 주입)
      → 자기 바인드 포트를 setdefault해 recall_client의 포트 스캔(최악 0.3초×20) 생략.
    [불변식] 어떤 실패도 채팅 중계를 중단시키지 않는다 — 전부 삼키고 '' 반환.
      recall_client 자체도 2초 상한 + 3단 폴백 내장 (hive_hook과 동일 계약).
    """
    try:
        import os
        os.environ.setdefault('VIBE_SERVER_PORT', str(server_port))
        from src.recall_client import smart_recall_summary
        short = message.strip().replace('\n', ' ')[:120]
        return smart_recall_summary(short, limit=5, caller='codex')
    except Exception:
        return ''


def handle_chat(handler) -> None:
    """POST /api/agent/chat — CLI spawn + SSE 실시간 스트리밍.

    [cokacdir 패턴 서버 구현]
    1. 요청 본문에서 터미널 ID, 메시지, CLI 종류, YOLO 모드 수신
    2. CLI 프로세스를 spawn하고 stdin으로 메시지 전달
    3. stdout을 SSE(text/event-stream)로 실시간 전달
    4. 세션 ID 저장하여 다음 요청에서 --resume으로 컨텍스트 유지

    요청 본문:
        { "terminal_id": "T1", "message": "안녕", "cli": "claude", "yolo": false }

    SSE 이벤트 형식:
        data: {"type": "text", "content": "응답 텍스트"}
        data: {"type": "tool_use", "name": "Read", "input": "..."}
        data: {"type": "session", "session_id": "abc..."}
        data: {"type": "done", "full_text": "전체 응답"}
        data: {"type": "error", "message": "에러 내용"}
    """
    data = _read_body(handler)
    terminal_id = data.get('terminal_id', 'T1')
    message = data.get('message', '').strip()
    cli = data.get('cli', 'claude')
    yolo = data.get('yolo', False)

    if not message:
        _json_response(handler, {'error': 'empty_message'}, 400)
        return

    # 터미널 ID 정규화
    if terminal_id and terminal_id.isdigit():
        terminal_id = f'T{terminal_id}'

    # 기존 세션에서 session_id 가져오기
    with _chat_sessions_lock:
        session = _chat_sessions.get(terminal_id, {})
        session_id = session.get('session_id')
        # 이전 프로세스 상태 확인
        old_proc = session.get('proc')
        if old_proc is not None:
            if old_proc.poll() is None:
                # 아직 실행 중이면 거부
                _json_response(handler, {'error': 'already_streaming',
                                         'detail': '이전 응답이 진행 중입니다. /stop 후 재시도하세요.'}, 409)
                return
            else:
                # 이미 종료됐지만 정리되지 않은 좀비 프로세스 — 즉시 정리
                session['proc'] = None

    # CLI 명령 구성 — Claude는 -p 인자로 메시지 직접 전달 (stdin 파이프 불필요)
    cmd = _build_chat_cmd(cli, session_id, yolo, message=message if cli == 'claude' else '')

    # SSE 헤더 전송
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/event-stream; charset=utf-8')
    handler.send_header('Cache-Control', 'no-cache')
    handler.send_header('Connection', 'keep-alive')
    handler.send_header('Access-Control-Allow-Origin', handler._cors_origin())
    handler.end_headers()

    def _sse_send(event_data: dict) -> bool:
        """SSE 이벤트 전송. 연결 끊김 시 False 반환."""
        try:
            line = f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
            handler.wfile.write(line.encode('utf-8'))
            handler.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    try:
        # CLI 프로세스 spawn
        # Claude: -p 인자로 메시지 전달 → stdin=DEVNULL (파이프 아닌 /dev/null)
        #   → "stdin is not a terminal" 에러 방지
        # Antigravity/Codex: stdin=PIPE로 메시지 전달 (기존 방식 유지)
        use_stdin_pipe = (cli != 'claude')
        # stderr=DEVNULL로 변경 — stderr 버퍼 데드락 방지
        # (stderr가 꽉 차면 자식 프로세스가 block → stdout 읽기도 멈춤)
        # shell=True 필수 — Windows에서 claude.CMD 등 .cmd 파일은 cmd.exe 경유 필요
        # [과거사고] 여기 creationflags 누락 시 채팅 메시지 전송마다 shell=True cmd.exe 창이
        # 번쩍였다(2026-07-19 발견). _proc.popen이 CREATE_NO_WINDOW를 자동 주입해 차단.
        proc = _proc.popen(
            cmd,
            stdin=_sp.PIPE if use_stdin_pipe else _sp.DEVNULL,
            stdout=_sp.PIPE,
            stderr=_sp.DEVNULL,
            cwd=_project_root,
            shell=True,
            encoding=None,  # 바이너리 모드
        )

        # 세션에 프로세스 등록
        with _chat_sessions_lock:
            if terminal_id not in _chat_sessions:
                _chat_sessions[terminal_id] = {'session_id': None, 'proc': None, 'history': [], 'cli': cli}
            _chat_sessions[terminal_id]['proc'] = proc
            _chat_sessions[terminal_id]['cli'] = cli

        # Antigravity/Codex: stdin에 메시지 전달 후 EOF
        if use_stdin_pipe:
            # [로드맵 ③] 회상 주입은 stdin 중계분에만 — history/_bus_append는 원문 유지
            # (채팅 UI/텔레그램에 회상 블록 노출 금지). codex 한정: claude/antigravity는
            # 자체 훅이 이미 주입하므로 여기서 또 하면 이중 주입.
            relay_text = message
            if cli == 'codex':
                prefix = _codex_recall_prefix(message, handler.server.server_address[1])
                if prefix:
                    relay_text = f"[하이브 회상 — 과거 지식]\n{prefix}\n---\n{message}"
            proc.stdin.write(relay_text.encode('utf-8'))
            proc.stdin.close()

        # 히스토리에 사용자 메시지 추가 + 메시지 버스 기록 (텔레그램 동기화)
        with _chat_sessions_lock:
            _chat_sessions[terminal_id]['history'].append({
                'role': 'user', 'content': message, 'ts': time.strftime('%Y-%m-%dT%H:%M:%S')
            })
        _bus_append(terminal_id, 'dashboard', 'user', message)

        # stdout 스트리밍 파싱 → SSE 전송
        full_text = ""
        new_session_id = None

        for raw_line in proc.stdout:
            line = raw_line.decode('utf-8', errors='replace').strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                # stream-json이 아닌 일반 텍스트 출력 (antigravity/codex)
                full_text += line + "\n"
                if not _sse_send({'type': 'text', 'content': line}):
                    break
                continue

            msg_type = msg.get('type', '')

            # ── init: 세션 ID 수신 ──
            if msg_type == 'system' and msg.get('subtype') == 'init':
                sid = msg.get('session_id', '')
                if sid:
                    new_session_id = sid
                    _sse_send({'type': 'session', 'session_id': sid})

            # ── assistant 텍스트 (실시간 스트리밍) ──
            elif msg_type == 'assistant':
                content = msg.get('message', {}).get('content', '')
                if isinstance(content, str) and content:
                    full_text += content
                    _sse_send({'type': 'text', 'content': content})
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            if block.get('type') == 'text':
                                text_val = block.get('text', '')
                                full_text += text_val
                                _sse_send({'type': 'text', 'content': text_val})
                            elif block.get('type') == 'tool_use':
                                _sse_send({
                                    'type': 'tool_use',
                                    'name': block.get('name', ''),
                                    'input': str(block.get('input', ''))[:200],
                                })

            # ── tool_use / tool_result ──
            elif msg_type == 'content_block_start':
                cb = msg.get('content_block', {})
                if cb.get('type') == 'tool_use':
                    _sse_send({
                        'type': 'tool_use',
                        'name': cb.get('name', ''),
                        'input': str(cb.get('input', ''))[:200],
                    })

            # ── result (완료) ──
            # result 이벤트에는 전체 응답 텍스트가 들어있음.
            # assistant 이벤트로 이미 스트리밍한 경우 중복 전송하지 않음.
            elif msg_type == 'result':
                result_text = msg.get('result', '')
                sid = msg.get('session_id', '')
                if sid:
                    new_session_id = sid
                if result_text and not full_text:
                    # assistant 스트리밍이 없었던 경우에만 result 텍스트 전송
                    full_text = result_text
                    _sse_send({'type': 'text', 'content': result_text})

        # 프로세스 종료 대기
        proc.wait(timeout=5)

        # 세션 ID 업데이트 + 히스토리에 응답 추가
        # 세션 ID 업데이트 + 히스토리에 응답 추가 + 메시지 버스 기록
        with _chat_sessions_lock:
            if new_session_id:
                _chat_sessions[terminal_id]['session_id'] = new_session_id
            _chat_sessions[terminal_id]['proc'] = None
            _chat_sessions[terminal_id]['history'].append({
                'role': 'assistant', 'content': full_text, 'ts': time.strftime('%Y-%m-%dT%H:%M:%S')
            })
            # 히스토리 100개 제한
            if len(_chat_sessions[terminal_id]['history']) > 100:
                _chat_sessions[terminal_id]['history'] = _chat_sessions[terminal_id]['history'][-100:]
        _bus_append(terminal_id, 'dashboard', 'assistant', full_text)

        _sse_send({'type': 'done', 'full_text': full_text, 'session_id': new_session_id or session_id})

    except Exception as exc:
        _sse_send({'type': 'error', 'message': str(exc)})
        # 프로세스 정리
        with _chat_sessions_lock:
            session = _chat_sessions.get(terminal_id, {})
            p = session.get('proc')
            if p and p.poll() is None:
                try:
                    p.kill()
                except Exception:
                    pass
            if terminal_id in _chat_sessions:
                _chat_sessions[terminal_id]['proc'] = None


def handle_chat_stop(handler) -> None:
    """POST /api/agent/chat/stop — 채팅 모드 진행 중인 CLI 프로세스 종료.

    요청 본문: { "terminal_id": "T1" }
    """
    data = _read_body(handler)
    terminal_id = data.get('terminal_id', 'T1')
    if terminal_id and terminal_id.isdigit():
        terminal_id = f'T{terminal_id}'

    with _chat_sessions_lock:
        session = _chat_sessions.get(terminal_id, {})
        proc = session.get('proc')
        if proc and proc.poll() is None:
            try:
                # Windows: taskkill /T /F로 프로세스 트리 종료
                # [WHY] os.system은 항상 cmd.exe를 새로 띄워 채팅 stop마다 검은 창이 번쩍인다.
                # _proc.run(콘솔 숨김 주입)으로 콘솔 없이 조용히 트리 킬.
                if sys.platform == 'win32':
                    _proc.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                              capture_output=True)
                else:
                    proc.kill()
                session['proc'] = None
                _json_response(handler, {'status': 'stopped', 'terminal_id': terminal_id})
            except Exception as e:
                _json_response(handler, {'error': str(e)}, 500)
        else:
            _json_response(handler, {'status': 'not_running', 'terminal_id': terminal_id})


def handle_chat_history(handler) -> None:
    """GET /api/agent/chat/history?terminal_id=T1 — 채팅 히스토리 반환.

    응답: { "terminal_id": "T1", "cli": "claude", "session_id": "abc...",
            "history": [{"role": "user", "content": "...", "ts": "..."}], "streaming": false }
    """
    # URL 쿼리 파라미터 파싱
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(handler.path)
    params = parse_qs(parsed.query)
    terminal_id = params.get('terminal_id', ['T1'])[0]

    with _chat_sessions_lock:
        session = _chat_sessions.get(terminal_id, {})
        proc = session.get('proc')
        is_streaming = proc is not None and proc.poll() is None

    _json_response(handler, {
        'terminal_id': terminal_id,
        'cli': session.get('cli', ''),
        'session_id': session.get('session_id', ''),
        'history': session.get('history', []),
        'streaming': is_streaming,
    })


# ── 메시지 버스 API (대시보드 ↔ 텔레그램 양방향 동기화) ──────────────────────

def handle_chat_feed(handler) -> None:
    """GET /api/agent/chat/feed?terminal_id=T1&since=0 — 메시지 버스 폴링.

    since 이후의 새 메시지를 반환합니다. 대시보드와 텔레그램 양쪽에서 폴링하여
    상대방 채널의 메시지를 수신합니다.

    응답: { "messages": [...], "latest_seq": N }
    """
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(handler.path)
    params = parse_qs(parsed.query)
    terminal_id = params.get('terminal_id', ['T1'])[0]
    since = int(params.get('since', ['0'])[0])

    with _chat_bus_lock:
        bus = _chat_bus.get(terminal_id, [])
        # since 이후 메시지만 필터링
        new_msgs = [m for m in bus if m['seq'] > since]
        latest_seq = _chat_bus_seq.get(terminal_id, 1) - 1

    _json_response(handler, {
        'messages': new_msgs,
        'latest_seq': max(latest_seq, 0),
    })


def handle_chat_bus_post(handler) -> None:
    """POST /api/agent/chat/bus — 외부 채널(텔레그램)에서 메시지 버스에 기록.

    요청 본문: { "terminal_id": "T1", "source": "telegram", "role": "user",
                "content": "메시지 내용", "tg_user": "홍길동" }
    응답: { "status": "ok", "seq": N }
    """
    data = _read_body(handler)
    terminal_id = data.get('terminal_id', 'T1')
    source = data.get('source', 'telegram')
    role = data.get('role', 'user')
    content = data.get('content', '')
    tg_user = data.get('tg_user')

    if not content.strip():
        _json_response(handler, {'error': 'empty_content'}, 400)
        return

    seq = _bus_append(terminal_id, source, role, content, tg_user=tg_user)
    _json_response(handler, {'status': 'ok', 'seq': seq})


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
    if path.startswith('/api/agent/chat/feed'):
        handle_chat_feed(handler)
        return True
    if path.startswith('/api/agent/chat/history'):
        handle_chat_history(handler)
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
    if path == '/api/agent/heartbeat':
        handle_heartbeat(handler)
        return True
    if path == '/api/agent/chat/bus':
        handle_chat_bus_post(handler)
        return True
    if path == '/api/agent/chat':
        handle_chat(handler)
        return True
    if path == '/api/agent/chat/stop':
        handle_chat_stop(handler)
        return True
    return False
