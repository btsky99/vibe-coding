# -*- coding: utf-8 -*-
"""
FILE: scripts/hook_bridge.py
DESCRIPTION: Claude Code UserPromptSubmit 훅 브릿지 — 자율 에이전트 디스패치 및 하이브 컨텍스트 자동 주입.

REVISION HISTORY:
- 2026-08-02 Claude: 앱이 떠 있으면 server.py를 절대 스폰하지 않는 가드 추가
  (_is_app_server_running). 앱의 활성 프로젝트가 타 프로젝트일 때 슬러그 대조가
  실패해 매 메시지마다 2번째 인스턴스를 완전 부팅시켜 터미널이 통째로 죽던 사고 차단.
- 2026-07-16 Claude: 포트 선택에도 프로젝트 경계 — _server_port_for(슬러그 대조) 경유로
  API 호출, 자기 서버 없으면 자동 시작 경로. payload 꼬리표(c95b2ec)만으로는 타 프로젝트
  서버 '도착' 자체를 못 막던 잔여 구멍 청산.
- 2026-07-15 Claude: 크로스 프로젝트 간섭 수정 — payload에 호출 프로젝트 cwd/project_id
  탑재 + 409 배너에 타 프로젝트 실행 명시 + 오프라인 폴백에 작업 디렉토리 전달.
- 2026-03-19 Claude: 표준 헤더 형식 적용 (RULES.md 섹션 2 준수)
"""
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
#   - cli_agent.py에 auto 모드로 라우팅 (Claude/Antigravity 자동 선택)
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
# [2026-03-18] Claude: [버그수정] 프로세스 중복 생성 방지 — PID 락 파일 기반 가드
#   - 원인: 매 UserPromptSubmit마다 서버/에이전트를 새로 생성하면서 기존 프로세스 미종료
#   - 수정: _is_process_alive() + PID 락 파일로 서버·에이전트 중복 생성 차단
#   - _start_server(): PID 파일 확인 → 이미 실행 중이면 스킵
#   - _fallback_subprocess(): PID 파일 확인 → 이미 실행 중이면 스킵
# ------------------------------------------------------------------------
"""

import sys
import json
import subprocess
import os
import time
from pathlib import Path
from urllib import request as urllib_request
from urllib.error import URLError

# --- 경로 설정 ---
SCRIPT_DIR  = Path(__file__).parent
CLI_AGENT   = SCRIPT_DIR / 'cli_agent.py'
SERVER_PY   = SCRIPT_DIR.parent / '.ai_monitor' / 'server.py'
CWD         = SCRIPT_DIR.parent  # D:/vibe-coding
# [수정 2026-03-15 v3.7.67] 실행 중인 서버 포트 자동 탐색 (9000~9019 스캔)
# VIBE_SERVER_PORT 환경변수가 있으면 그걸 우선 사용하고, 없으면 9000부터 스캔
def _find_active_server_port(start: int = 9000, count: int = 20) -> int:
    """9000번대에서 실제 응답하는 서버 포트를 찾아 반환합니다."""
    env_port = os.getenv('VIBE_SERVER_PORT')
    if env_port:
        return int(env_port)
    for port in range(start, start + count):
        try:
            urllib_request.urlopen(f'http://localhost:{port}/api/hive/health', timeout=0.3)
            return port
        except Exception:
            continue
    return start  # 못 찾으면 기본값 반환

SERVER_PORT = _find_active_server_port()
API_URL     = f'http://localhost:{SERVER_PORT}/api/agent/run'
HEALTH_URL  = f'http://localhost:{SERVER_PORT}/api/hive/health'

# [과거사고 2026-07-16] 위 모듈 상수는 '첫 응답 포트'라 멀티 프로젝트 가동 시 타 프로젝트
# 서버를 가리킬 수 있음 — 실제 API 호출은 아래 프로젝트 대조 헬퍼를 경유한다.
# (모듈 상수는 슬러그 산출 불가 환경의 폴백으로만 유지 — 하위호환)
_PORT_CACHE: dict = {}  # project_id → 확정 포트 (양성 결과만 캐시 — 서버 기동 재탐색 허용)


def _server_port_for(project_id: str = '') -> int | None:
    """호출 프로젝트의 서버 포트. 자기 서버 없으면 None (타 서버 오염 금지)."""
    cached = _PORT_CACHE.get(project_id)
    if cached:
        return cached
    try:
        _monitor = str(SCRIPT_DIR.parent / '.ai_monitor')
        if _monitor not in sys.path:
            sys.path.insert(0, _monitor)
        from src.server_locator import find_server_port
        port = find_server_port(project_id=project_id)
    except Exception:
        port = SERVER_PORT  # 공용 모듈 불가 — 기존 첫 응답 동작 유지
    if port:
        _PORT_CACHE[project_id] = port
    return port

# --- 터미널 ID ---
# 각 터미널 실행 전 환경변수로 지정:
#   Terminal 1: set TERMINAL_ID=T1 && claude
#   Terminal 2: set TERMINAL_ID=T2 && claude
# 미지정 시 "T0" 사용
TERMINAL_ID   = os.environ.get('TERMINAL_ID', 'T0')


def _resolve_caller_project(data: dict) -> tuple[str, str]:
    """훅을 호출한 세션의 (프로젝트 루트, project_id 슬러그)를 반환.

    [과거사고 2026-07-15] 이 훅은 D:/vibe-coding 원본이 모든 프로젝트에 공유 등록됨.
    payload에 cwd/project_id를 안 실으면 서버 cli_agent가 _PROJECT_ROOT(=vibe-coding)로
    폴백해 다른 프로젝트의 지시가 vibe-coding 안에서 실행되는 교차 간섭 발생.
    호출 프로젝트의 진실은 Claude Code stdin JSON의 cwd 뿐이다.
    """
    raw_cwd = (data.get('cwd') or os.getcwd() or '').strip()
    try:
        _monitor = str(SCRIPT_DIR.parent / '.ai_monitor')
        if _monitor not in sys.path:
            sys.path.insert(0, _monitor)
        from infra.project_context import slugify, find_project_root_marker
        root = find_project_root_marker(Path(raw_cwd)) or Path(raw_cwd)
        return str(root), slugify(root)
    except Exception:
        return raw_cwd, ''

# --- PID 락 파일 경로 (중복 프로세스 생성 방지) ---
# [2026-03-18 Claude] 서버·에이전트 프로세스가 매 프롬프트마다 누적 생성되는 버그 수정
# 각 프로세스 유형별 PID를 파일에 기록하고, 해당 PID가 살아있으면 새로 생성하지 않음
_LOCK_DIR     = CWD / '.ai_monitor' / 'data'
_SERVER_PID   = _LOCK_DIR / '.server.pid'
_AGENT_PID    = _LOCK_DIR / '.agent.pid'
# 앱(GUI)이 직접 띄운 서버의 PID — 훅이 아니라 server.py가 기록하는 파일이라 소유자가 다르다.
_DEV_SERVER_PID = _LOCK_DIR / '.dev_server.pid'


def _is_process_alive(pid: int) -> bool:
    """주어진 PID의 프로세스가 아직 실행 중인지 확인합니다 (Windows/Unix 호환).

    [2026-03-18 T3 코드리뷰 반영] 5개 버그/리스크 수정:
    - BUG#1: Unix PermissionError → True 반환 (살아있는 프로세스임)
    - BUG#2: Windows OpenProcess 실패 시 GetLastError로 접근거부 구분
    - BUG#3: ctypes restype 설정 → 64bit 핸들 절삭 방지
    """
    if pid <= 0:
        return False
    try:
        if os.name == 'nt':
            import ctypes
            import ctypes.wintypes
            kernel32 = ctypes.windll.kernel32
            # [BUG#3 수정] restype 설정 — 64bit Windows에서 핸들 포인터 절삭 방지
            kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
            kernel32.OpenProcess.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
            # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            # [BUG#2 수정] GetLastError로 "접근 거부"(=프로세스 존재) vs "프로세스 없음" 구분
            # ERROR_ACCESS_DENIED = 5 → 프로세스는 살아있지만 권한 부족
            # ERROR_INVALID_PARAMETER = 87 → PID가 존재하지 않음
            error_code = ctypes.get_last_error() or kernel32.GetLastError()
            if error_code == 5:  # ERROR_ACCESS_DENIED → 프로세스 존재함
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except PermissionError:
        # [BUG#1 수정] PermissionError = 프로세스가 살아있지만 권한 부족 → True
        return True
    except OSError:
        # OSError (ESRCH 등) = 프로세스가 존재하지 않음
        return False


def _read_pid_file(pid_path: Path) -> tuple[int, float]:
    """PID 파일에서 PID와 기록 시각을 읽어 반환합니다.

    [RISK#4 수정] PID 재사용 방지를 위해 기록 시각도 함께 저장/반환.
    PID 파일 형식: "PID TIMESTAMP" (예: "12345 1710777600.0")
    하위 호환: 숫자만 있으면 시각=0으로 처리.
    """
    try:
        if pid_path.exists():
            parts = pid_path.read_text().strip().split()
            pid = int(parts[0]) if parts and parts[0].isdigit() else 0
            ts = float(parts[1]) if len(parts) > 1 else 0.0
            return pid, ts
    except Exception:
        pass
    return 0, 0.0


def _write_pid_file(pid_path: Path, pid: int) -> None:
    """PID 파일에 PID와 현재 시각을 기록합니다."""
    try:
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(f"{pid} {time.time()}")
    except Exception:
        pass


# [RISK#5 수정] 파일 기반 간이 락 — 동시 훅 호출 시 레이스 컨디션 방지
def _try_lock(pid_path: Path, timeout: float = 2.0) -> bool:
    """PID 파일에 대한 간이 파일 락을 시도합니다.
    .lock 파일을 생성하여 동시 접근을 방지합니다.
    """
    lock_path = pid_path.with_suffix('.lock')
    start = time.time()
    while time.time() - start < timeout:
        try:
            # O_CREAT | O_EXCL → 파일이 이미 있으면 실패 (원자적)
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            # 락 파일이 10초 이상 오래되었으면 stale로 간주하고 삭제
            try:
                if lock_path.exists() and time.time() - lock_path.stat().st_mtime > 10:
                    lock_path.unlink()
            except Exception:
                pass
            time.sleep(0.1)
        except Exception:
            return False
    return False


def _release_lock(pid_path: Path) -> None:
    """간이 파일 락을 해제합니다."""
    lock_path = pid_path.with_suffix('.lock')
    try:
        if lock_path.exists():
            lock_path.unlink()
    except Exception:
        pass


# [RISK#4 수정] PID 재사용 방지 — 최대 유효 시간 (초)
_PID_MAX_AGE = 3600  # 1시간 이상 된 PID 파일은 stale로 간주


def _is_app_server_running() -> bool:
    """앱(GUI)이 직접 띄운 서버가 살아있는지 — **읽기 전용** 판정.

    [WHY 별도 함수] _is_already_running을 쓰면 안 된다. 그쪽은 stale 판정 시 PID 파일을
    unlink 하고 .lock 파일을 만드는데, .dev_server.pid의 소유자는 훅이 아니라 server.py다.
    남의 상태 파일을 훅이 지우면 앱 쪽 판정이 깨진다 — 여기서는 읽기만 한다.

    [형식] server.py는 PID만("4324"), 훅은 "PID 타임스탬프"로 쓴다 → 첫 토큰만 취한다.
    """
    try:
        raw = _DEV_SERVER_PID.read_text(encoding='utf-8').strip().split()
        return bool(raw) and _is_process_alive(int(raw[0]))
    except Exception:
        return False


def _is_already_running(pid_path: Path) -> bool:
    """PID 파일을 확인하여 해당 프로세스가 이미 실행 중인지 판별합니다.

    [개선 사항]
    - 파일 락으로 동시 호출 시 레이스 컨디션 방지 (RISK#5)
    - PID 기록 시각 확인으로 PID 재사용 감지 (RISK#4)
    """
    # [RISK#5] 파일 락 획득
    if not _try_lock(pid_path):
        # 락 획득 실패 → 다른 훅이 이미 처리 중 → 중복 생성 차단
        return True

    try:
        pid, ts = _read_pid_file(pid_path)
        if pid and _is_process_alive(pid):
            # [RISK#4] PID 재사용 감지: 기록 시각이 너무 오래되면 stale
            if ts > 0 and (time.time() - ts) > _PID_MAX_AGE:
                # 1시간 이상 → PID가 재사용됐을 가능성 높음 → stale 처리
                try:
                    pid_path.unlink()
                except Exception:
                    pass
                return False
            return True
        # PID 파일이 stale하면 삭제
        try:
            if pid_path.exists():
                pid_path.unlink()
        except Exception:
            pass
        return False
    finally:
        _release_lock(pid_path)


# --- 무시할 접두사 (무한루프 방지) ---
SKIP_PREFIXES = ['[지시]', '[오류]', '[완료]', '[INFO]', '[OK]', '[🤖', 'python ', 'git ']

# --- 무시할 키워드 (메타 명령어) ---
SKIP_KEYWORDS = ['/commit', '/review', '/plan', '/help', '/clear']


def _notify(msg: str) -> None:
    """Claude Code context에 상태 메시지 출력.
    훅의 stdout은 Claude가 system-reminder로 읽으므로 Claude 응답에 반영됨.
    """
    print(msg, flush=True)


def _call_api(prompt: str, cwd: str = '', project_id: str = '') -> dict | None:
    """서버 HTTP API로 에이전트 실행 요청 전송.
    반환: dict(서버 응답) 또는 None(서버 미실행)

    [불변식] cwd/project_id 필수 전달 — 누락 시 서버가 자기 _PROJECT_ROOT에서
    실행해 다른 프로젝트 지시가 vibe-coding을 오염시킴 (2026-07-15 사고).
    """
    # [과거사고 2026-07-16] 포트도 프로젝트 대조 — payload 꼬리표(c95b2ec)만으로는
    # 타 프로젝트 서버에 도착하는 것 자체를 못 막았음. 자기 서버 없으면 None 반환
    # → 호출부가 '서버 미실행' 경로(자동 시작→재시도)로 처리.
    port = _server_port_for(project_id)
    if port is None:
        return None

    payload = json.dumps({
        'task': prompt,
        'cli': 'auto',
        'terminal_id': TERMINAL_ID,
        'cwd': cwd,
        'project_id': project_id,
        'source': 'hook',
    }).encode('utf-8')

    req = urllib_request.Request(
        f'http://127.0.0.1:{port}/api/agent/run',
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


def _is_server_alive(project_id: str = '') -> bool:
    """서버 헬스체크. project_id 전달 시 그 프로젝트의 서버가 살아있는지 판정.

    [과거사고 2026-07-16] 첫 응답 포트(HEALTH_URL) 판정은 타 프로젝트 서버만 살아있어도
    True — _start_server 대기 루프가 자기 서버 기동 전에 조기 탈출하던 구멍.
    """
    if project_id:
        return _server_port_for(project_id) is not None
    try:
        with urllib_request.urlopen(HEALTH_URL, timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def _start_server(project_id: str = '') -> bool:
    """서버가 꺼져있으면 백그라운드로 자동 시작합니다.

    [중복 방지] PID 파일(_SERVER_PID)로 이미 실행 중인 서버가 있으면 새로 생성하지 않음.
    최대 5초 대기 후 서버가 응답하면 True 반환.
    서버 프로세스는 현재 터미널 세션과 독립적으로 유지됩니다.
    """
    if not SERVER_PY.exists():
        return False

    # [과거사고 2026-07-25] 아래 PID 파일 판정은 '훅이 띄운 서버'(.server.pid)만 안다.
    # 사용자가 앱으로 직접 띄운 서버는 .dev_server.pid에 기록되므로, 9000에 멀쩡히
    # 응답하는 서버가 있어도 '없음'으로 보고 매 메시지마다 server.py를 새로 스폰했다.
    # 새 인스턴스는 단일 인스턴스 락에 걸려 즉시 os._exit 하지만, 그 직전 기존 창을
    # ShowWindow(SW_RESTORE)로 포커스해 사용자의 최대화 창을 축소시켰다(instance_lock.py
    # 동일 날짜 수정 참조). PID 파일보다 '실제 응답하는 서버가 있는가'가 상위 진실이다.
    if _is_server_alive(project_id):
        return True

    # [과거사고 2026-08-02 — 터미널 통째 사망] 위 _is_server_alive는 /api/project-info의
    # **활성 프로젝트 슬러그**로 대조한다. 그래서 앱이 다른 프로젝트(예: D:/ons)를 열어둔
    # 상태에서 vibe-coding 폴더의 Claude Code가 메시지를 보내면 '내 서버 없음'으로 판정된다.
    # 그런데 단일 인스턴스 락은 project_root 시드 해시라(instance_lock.py) 슬러그가 다르면
    # **락에 걸리지 않고 2번째 인스턴스가 끝까지 부팅**한다 — 자체 PTY 서버를 띄우고 9000번대
    # 포트 슬롯을 경쟁하다가, 한쪽이 닫힐 때 살아있는 터미널 세션이 전부 죽었다.
    # (동일 경쟁의 선례가 instance_lock.py _server_port_slot_base 주석의 2026-07-22 사고.)
    #
    # [불변식] 앱 프로세스가 살아있는 동안 훅은 server.py를 절대 스폰하지 않는다. 앱이 이미
    # 있는데 헤드리스 서버를 하나 더 띄워야 하는 상황은 존재하지 않는다 — 서버가 남의
    # 프로젝트를 보고 있다면 그건 '스폰'이 아니라 '이 프로젝트로는 API를 안 쓴다'가 정답이라,
    # False를 반환해 호출부의 fallback(cli_agent 직접 실행) 경로로 보낸다. 교차 오염도 없다.
    if _is_app_server_running():
        return False

    # [2026-03-18] PID 파일 기반 중복 방지 — 이미 서버가 실행 중이면 스킵
    if _is_already_running(_SERVER_PID):
        # 서버 프로세스는 살아있지만 아직 HTTP 응답이 안 될 수 있음 → 대기
        import time
        for _ in range(10):
            time.sleep(0.5)
            if _is_server_alive(project_id):
                return True
        return False

    # Windows: 새 콘솔 없이 백그라운드 실행
    creationflags = 0
    if os.name == 'nt':
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS

    try:
        proc = subprocess.Popen(
            [sys.executable, str(SERVER_PY)],
            cwd=str(CWD),
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, 'VIBE_AGENT_MODE': '1'},
        )
        # PID 기록 — 다음 훅 호출 시 중복 생성 방지
        _write_pid_file(_SERVER_PID, proc.pid)
    except Exception:
        return False

    # 최대 5초 대기 (0.5초 간격 × 10회)
    import time
    for _ in range(10):
        time.sleep(0.5)
        if _is_server_alive(project_id):
            return True

    return False


def _fallback_subprocess(prompt: str, working_dir: str = '') -> None:
    """서버 완전 오프라인 시 cli_agent.py를 백그라운드로 실행 (창 점유 없음).

    [중복 방지] PID 파일(_AGENT_PID)로 이미 에이전트가 실행 중이면 새로 생성하지 않음.
    서버가 정상 동작하면 이 함수는 호출되지 않음.
    결과는 agent_runs.jsonl / agent_live.jsonl에 저장됨.
    working_dir: 호출 프로젝트 루트 — 미전달 시 cli_agent가 vibe-coding으로 폴백(교차 간섭).
    """
    # [2026-03-18] PID 파일 기반 중복 방지 — 이미 에이전트가 실행 중이면 스킵
    if _is_already_running(_AGENT_PID):
        _notify(f'[🤖 {TERMINAL_ID}] 에이전트 이미 실행 중 — 중복 생성 차단됨')
        return

    creationflags = 0
    if os.name == 'nt':
        creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS

    proc = subprocess.Popen(
        [sys.executable, str(CLI_AGENT), prompt, 'auto'] + ([working_dir] if working_dir else []),
        cwd=str(CWD),
        creationflags=creationflags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, 'VIBE_CHILD_AGENT': '1'},
    )
    # PID 기록 — 다음 훅 호출 시 중복 생성 방지
    _write_pid_file(_AGENT_PID, proc.pid)


def _ensure_postgres() -> None:
    """PostgreSQL이 미실행 중이면 백그라운드로 자동 시작합니다.

    [설계 의도]
    프로그램 실행 시(UserPromptSubmit 훅) PostgreSQL이 자동으로 켜지도록 합니다.
    사용자가 수동으로 DB를 시작할 필요 없습니다.
    서버(server.py) 기동 여부와 무관하게 DB는 항상 실행 상태를 유지합니다.

    [변경 이력] 2026-03-08 Claude: ITCP 도입에 따라 PostgreSQL 자동 시작 로직 추가
    """
    try:
        import urllib.request as _ur
        # psql.exe 헬스체크 (가장 빠른 방법)
        _pg_bin = CWD / ".ai_monitor" / "bin" / "pgsql" / "bin" / "psql.exe"
        if not _pg_bin.exists():
            return
        no_window = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run(
            [str(_pg_bin), "-p", str(os.environ.get('VIBE_PG_PORT', '5433')), "-U", "postgres", "-d", "postgres",
             "-c", "SELECT 1;", "--tuples-only"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=2, creationflags=no_window,
        )
        if result.returncode == 0:
            return  # 이미 실행 중

        # pg_manager.py로 백그라운드 시작 (PID 락으로 중복 방지)
        _pg_pid_file = _LOCK_DIR / '.postgres.pid'
        if _is_already_running(_pg_pid_file):
            return  # 이미 pg_manager가 실행 중
        pg_manager = SCRIPT_DIR / "pg_manager.py"
        if pg_manager.exists():
            pg_proc = subprocess.Popen(
                [sys.executable, str(pg_manager), "start"],
                cwd=str(CWD),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS if os.name == 'nt' else 0,
            )
            _write_pid_file(_pg_pid_file, pg_proc.pid)
    except Exception:
        pass


def main():
    # 오피스 세션(OFFICE_MODE=true)에서는 hook 비활성화 — 대화형 세션이므로 hook 불필요
    if os.environ.get('OFFICE_MODE') == 'true':
        sys.exit(0)

    # 캐스케이드 루프 방지: cli_agent.py가 spawn한 자식 프로세스(VIBE_CHILD_AGENT=1)는 즉시 종료.
    if os.environ.get('VIBE_CHILD_AGENT'):
        sys.exit(0)

    # PostgreSQL 자동 시작 (ITCP 통신 인프라 보장)
    # 서버(server.py)와 무관하게 DB는 항상 실행 상태를 유지해야 합니다
    _ensure_postgres()

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

    # 호출 프로젝트 식별 — 지시에 프로젝트 꼬리표(cwd/project_id)를 반드시 붙인다
    caller_root, caller_pid = _resolve_caller_project(data)

    # 1순위: 서버 HTTP API 호출 (대시보드 SSE 연동)
    result = _call_api(prompt, cwd=caller_root, project_id=caller_pid)

    if result is not None:
        # ── 서버 연결 성공 ──────────────────────────────────────────────
        if result.get('error') == 'already_running':
            current = result.get('current', {})
            current_task = current.get('task', '')[:40]
            current_pid = (current.get('project_id') or '').strip()
            if current_pid and caller_pid and current_pid != caller_pid:
                # 다른 프로젝트의 실행이 점유 중 — 이 프로젝트 일이 아님을 명시해 혼동 차단
                _notify(f'[🤖 {TERMINAL_ID}] 다른 프로젝트({current_pid})의 에이전트가 실행 중이라 이 지시는 대기됩니다.')
            else:
                _notify(f'[🤖 {TERMINAL_ID}] 에이전트 실행 중: "{current_task}..." — 완료 후 자동 처리됩니다.')
        else:
            chosen_cli = result.get('cli', 'auto')
            _notify(f'[🤖 {TERMINAL_ID}→{chosen_cli.upper()}] 자율 에이전트 시작됨: "{short_prompt}"')
    else:
        # ── 앱이 살아있으면 스폰도 폴백도 하지 않고 여기서 끝낸다 (2026-08-02 승인).
        #
        # [WHY] 이 분기는 '서버가 죽었다'가 아니라 '앱이 다른 프로젝트를 열고 있어 이 프로젝트용
        # API가 없다'인 경우가 대부분이다(활성 프로젝트 슬러그 대조 실패). 그 상태에서 폴백을
        # 태우면 cli_agent가 claude.exe를 **또** 띄운다 — 사용자는 이미 이 CLI 세션에서 같은
        # 프롬프트로 대화 중이므로, 한 메시지가 API를 두 번 호출해 쿼터를 이중 소모하고 동시
        # 요청이 겹치면 429/overloaded를 유발한다. 더 위험한 건 그 백그라운드 클로드도 코드를
        # 고칠 수 있다는 것 — 전경 세션과 같은 파일을 동시에 수정할 수 있다.
        #
        # [경계] '앱이 진짜 꺼져 있을 때'의 자율 실행은 이 기능의 본래 목적이므로 그대로 둔다.
        # 끄는 조건은 오직 '앱 프로세스 생존' 하나다.
        if _is_app_server_running():
            _notify(f'[🤖 {TERMINAL_ID}] 앱은 실행 중이나 활성 프로젝트가 달라 자율 에이전트 생략 '
                    f'(중복 실행 방지) — 이 세션에서 직접 처리하세요.')
            sys.exit(0)

        # ── 서버 미실행 → 자동 시작 시도 후 재연결, 실패 시 동기 fallback
        _notify(f'[🤖 {TERMINAL_ID}] 백엔드 오프라인 — 자동 시작 중...')
        server_started = _start_server(caller_pid)

        if server_started:
            # 서버 기동 성공 → API 재호출
            result2 = _call_api(prompt, cwd=caller_root, project_id=caller_pid)
            if result2 is not None:
                chosen_cli = result2.get('cli', 'auto')
                _notify(f'[🤖 {TERMINAL_ID}→{chosen_cli.upper()}] 서버 자동 시작 후 에이전트 시작됨: "{short_prompt}"')
            else:
                _notify(f'[🤖 {TERMINAL_ID}] 서버 시작됐으나 API 호출 실패 — fallback 실행')
                _fallback_subprocess(prompt, working_dir=caller_root)
        else:
            # 서버 시작 실패 → 동기 fallback (결과를 Claude 컨텍스트로 출력)
            _notify(f'[🤖 {TERMINAL_ID}→오프라인] 에이전트 실행 중 (서버 없음): "{short_prompt}"')
            _fallback_subprocess(prompt, working_dir=caller_root)

    # 훅은 0 반환 필수 (non-zero면 Claude가 응답 중단)
    sys.exit(0)


if __name__ == '__main__':
    main()
