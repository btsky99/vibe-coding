# -*- coding: utf-8 -*-
"""
# ------------------------------------------------------------------------
# 파일명: scripts/agent_shell.py
# 설명: 터미널 전용 자율 에이전트 인터랙티브 쉘.
#       각 터미널에서 직접 지시를 입력하면 Claude/Gemini/Codex CLI가 자동 실행되고
#       출력을 실시간으로 터미널에 스트리밍합니다.
#
# 사용법:
#   python scripts/agent_shell.py                         # 자동 라우팅
#   python scripts/agent_shell.py --cli claude            # 항상 Claude
#   python scripts/agent_shell.py --cli gemini            # 항상 Gemini
#   python scripts/agent_shell.py --cli codex             # 항상 Codex (YOLO 자율 모드)
#   python scripts/agent_shell.py --terminal T2           # 터미널 ID 지정
#
# 변경 이력 (REVISION HISTORY):
# [2026-03-04] Claude: 최초 구현
#   - 인터랙티브 REPL: 지시 입력 -> CLI 자동 선택 -> 실시간 스트리밍 출력
#   - --cli: auto(기본) / claude / gemini
#   - --terminal: 터미널 ID 표시 (T1, T2 등)
#   - agent_live.jsonl 동시 기록: 대시보드에서도 실시간 확인 가능
#   - Ctrl+C: 실행 중 에이전트 중단 지원
#   - Windows CREATE_NO_WINDOW + shell=True: .cmd CLI 호환
# [2026-03-04] Claude: 오케스트레이터 자동 라우팅 추가
#   - 복합 지시(여러 작업 나열) 감지 시 서버 API 경유 오케스트레이터 실행
#   - _route()가 'orchestrator' 반환 시 HTTP API로 전달 (대시보드 연동)
# [2026-03-07] Claude: Codex CLI 지원 추가
#   - --cli codex: Vibe Coding Codex 래퍼를 통해 자율 YOLO 모드 실행
#   - !cli codex: 실행 중 즉석 CLI 변경 지원
# ------------------------------------------------------------------------
"""

import os
import sys
import json
import signal
import subprocess
from datetime import datetime
from pathlib import Path
from urllib import request as _urllib_req
from urllib.error import URLError

_SCRIPTS_DIR = Path(__file__).resolve().parent
_ROOT        = _SCRIPTS_DIR.parent
_DATA_DIR    = _ROOT / '.ai_monitor' / 'data'
_LIVE_FILE   = _DATA_DIR / 'agent_live.jsonl'

_CLAUDE_KW = [
    '코드', '구현', '수정', '버그', '파일', '함수', '클래스', '테스트',
    '추가', '삭제', '리팩터', '리팩토링', '컴포넌트', '빌드',
    'code', 'fix', 'implement', 'write', 'create', 'test', 'build',
    'refactor', 'bug', 'error', 'class', 'function', 'component',
]
_GEMINI_KW = [
    '설계', '분석', '검토', '브레인', '아키텍처', '계획', '문서',
    '리뷰', '평가', '조사', '정리', '요약',
    'design', 'analyze', 'review', 'plan', 'architecture',
    'document', 'research', 'summary', 'evaluate',
]

_active_proc = None

# 복합 지시 감지 키워드 → 오케스트레이터로 라우팅
_ORCH_KW = [
    '자동으로', '전부', '전체', '다 해줘', '다해줘', '알아서',
    '순서대로', '차례로', '단계별로', '하나씩',
    '하고', '그리고', '다음에',
    '고치고 테스트', '테스트하고 배포', '만들고 커밋', '구현하고 빌드',
    'orchestrat',
]

# 서버 API 포트 (server.py 기본값)
_SERVER_PORT   = 9571
_API_URL       = f'http://localhost:{_SERVER_PORT}/api/agent/run'
_DASHBOARD_URL = f'http://localhost:{_SERVER_PORT}'

# 이미 열린 경우 중복 오픈 방지 (프로세스 내 1회)
_dashboard_opened = False


def _route(task):
    """지시를 분석하여 실행 주체를 반환합니다.

    반환값:
      'orchestrator' - 복합 지시 (서버 API 경유)
      'claude'       - 코드 구현/수정
      'gemini'       - 설계/분석
    """
    t = task.lower()
    # 복합 지시 감지 (오케스트레이터 최우선)
    if any(kw in t for kw in _ORCH_KW):
        return 'orchestrator'
    c = sum(1 for kw in _CLAUDE_KW if kw in t)
    g = sum(1 for kw in _GEMINI_KW if kw in t)
    return 'gemini' if g > c else 'claude'


