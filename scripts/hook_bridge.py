# -*- coding: utf-8 -*-
"""
# ------------------------------------------------------------------------
# 파일명: scripts/hook_bridge.py
# 설명: Claude Code UserPromptSubmit 훅 브릿지.
#       Claude Code CLI에서 사용자가 메시지를 입력하면,
#       서버 HTTP API(/api/agent/run)를 호출하여 대시보드 자율 에이전트를 실행합니다.
#       서버 미실행 시 fallback으로 cli_agent.py를 직접 subprocess로 실행합니다.
#
# 변경 이력 (REVISION HISTORY):
# [2026-03-04] Claude: 최초 구현
#   - UserPromptSubmit 훅에서 stdin JSON 파싱
#   - cli_agent.py에 auto 모드로 라우팅 (Claude/Gemini 자동 선택)
#   - 무한루프 방지: "[지시]" 접두사가 없는 메시지만 전달
#   - 백그라운드 실행: 훅이 Claude 응답을 블로킹하지 않도록 non-blocking
# [2026-03-04] Claude: [버그수정] 직접 subprocess 방식 -> HTTP API 방식으로 전환
# [2026-03-04] Claude: 멀티터미널 + 가시성 개선
#   - TERMINAL_ID 환경변수 지원: 터미널별 에이전트 요청 추적
#   - stdout 피드백: 에이전트 시작/대기중/오프라인 상태를 Claude context에 출력
#   - already_running(409) 처리: 사용자에게 현재 에이전트 상태 안내
# [2026-03-04] Claude: 서버 자동 시작 로직 추가
#   - _is_server_alive(): 헬스체크 (HEALTH_URL 응답 확인)
#   - _start_server(): 서버 미실행 시 server.py를 백그라운드 자동 기동 (최대 5초 대기)
#   - fallback 순서: 서버 API → 서버 자동시작 후 재시도 → 직접 subprocess
#   - 각 터미널 지시 입력 시 서버 없어도 자동으로 에이전트 연결됨
# ------------------------------------------------------------------------
"""

import sys
import json
import subprocess
import os
import webbrowser
from pathlib import Path
from urllib import request as urllib_request
from urllib.error import URLError

# --- 경로 설정 ---
SCRIPT_DIR  = Path(__file__).parent
CLI_AGENT   = SCRIPT_DIR / 'cli_agent.py'
SERVER_PY   = SCRIPT_DIR.parent / '.ai_monitor' / 'server.py'
CWD         = SCRIPT_DIR.parent  # D:/vibe-coding
SERVER_PORT = 9571
API_URL     = f'http://localhost:{SERVER_PORT}/api/agent/run'
HEALTH_URL  = f'http://localhost:{SERVER_PORT}/api/hive/health'

# --- 터미널 ID ---
# 각 터미널 실행 전 환경변수로 지정:
#   Terminal 1: set TERMINAL_ID=T1 && claude
#   Terminal 2: set TERMINAL_ID=T2 && claude
# 미지정 시 "T0" 사용
TERMINAL_ID   = os.environ.get('TERMINAL_ID', 'T0')
MONITOR_PORT  = 9580  # 상황판 전용 미니 서버 포트
MONITOR_URL   = f'http://localhost:{MONITOR_PORT}'
MONITOR_SRV   = SCRIPT_DIR / 'monitor_server.py'
# 창 열림 여부를 프로세스 간 공유하는 플래그 파일 (중복 창 방지)
_WINDOW_FLAG  = SCRIPT_DIR.parent / '.ai_monitor' / 'data' / '.monitor_opened'
# Chrome 실행 파일 경로 (우선순위 순)
_CHROME_PATHS = [
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    r'C:\Users\com\AppData\Local\Google\Chrome\Application\chrome.exe',
]

