# -*- coding: utf-8 -*-
"""
# ------------------------------------------------------------------------
# 파일명: scripts/terminal_agent.py
# 설명: 멀티터미널 자율 에이전트 디스패처 (REPL 모드).
#       일반 bash/cmd 터미널에서도 에이전트/오케스트레이터를 직접 실행합니다.
#       Claude Code 세션 없이도 동작합니다.
#
#       [사용법]
#         # 터미널 1:
#         set TERMINAL_ID=T1 && python scripts/terminal_agent.py
#
#         # 터미널 2:
#         set TERMINAL_ID=T2 && python scripts/terminal_agent.py
#
#         # 단발 실행 (REPL 없이):
#         python scripts/terminal_agent.py "버그 고쳐줘" [claude|gemini|auto]
#
#       [자동 라우팅 규칙]
#         - 설계/분석/계획/아키텍처 키워드 -> 오케스트레이터(vibe-orchestrate)
#         - 코드/버그/수정/구현 키워드     -> Claude Code CLI (-p 모드)
#         - 검토/리뷰/문서 키워드          -> Gemini CLI
#         - 기타                            -> Claude (기본값)
#
# 변경 이력 (REVISION HISTORY):
# [2026-03-04] Claude: 최초 구현
#   - REPL 모드: 빈 줄 입력 시 종료, Ctrl+C 안전 처리
#   - 단발 실행 모드: sys.argv[1]로 지시 전달
#   - 서버 API 우선 -> 서버 자동시작 시도 -> cli_agent.py 직접 실행 fallback
#   - 실시간 agent_live.jsonl tail: 에이전트 출력을 터미널에 스트리밍
#   - TERMINAL_ID 환경변수: 터미널별 구분 (T1, T2, ...)
#   - _route(): 복잡도 기반 오케스트레이터 vs 직접 에이전트 자동 선택
# ------------------------------------------------------------------------
"""

import sys
import os
import json
import subprocess
import threading
import time
from pathlib import Path
from urllib import request as urllib_request
from urllib.error import URLError

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).parent
CLI_AGENT   = SCRIPT_DIR / 'cli_agent.py'
SERVER_PY   = SCRIPT_DIR.parent / '.ai_monitor' / 'server.py'
CWD         = SCRIPT_DIR.parent
DATA_DIR    = CWD / '.ai_monitor' / 'data'
LIVE_FILE   = DATA_DIR / 'agent_live.jsonl'

SERVER_PORT = 8005
API_URL     = f'http://localhost:{SERVER_PORT}/api/agent/run'
HEALTH_URL  = f'http://localhost:{SERVER_PORT}/api/hive/health'

# ── 터미널 ID (환경변수로 각 터미널에서 설정) ──────────────────────────────────
TERMINAL_ID = os.environ.get('TERMINAL_ID', 'T?')

# ── 오케스트레이터 판정 키워드 (복잡 작업) ────────────────────────────────────
# 이 키워드가 많이 포함된 지시는 직접 실행 대신 오케스트레이터로 라우팅
ORCH_KEYWORDS = [
    '설계', '아키텍처', '계획', '전체', '자동', '시스템', '파이프라인',
    '브레인', '브레인스토밍', '분석', '검토', '리뷰', '전부', '다',
    'design', 'architecture', 'plan', 'system', 'pipeline', 'review',
    'analyze', 'orchestrate', 'full', 'all', 'everything',
]

# ── 출력 색상 (ANSI - Windows Terminal, macOS, Linux 지원) ──────────────────
C_RESET  = '\033[0m'
C_CYAN   = '\033[96m'
C_GREEN  = '\033[92m'
C_YELLOW = '\033[93m'
C_RED    = '\033[91m'
C_GRAY   = '\033[90m'
C_BOLD   = '\033[1m'


def _p(msg: str, color: str = '') -> None:
    """터미널에 색상 있는 메시지 출력 (flush 강제)."""
    print(f'{color}{msg}{C_RESET}', flush=True)


def _route(task: str) -> str:
    """지시 내용 분석 후 라우팅 대상 반환: 'orchestrate' | 'auto'.

    오케스트레이터 키워드가 많거나 지시가 복잡하면(다중 단계 추정) orchestrate,
    그 외 기본값은 'auto'(cli_agent가 claude/gemini 선택).
    """
    task_lower = task.lower()
    orch_score = sum(1 for kw in ORCH_KEYWORDS if kw in task_lower)

    # 여러 오케스트레이터 키워드 동시 매칭 or 3줄 이상 지시 -> 복잡 작업
    is_multiline = task.count('\n') >= 2
    if orch_score >= 2 or is_multiline:
        return 'orchestrate'

    return 'auto'