def _call_api(task: str) -> bool:
    """서버 API로 오케스트레이터 실행 요청을 전송합니다.

    성공 시 True 반환. 서버 미실행 시 False 반환 (fallback: claude 직접 실행).
    """
    payload = json.dumps({'task': task, 'cli': 'auto'}).encode('utf-8')
    req = _urllib_req.Request(
        _API_URL,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with _urllib_req.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except (URLError, Exception):
        return False


def _write_live(event):
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        with _LIVE_FILE.open('a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')
    except Exception:
        pass


def run_agent(task, cli='auto', terminal_id='T?'):
    global _active_proc

    chosen = _route(task) if cli == 'auto' else cli
    ts = datetime.now().isoformat()

    print(f'\n+--[{terminal_id}] {chosen.upper()} 에이전트 실행')
    print(f'|  지시: {task[:80]}{"..." if len(task) > 80 else ""}')
    print(f'+{"-" * 58}')

    # 오케스트레이터 모드: 복합 지시는 서버 API로 전달 (대시보드 연동)
    if chosen == 'orchestrator':
        ok = _call_api(task)
        if ok:
            print(f'[{terminal_id}] 오케스트레이터 실행 요청 전송됨')
            _write_live({'type': 'done', 'status': 'dispatched', 'cli': 'orchestrator',
                         'terminal': terminal_id, 'ts': ts})
            return 0
        else:
            # 서버 미실행: claude로 fallback
            print(f'[{terminal_id}] 서버 미실행 — Claude로 fallback 실행')
            chosen = 'claude'

    _write_live({'type': 'started', 'cli': chosen, 'task': task,
                 'terminal': terminal_id, 'ts': ts})

    if chosen == 'claude':
        cmd = ['claude', '-p', task, '--dangerously-skip-permissions']
    elif chosen == 'codex':
        # Codex CLI: 프로젝트 루트의 codex.bat을 통해 YOLO 자율 모드로 실행
        # --yolo 플래그: 확인 없이 자율적으로 과업을 완수하는 에이전트 모드
        cmd = ['codex', '--yolo', task]
    else:
        cmd = ['gemini', '-p', task]

    # 중복 세션 에러 방지: CLAUDECODE 관련 환경 변수 제거
    # VIBE_CHILD_AGENT=1: 자식 claude -p 세션에서 hook_bridge.py가 또 실행되어
    # 서버 API를 재호출하는 이중 실행 루프 방지
    env = os.environ.copy()
    env.pop('CLAUDECODE', None)
    env.pop('CLAUDE_CODE_ENTRYPOINT', None)
    env.pop('CLAUDE_CODE_SSE_PORT', None)
    env['VIBE_CHILD_AGENT'] = '1'

    kw = {}
    use_shell = False
    if os.name == 'nt':
        # CREATE_NO_WINDOW만 사용: DETACHED_PROCESS를 같이 쓰면
        # stdout PIPE 연결이 끊어져 Claude/Gemini 출력이 터미널에 안 나옴.
        kw['creationflags'] = subprocess.CREATE_NO_WINDOW
        use_shell = True
        cmd = subprocess.list2cmdline(cmd)

    rc = 1
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            shell=use_shell,
            bufsize=0,
            cwd=str(_ROOT),
            env=env,
            **kw,
        )
        _active_proc = proc

        for raw in iter(proc.stdout.readline, b''):
            if raw:
                line = raw.decode('utf-8', errors='replace').rstrip()
                print(line)
                _write_live({'type': 'output', 'line': line,
                             'cli': chosen, 'terminal': terminal_id,
                             'ts': datetime.now().isoformat()})

        proc.wait()
        rc = proc.returncode

    except FileNotFoundError:
        msg = f'[오류] {chosen} CLI를 찾을 수 없습니다. 설치 여부를 확인하세요.'
        print(msg)
        _write_live({'type': 'error', 'line': msg, 'terminal': terminal_id,
                     'ts': datetime.now().isoformat()})
        rc = 1
    finally:
        _active_proc = None

    status = 'done' if rc == 0 else ('stopped' if rc < 0 else 'error')
    icon = 'OK' if status == 'done' else ('STOP' if status == 'stopped' else 'ERR')
    print(f'\n[{icon}] [{terminal_id}] 완료 -- 상태: {status} (코드: {rc})')
    _write_live({'type': 'done', 'status': status, 'cli': chosen,
                 'terminal': terminal_id, 'ts': datetime.now().isoformat()})

    return rc


def _stop_active():
    global _active_proc
    proc = _active_proc
    if proc and proc.poll() is None:
        print('\n[중단] 에이전트를 종료합니다...')
        try:
            if os.name == 'nt':
                subprocess.call(
                    ['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def main():
    args = sys.argv[1:]
    cli_mode    = 'auto'
    terminal_id = 'T1'

    i = 0
    while i < len(args):
        if args[i] == '--cli' and i + 1 < len(args):
            cli_mode = args[i + 1]
            i += 2
        elif args[i] == '--terminal' and i + 1 < len(args):
            terminal_id = args[i + 1]
            i += 2
        else:
            i += 1

    def _sigint_handler(sig, frame):
        if _active_proc and _active_proc.poll() is None:
            _stop_active()
        else:
            print('\n\n[종료] 에이전트 쉘을 닫습니다.')
            sys.exit(0)

    signal.signal(signal.SIGINT, _sigint_handler)

    cli_label = cli_mode.upper() if cli_mode != 'auto' else 'AUTO(Claude/Gemini/Codex)'
    print('=' * 60)
    print(f' Agent Shell [{terminal_id}]  CLI: {cli_label}')
    print(f' 프로젝트: {_ROOT.name}')
    print(f' 종료: exit | 에이전트 중단: Ctrl+C')
    print('=' * 60)

    while True:
        try:
            task = input(f'\n[{terminal_id}:{cli_mode}]> ').strip()
        except (EOFError, KeyboardInterrupt):
            print('\n[종료]')
            break

        if not task:
            continue

        if task.lower() in ('exit', 'quit', '종료', 'q'):
            print('[종료] 에이전트 쉘을 닫습니다.')
            break

        if len(task) < 3:
            print('[무시] 3자 이상 입력해주세요.')
            continue

        # 즉석 CLI 변경: !cli claude / !cli gemini / !cli codex / !cli auto
        if task.startswith('!cli '):
            new_cli = task[5:].strip()
            if new_cli in ('auto', 'claude', 'gemini', 'codex'):
                cli_mode = new_cli
                print(f'[설정] CLI 변경 -> {cli_mode}')
            else:
                print('[오류] auto / claude / gemini / codex 중 선택하세요.')
            continue

        run_agent(task, cli_mode, terminal_id)


if __name__ == '__main__':
    main()