def _ensure_monitor_server() -> bool:
    """상황판 미니 서버(9572)가 실행 중인지 확인, 없으면 시작합니다."""
    import urllib.request
    try:
        urllib.request.urlopen(MONITOR_URL, timeout=1)
        return True  # 이미 실행 중
    except Exception:
        pass
    # 서버 시작
    try:
        subprocess.Popen(
            [sys.executable, str(MONITOR_SRV)],
            cwd=str(CWD),
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS if os.name == 'nt' else 0,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        import time; time.sleep(1)
        return True
    except Exception:
        return False

def _open_monitor_window() -> None:
    """에이전트 상황판을 별도 Chrome 창으로 엽니다 (포트 9580 전용 서버).
    플래그 파일로 프로세스 간 중복 창 방지: 이미 열린 경우 재오픈하지 않음.
    """
    # 플래그 파일 존재 시 이미 창이 열린 것으로 간주 → 즉시 스킵
    if _WINDOW_FLAG.exists():
        return
    # 플래그 파일 생성 (다른 프로세스/터미널이 동시에 열지 못하도록)
    try:
        _WINDOW_FLAG.parent.mkdir(parents=True, exist_ok=True)
        _WINDOW_FLAG.touch()
    except Exception:
        pass
    # 서버 시작 + 창 오픈
    _ensure_monitor_server()
    for chrome in _CHROME_PATHS:
        if Path(chrome).exists():
            try:
                subprocess.Popen([chrome, '--new-window', MONITOR_URL])
                return
            except Exception:
                continue
    try:
        webbrowser.open_new(MONITOR_URL)
    except Exception:
        pass

# --- 무시할 접두사 (무한루프 방지) ---
SKIP_PREFIXES = ['[지시]', '[오류]', '[완료]', '[INFO]', '[OK]', '[🤖', 'python ', 'git ']

# --- 무시할 키워드 (메타 명령어) ---
SKIP_KEYWORDS = ['/commit', '/review', '/plan', '/help', '/clear']


def _notify(msg: str) -> None:
    """Claude Code context에 상태 메시지 출력.
    훅의 stdout은 Claude가 system-reminder로 읽으므로 Claude 응답에 반영됨.
    """
    print(msg, flush=True)


def _call_api(prompt: str) -> dict | None:
    """서버 HTTP API로 에이전트 실행 요청 전송.
    반환: dict(서버 응답) 또는 None(서버 미실행)
    """
    payload = json.dumps({
        'task': prompt,
        'cli': 'auto',
        'terminal_id': TERMINAL_ID,
    }).encode('utf-8')

    req = urllib_request.Request(
        API_URL,
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )

    try:
        with urllib_request.urlopen(req, timeout=2) as resp:
            body = resp.read().decode('utf-8')
            return json.loads(body) if body else {'status': 'started'}
    except urllib_request.HTTPError as e:
        # 4xx/5xx 응답도 body를 파싱하여 반환 (409 already_running 등 처리)
        try:
            body = e.read().decode('utf-8')
            return json.loads(body) if body else {'error': str(e)}
        except Exception:
            return {'error': str(e)}
    except URLError:
        return None
    except Exception:
        return None


def _is_server_alive() -> bool:
    """서버 헬스체크. 응답하면 True."""
    try:
        with urllib_request.urlopen(HEALTH_URL, timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def _start_server() -> bool:
    """서버가 꺼져있으면 백그라운드로 자동 시작합니다.

    최대 5초 대기 후 서버가 응답하면 True 반환.
    서버 프로세스는 현재 터미널 세션과 독립적으로 유지됩니다.
    """
    if not SERVER_PY.exists():
        return False

    # Windows: 새 콘솔 없이 백그라운드 실행
    creationflags = 0
    if os.name == 'nt':
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS

    try:
        subprocess.Popen(
            [sys.executable, str(SERVER_PY)],
            cwd=str(CWD),
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, 'VIBE_AGENT_MODE': '1'},  # 서버 자체가 훅을 재트리거하지 않도록
        )
    except Exception:
        return False

    # 최대 5초 대기 (0.5초 간격 × 10회)
    import time
    for _ in range(10):
        time.sleep(0.5)
        if _is_server_alive():
            return True

    return False


def _fallback_subprocess(prompt: str) -> None:
    """서버 완전 오프라인 시 cli_agent.py를 백그라운드로 실행 (창 점유 없음).

    서버가 정상 동작하면 이 함수는 호출되지 않음.
    결과는 agent_runs.jsonl / agent_live.jsonl에 저장됨.
    """
    creationflags = 0
    if os.name == 'nt':
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS

    subprocess.Popen(
        [sys.executable, str(CLI_AGENT), prompt, 'auto'],
        cwd=str(CWD),
        creationflags=creationflags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, 'VIBE_CHILD_AGENT': '1'},
    )