def _is_server_alive() -> bool:
    """서버 헬스체크."""
    try:
        with urllib_request.urlopen(HEALTH_URL, timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def _start_server() -> bool:
    """서버 자동 기동 (최대 5초 대기). 성공 시 True."""
    if not SERVER_PY.exists():
        return False

    creationflags = 0
    if os.name == 'nt':
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS

    env = {**os.environ, 'VIBE_AGENT_MODE': '1'}
    try:
        subprocess.Popen(
            [sys.executable, str(SERVER_PY)],
            cwd=str(CWD),
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
    except Exception:
        return False

    for _ in range(10):
        time.sleep(0.5)
        if _is_server_alive():
            return True
    return False


def _call_api(task: str, cli: str = 'auto') -> dict | None:
    """서버 API에 에이전트 실행 요청. 실패 시 None."""
    payload = json.dumps({
        'task': task,
        'cli': cli,
        'terminal_id': TERMINAL_ID,
    }).encode('utf-8')
    req = urllib_request.Request(
        API_URL,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib_request.urlopen(req, timeout=3) as resp:
            body = resp.read().decode('utf-8')
            return json.loads(body) if body else {'status': 'started'}
    except Exception:
        return None


def _run_direct(task: str, cli: str = 'auto') -> None:
    """서버 없을 때 cli_agent.py를 동기(foreground)로 직접 실행하고 출력 스트리밍.

    터미널 에이전트 모드에서는 출력이 보여야 하므로 DEVNULL이 아닌 PIPE를 사용합니다.
    """
    env = {k: v for k, v in os.environ.items() if k != 'CLAUDECODE'}
    env['VIBE_AGENT_MODE'] = '1'

    use_shell = False
    cmd = [sys.executable, str(CLI_AGENT), task, cli]

    if os.name == 'nt':
        use_shell = True
        cmd_str = subprocess.list2cmdline(cmd)
    else:
        cmd_str = cmd  # type: ignore[assignment]

    proc = subprocess.Popen(
        cmd_str if use_shell else cmd,
        cwd=str(CWD),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        shell=use_shell,
        bufsize=0,
    )

    # 실시간 출력 스트리밍
    try:
        for raw_line in iter(proc.stdout.readline, b''):
            if raw_line:
                line_data = raw_line.decode('utf-8', errors='replace').rstrip()
                # agent_live.jsonl 형식이면 파싱, 아니면 그대로 출력
                try:
                    evt = json.loads(line_data)
                    evt_type = evt.get('type', '')
                    text = evt.get('line', '')
                    if evt_type == 'started':
                        _p(f'  [시작] {evt.get("cli", "").upper()} 에이전트 가동', C_CYAN)
                    elif evt_type == 'done':
                        status = evt.get('status', '')
                        icon = '✓' if status == 'done' else '✗'
                        color = C_GREEN if status == 'done' else C_RED
                        _p(f'  [{icon} 완료] {status}', color)
                    elif text:
                        _p(f'  {text}', C_GRAY)
                except json.JSONDecodeError:
                    # JSON이 아닌 일반 텍스트 출력 (claude CLI 직접 출력 등)
                    _p(f'  {line_data}', C_GRAY)
    except KeyboardInterrupt:
        proc.terminate()
    finally:
        proc.wait()


def _tail_live(timeout_sec: float = 30.0) -> None:
    """서버 모드일 때 agent_live.jsonl을 tail하며 에이전트 출력을 터미널에 스트리밍.

    백그라운드 스레드에서 실행됩니다.
    timeout_sec 동안 'done' 이벤트가 오거나 파일 EOF가 유지되면 종료합니다.
    """
    start_ts = time.time()
    last_size = 0

    # 파일이 생길 때까지 최대 3초 대기
    deadline = time.time() + 3.0
    while not LIVE_FILE.exists() and time.time() < deadline:
        time.sleep(0.2)

    if not LIVE_FILE.exists():
        return

    # tail 방식: 현재 파일 크기부터 읽기 시작 (이전 내용 무시)
    try:
        last_size = LIVE_FILE.stat().st_size
    except Exception:
        last_size = 0

    done = False
    while not done and (time.time() - start_ts) < timeout_sec:
        time.sleep(0.3)
        try:
            cur_size = LIVE_FILE.stat().st_size
            if cur_size <= last_size:
                continue

            with LIVE_FILE.open('rb') as f:
                f.seek(last_size)
                new_bytes = f.read()

            last_size = cur_size

            for raw_line in new_bytes.decode('utf-8', errors='replace').splitlines():
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    evt = json.loads(raw_line)
                    evt_type = evt.get('type', '')
                    text = evt.get('line', '')

                    if evt_type == 'started':
                        _p(f'  [시작] {evt.get("cli", "").upper()} 에이전트 가동', C_CYAN)
                    elif evt_type == 'done':
                        status = evt.get('status', '')
                        icon = '✓' if status == 'done' else '✗'
                        color = C_GREEN if status == 'done' else C_RED
                        _p(f'  [{icon} 완료] {status}', color)
                        done = True
                        break
                    elif evt_type == 'stopped':
                        _p('  [중단] 사용자에 의해 중단됨', C_YELLOW)
                        done = True
                        break
                    elif evt_type == 'error' and text:
                        _p(f'  [오류] {text}', C_RED)
                    elif text:
                        _p(f'  {text}', C_GRAY)
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass


def dispatch(task: str, cli_override: str = 'auto') -> None:
    """지시를 분석하여 최적 에이전트/오케스트레이터로 라우팅하고 실행합니다.

    [라우팅 순서]
    1. _route()로 복잡도 판별 -> orchestrate / auto
    2. 서버 API 호출 시도
    3. 서버 없으면 자동 시작 후 재시도
    4. 서버 시작도 실패 -> cli_agent.py 직접 실행 (foreground, 실시간 출력)
    """
    if cli_override != 'auto':
        # 명시적 CLI 지정 시 라우팅 생략
        route = cli_override
    else:
        route = _route(task)

    short = task[:60] + ('...' if len(task) > 60 else '')
    route_label = '오케스트레이터' if route == 'orchestrate' else route.upper()
    _p(f'\n[🤖 {TERMINAL_ID}->{route_label}] "{short}"', C_BOLD + C_CYAN)

    # 실제 CLI 라우팅: orchestrate는 서버 측에서 처리하므로 api에 route='orchestrate' 전달
    cli_for_api = route  # 'orchestrate' | 'auto' | 'claude' | 'gemini'

    # 서버 API 호출
    result = _call_api(task, cli_for_api)

    if result is None and _start_server():
        _p('  [서버] 자동 시작 완료', C_GREEN)
        result = _call_api(task, cli_for_api)

    if result is not None:
        # 서버 모드: live 파일 tail로 실시간 출력
        if result.get('error') == 'already_running':
            current_task = result.get('current', {}).get('task', '')[:40]
            _p(f'  [대기] 실행 중: "{current_task}..." - 완료 후 처리됩니다.', C_YELLOW)
        else:
            _p('  [서버] 에이전트 전송됨 - 출력 스트리밍...', C_GRAY)
            _tail_live(timeout_sec=600)
    else:
        # 직접 실행 모드 (서버 없음)
        _p('  [직접실행] 서버 없이 에이전트 실행...', C_YELLOW)
        # orchestrate 요청이지만 서버 없으면 claude로 fallback
        actual_cli = 'auto' if route == 'orchestrate' else route
        _run_direct(task, actual_cli)


def _print_banner() -> None:
    """터미널 에이전트 시작 배너 출력."""
    server_status = '[온라인]' if _is_server_alive() else '[오프라인 - 자동시작]'
    _p(f'{C_BOLD}{C_CYAN}[Vibe Terminal Agent] {TERMINAL_ID}{C_RESET}')
    _p(f'  Claude Code + Gemini 자율 에이전트')
    _p(f'  서버: {server_status}  |  빈 줄 입력 -> 종료')
    _p(f'  라우팅: 복잡도 자동 감지 -> 에이전트/오케스트레이터 선택')
    _p('')


def _repl_mode() -> None:
    """대화형 REPL 모드 - 빈 줄이나 Ctrl+C까지 지시를 반복 처리."""
    _print_banner()

    while True:
        try:
            task = input(f'{C_BOLD}{C_CYAN}[{TERMINAL_ID}] > {C_RESET}').strip()
        except (EOFError, KeyboardInterrupt):
            _p('\n[종료] 터미널 에이전트를 종료합니다.', C_YELLOW)
            break

        if not task:
            _p('[종료] 터미널 에이전트를 종료합니다.', C_YELLOW)
            break

        dispatch(task)
        _p('')  # 빈 줄로 구분


# ── 진입점 ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    if len(sys.argv) >= 2:
        # 단발 실행 모드: python terminal_agent.py "지시" [claude|gemini|auto]
        _task = sys.argv[1]
        _cli  = sys.argv[2] if len(sys.argv) >= 3 else 'auto'
        dispatch(_task, _cli)
    else:
        # REPL 모드: python terminal_agent.py
        _repl_mode()