def main():
    # 캐스케이드 루프 방지: cli_agent.py가 spawn한 자식 프로세스(VIBE_CHILD_AGENT=1)는 즉시 종료.
    # VIBE_AGENT_MODE는 서버/다른 용도로도 사용되므로 체크하지 않음.
    if os.environ.get('VIBE_CHILD_AGENT'):
        sys.exit(0)

    # stdin에서 훅 데이터 읽기
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    prompt = data.get('prompt', '').strip()

    # 빈 메시지 스킵
    if not prompt:
        sys.exit(0)

    # 무시할 접두사 스킵 (무한루프 방지)
    for prefix in SKIP_PREFIXES:
        if prompt.startswith(prefix):
            sys.exit(0)

    # 슬래시 명령어 스킵
    for kw in SKIP_KEYWORDS:
        if prompt.startswith(kw):
            sys.exit(0)

    # 너무 짧은 메시지 스킵 (단순 인사, y/n 등)
    if len(prompt) < 5:
        sys.exit(0)

    # 터미널 이스케이프 시퀀스 스킵 (ESC [ 또는 ESC ] 로 시작하는 garbage 입력 차단)
    # 예: "[O]11;rgb:1e1e/1e1e/1e1e" 같은 색상 제어 코드가 task로 들어오는 현상 방지
    import re
    if re.search(r'[\x00-\x1f]|\[O\]|\\\]|\x1b[\[\]]', prompt):
        sys.exit(0)
    # ESC 시퀀스 패턴이 텍스트로 들어온 경우도 차단 (e.g. "\033[" 형태)
    if re.match(r'^[\[\]\\x0-9a-fA-F;:/]+$', prompt[:20]):
        sys.exit(0)

    short_prompt = prompt[:50] + ('...' if len(prompt) > 50 else '')

    # 1순위: 서버 HTTP API 호출 (대시보드 SSE 연동)
    result = _call_api(prompt)

    if result is not None:
        # ── 서버 연결 성공 ──────────────────────────────────────────────
        if result.get('error') == 'already_running':
            current = result.get('current', {})
            current_task = current.get('task', '')[:40]
            _notify(f'[🤖 {TERMINAL_ID}] 에이전트 실행 중: "{current_task}..." — 완료 후 자동 처리됩니다.')
        else:
            chosen_cli = result.get('cli', 'auto')
            _notify(f'[🤖 {TERMINAL_ID}→{chosen_cli.upper()}] 자율 에이전트 시작됨: "{short_prompt}"')
            # 에이전트 시작 시 상황판을 별도 Chrome 창으로 오픈
            _open_monitor_window()
    else:
        # ── 서버 미실행 → 자동 시작 시도 후 재연결, 실패 시 동기 fallback
        _notify(f'[🤖 {TERMINAL_ID}] 백엔드 오프라인 — 자동 시작 중...')
        server_started = _start_server()

        if server_started:
            # 서버 기동 성공 → API 재호출
            result2 = _call_api(prompt)
            if result2 is not None:
                chosen_cli = result2.get('cli', 'auto')
                _notify(f'[🤖 {TERMINAL_ID}→{chosen_cli.upper()}] 서버 자동 시작 후 에이전트 시작됨: "{short_prompt}"')
            else:
                _notify(f'[🤖 {TERMINAL_ID}] 서버 시작됐으나 API 호출 실패 — fallback 실행')
                _fallback_subprocess(prompt)
        else:
            # 서버 시작 실패 → 동기 fallback (결과를 Claude 컨텍스트로 출력)
            _notify(f'[🤖 {TERMINAL_ID}→오프라인] 에이전트 실행 중 (서버 없음): "{short_prompt}"')
            _fallback_subprocess(prompt)

    # 훅은 0 반환 필수 (non-zero면 Claude가 응답 중단)
    sys.exit(0)


if __name__ == '__main__':
    main()
