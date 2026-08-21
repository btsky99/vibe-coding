# -*- coding: utf-8 -*-
"""
FILE: scripts/hive_bridge.py
DESCRIPTION: PostgreSQL 18 기반 하이브 마인드 통합 로깅 및 협업 브릿지 (Postgres-First).

REVISION HISTORY:
- 2026-03-19 Claude: 표준 헤더 형식 적용 (RULES.md 섹션 2 준수)
"""
# 🕒 변경 이력 (History):
# [2026-08-19] - Claude (로깅 실패가 도구 실행을 막던 것)
#   - log_task 의 stderr 잡담 3줄을 파일 진단(_diag)으로 옮김. 원인·재현은 _diag 주석 참조.
# [2026-03-11] - Claude (지식 그래프 연결선 수정)
#   - log_thought: parent_id 파라미터 추가 → API/psql 양쪽 경로에 parent_id 전달
#   - log_thought: 삽입 완료 후 반환된 id를 _LAST_THOUGHT_ID에 저장
#   - reflect_to_pg: 동일 에이전트 직전 thought id를 parent_id로 전달 → 연결선 생성
# [2026-03-06] - Gemini (Postgres 완전 통합 고도화)
#   - JSONL 파일 기반 로깅 중단 및 PostgreSQL 테이블(pg_logs, pg_thoughts) 전환.
#   - server.py API (/api/hive/log/pg) 우선 호출, 실패 시 psql.exe 직접 호출 폴백.
#   - PGMQ (hive_queue) 연동으로 실시간 메시지 큐 시스템 가동.
# ------------------------------------------------------------------------
import sys
import os
import io
import json
import time
import subprocess
import socket
from datetime import datetime
import urllib.request

try:
    from pg_project import resolve_project_db
except ImportError:
    from scripts.pg_project import resolve_project_db

# Windows 터미널(CP949 등)에서 이모지/한글 출력 시 UnicodeEncodeError 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# 프로젝트 루트 및 서버 정보 설정
PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
# [제약] src.server_locator 는 sys.path 에 .ai_monitor 가 있어야 import 된다 —
# 호출자가 각자 보장하는 규약이다(server_locator.py:67-69).
_MONITOR_DIR = os.path.join(PROJECT_ROOT, '.ai_monitor')
if _MONITOR_DIR not in sys.path:
    sys.path.insert(0, _MONITOR_DIR)
# [2026-08-21] 9000 고정을 걷어냈다. 이 상수는 이제 **탐색 실패 시의 폴백**일 뿐이다.
# [과거사고] 이 "첫 응답/9000 고정" 패턴은 2026-07-16 에 이미 한 번 청산 대상이었다
#   (사고 장부 beccc5662a4961bf). 그때 hook_bridge·hive_hook·agent_shell·terminal_agent 는
#   src/server_locator.py 로 옮겼는데 **이 파일이 누락됐다.** 대가는 서버가 9000 이 아닌
#   포트로 떠 있을 때 log_task 기록이 조용히 유실되는 것 — 느려지지도 않아 더 안 보인다.
# [WHY 127.0.0.1] localhost 는 IPv6(::1) 를 먼저 시도하고 실패한 뒤 IPv4 를 다시 시도해
#   닫힌 포트 하나에 timeout 을 두 배로 문다(2초 설정 -> 실측 4초).
SERVER_HOST = "127.0.0.1"
SERVER_URL = f"http://{SERVER_HOST}:9000"   # 폴백 전용 — 실제 주소는 _server_port() 가 정한다

# 훅은 단명 프로세스라 1회 해석 캐시(hive_hook.py:141 과 같은 규약).
# [불변식] None = 아직 안 봤다 / 0 = 봤는데 내 서버가 없다. 0 을 None 과 뭉개면
#   호출마다 다시 스캔해 오히려 느려진다.
# [제약] 장수 프로세스가 이 모듈을 쓰면 0 이 영구히 굳는다 — 그래서 TTL 을 둔다.
_PORT_CACHE: dict = {"port": None, "at": 0.0}
_PORT_TTL = 5.0   # 초. 훅 1회(2.3초)는 덮고, 장수 프로세스는 다시 찾게 한다


def _server_port() -> int:
    """이 프로젝트 서버의 포트. 못 찾으면 0.

    [WHY 슬러그 대조] 첫 응답 포트를 그냥 쓰면 멀티 프로젝트에서 **남의 서버**에
    붙는다 — 서버마다 PG DB 가 달라 요청 파라미터로는 못 고친다(server_locator.py:38-46).
    [불변식] 어떤 실패에서도 예외를 밖으로 던지지 않는다 — 호출자가 전부 훅이다.
    """
    now = time.time()
    if _PORT_CACHE["port"] is not None and (now - _PORT_CACHE["at"]) < _PORT_TTL:
        return _PORT_CACHE["port"]
    port = 0
    try:
        from src.server_locator import find_server_port, slug_for_cwd
        port = find_server_port(project_id=slug_for_cwd(PROJECT_ROOT)) or 0
    except Exception:
        port = 0
    _PORT_CACHE["port"], _PORT_CACHE["at"] = port, now
    return port
PG_BIN = os.path.join(PROJECT_ROOT, ".ai_monitor", "bin", "pgsql", "bin", "psql.exe")
PG_PORT = os.environ.get('VIBE_PG_PORT', '5433')

# 진단 로그 자리 — server.log 옆. PG 가 안 뜬 동안 무슨 일이 있었는지 남는 유일한 자리다.
_DIAG_LOG = os.path.join(PROJECT_ROOT, '.ai_monitor', 'hive_bridge.log')
_DIAG_MAX = 2 * 1024 * 1024        # 2MB 넘으면 처음부터 다시 쓴다(무한 증식 방지)


def _diag(msg: str) -> None:
    """로깅의 성공/실패를 **파일에만** 남긴다. stdout/stderr 에 절대 쓰지 않는다.

    [🔴 과거사고 2026-08-19 — 로그가 안 남는 것이 '작업을 막았다']
      원래 이 세 줄은 stderr 로 나갔다. 그런데 이 모듈은 `scripts/hive_hook.py` 를 통해
      **Claude Code 의 PreToolUse 훅**에서 불린다. 훅이 stderr 에 쓰면 하네스가 그것을
      훅 오류로 읽고 **도구 실행 자체를 차단한다.** 실측(2026-08-19): 훅 종료코드는
      **0** 인데도 `[ERROR] Failed to log task to Postgres.` 한 줄 때문에 `git commit`
      과 heredoc 명령이 막혔다. 재현 조건은 'PG 5433 미가동(앱이 꺼져 있을 때) +
      로깅 경로를 타는 긴 명령' — 짧은 명령은 이 경로를 안 타서 **간헐적으로 보인다.**
      즉 관측 장치가 작업을 막았다. 로깅은 최선노력(best-effort)이고, 그 실패는
      호출자가 알 일이 아니다.

    [🔴 왜 stdout 도 안 되나] Gemini CLI 는 stdout 을 JSON-RPC 로 쓴다 — 여기 뭘 찍으면
      function call/response 쌍이 깨진다(2026-03-22 사고). 그래서 **양쪽 스트림 다 막혔고**
      남는 자리가 파일뿐이다.

    [🔴 왜 조용히 삼키지 않나] 실패를 아무 데도 안 남기면 "왜 로그가 없나" 를 영영 못 푼다.
      스트림이 아니라 파일로 옮긴 이유가 그것이다 — 막지도, 잃지도 않는다.
    """
    try:
        try:
            if os.path.getsize(_DIAG_LOG) > _DIAG_MAX:
                os.remove(_DIAG_LOG)
        except OSError:
            pass
        os.makedirs(os.path.dirname(_DIAG_LOG), exist_ok=True)
        with io.open(_DIAG_LOG, 'a', encoding='utf-8', errors='replace') as fh:
            fh.write('%s %s' % (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), msg))
    except Exception:                                      # noqa: BLE001
        # [불변식] 진단이 실패해도 호출자를 절대 흔들지 않는다 — 그게 이 사고의 교훈이다.
        pass
PG_DB = resolve_project_db(PROJECT_ROOT)

# 에이전트별 마지막 삽입된 thought id — reflect_to_pg parent_id 체인에 사용
# (프로세스 수명 동안 인메모리 유지, 재시작 시 리셋됨)
_LAST_THOUGHT_ID: dict = {}

def _call_api(path: str, data: dict) -> bool:
    """server.py API를 호출합니다."""
    try:
        # [2026-08-21] 서버가 안 떠 있으면 urlopen 을 아예 시도하지 않는다.
        # [WHY] 이 함수는 log_task 를 거쳐 프롬프트 훅뿐 아니라 **도구 호출마다** 불린다
        # (hive_hook.py:783/789/818/831 — 파일 수정·커밋·BLOCKED). 서버가 없을 때
        # 호출 한 번이 timeout 을 통째로 먹어 훅 1회가 14.3초까지 갔다(실측 5회 평균 13.4초).
        # [불변식] bind 가 성공 = 아무도 안 듣는다 = 어차피 실패할 호출이므로 False 는 동일하다.
        # 판정 결과를 바꾸지 않고 대기 시간만 없앤다.
        # [WHY bind 인가] connect_ex 는 못 쓴다 — 윈도우는 닫힌 포트를 거절하지 않고 조용히
        # 버려서 timeout 을 꽉 채운다. bind 는 즉시 답한다. 같은 기법이 이 저장소 3곳에서
        # 이미 쓰인다: hook_bridge.py(e5ef260) · infra/instance_lock.py:261 · src/server_utils.py:25
        _port = _server_port()
        if not _port:
            return False   # 내 프로젝트 서버가 없다 — 남의 서버로 보내지 않는다
        with socket.socket() as _s:
            try:
                _s.bind((SERVER_HOST, _port))
                return False   # 묶였다 = 아무도 안 듣는다 = 그 사이에 내려갔다
            except OSError:
                pass           # 누가 쓰는 중 = 아래에서 실제로 호출해 본다
        req = urllib.request.Request(
            f"http://{SERVER_HOST}:{_port}{path}",
            data=json.dumps(data, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=2) as res:
            return res.status == 200
    except Exception:
        return False

def _run_psql(sql: str, params: tuple = None) -> str:
    """psql.exe를 직접 호출하여 SQL을 실행하고 stdout을 반환합니다 (서버 미가동 시 폴백).

    params를 지정하면 %s placeholder를 수동 이스케이프하여 SQL 인젝션 방지.

    Returns:
        str: psql stdout 출력 (RETURNING id 파싱 등에 활용), 실패 시 빈 문자열
    """
    if params:
        def _pg_escape(v):
            if v is None:
                return 'NULL'
            s = str(v).replace("'", "''")
            return f"'{s}'"
        sql = sql.replace('%s', '{}').format(*[_pg_escape(p) for p in params])
    if not os.path.exists(PG_BIN):
        return ''
    try:
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        # [과거사고 2026-08-21 — 이 폴백은 한글이 든 기록을 100% 흘리고 있었다]
        #   원래는 SQL 을 `-c <sql>` **명령줄 인자**로 넘겼다. 윈도우에서 psql.exe 는
        #   argv 를 ANSI 코드페이지(한국어 윈도우 = CP949)로 받는데 서버는 UTF8 을
        #   기대한다. 그래서 한글이 한 글자라도 들어가면 서버가 이렇게 거부했다:
        #     ERROR: invalid byte sequence for encoding "UTF8": 0xc1 0xf8
        #     (0xc1 0xf8 = CP949 의 '진')
        #   훅 기록은 거의 전부 한글이다([명령 실행]·[커밋 시작]·[수정 시작]...).
        #   실측: hive_bridge.log 에 'via PSQL' 성공 0건 / 실패 1,878건,
        #   pg_logs 는 2026-08-18 이후 사실상 0행. 서버가 떠 있을 땐 API 경로가
        #   가려 줘서 안 보였고, 서버가 안 뜨자 로깅이 통째로 죽었다.
        # [고침] SQL 을 stdin 으로 UTF-8 바이트 그대로 넣는다 — argv 를 안 거치니
        #   코드페이지와 무관하다. PGCLIENTENCODING 으로 서버에 인코딩을 명시한다.
        # [불변식] text=True 를 쓰면 안 된다 — 파이썬이 stdin 을 로캘로 인코딩해
        #   같은 사고가 되살아난다. 바이트로 넣고 바이트로 받아 우리가 디코딩한다.
        _env = dict(os.environ)
        _env['PGCLIENTENCODING'] = 'UTF8'
        res = subprocess.run(
            [PG_BIN, "-p", str(PG_PORT), "-U", "postgres", "-d", PG_DB,
             "-v", "ON_ERROR_STOP=1", "-q"],
            input=sql.encode('utf-8'),
            capture_output=True, timeout=10,
            creationflags=_no_window, env=_env,
        )
        _out = (res.stdout or b'').decode('utf-8', 'replace')
        if res.returncode != 0:
            # [WHY 남기나] 예전엔 실패 이유가 어디에도 안 남아 "왜 로그가 없나" 를
            #   오래 못 풀었다. 스트림은 막혀 있으니(_diag docstring) 파일로 남긴다.
            _err = (res.stderr or b'').decode('utf-8', 'replace').strip()
            _diag("[ERROR] psql rc=" + str(res.returncode) + ": " + _err[:300] + chr(10))
            return ''
        # [주의] -q 는 'INSERT 0 1' 같은 명령 태그를 지운다 — 성공해도 stdout 이 빌 수 있다.
        #   호출자는 반환값의 참/거짓으로 성공을 판정하므로 빈 문자열을 주면 안 된다.
        return _out if _out.strip() else 'OK'
    except Exception as _e:
        try:
            _diag("[ERROR] psql 호출 실패: " + type(_e).__name__ + ": " + str(_e)[:200] + chr(10))
        except Exception:
            pass
        return ''

# [크로스 프로젝트 경계 — 유일 관문] 훅이 stdin cwd로 해석한 '호출 세션의 project_id'.
# 훅은 이벤트당 단명 프로세스(단일 스레드)라 모듈 전역 1회 세팅이 안전 —
# hive_hook.main()이 진입 즉시 set_caller_project(_caller_pid)로 주입한다.
# [과거사고] f1c0d4b가 세션 함수(update_session_files 등)만 _caller_pid를 넘기게 고치고
#   log_task는 통째로 빠뜨려, 외부 프로젝트(예: ons) 편집/명령 로그가 계속 서버 자기
#   PROJECT_ID(=vibe-coding)로 도장 → 회상/하이브 컨텍스트 오염이 재발했다. 이 전역이
#   그 관문. None이면 서버가 자기 PROJECT_ID로 폴백(단일 프로젝트 실행 시 기존 동작 불변).
_CALLER_PROJECT_ID = None

def set_caller_project(project_id):
    """호출 세션의 project_id 슬러그를 모듈 전역에 주입 — 이후 모든 log_task가 상속."""
    global _CALLER_PROJECT_ID
    _CALLER_PROJECT_ID = project_id or None

def log_task(agent_name, task_summary, terminal_id=None, status="success", project_id=None):
    """작업 로그를 PostgreSQL에 기록합니다.

    project_id 미지정 시 set_caller_project로 주입된 호출 프로젝트를 사용한다. 지정·주입
    모두 없으면(None) 서버가 자기 PROJECT_ID로 도장 — 크로스 프로젝트 오염 방지의 관문."""
    _tid = terminal_id or os.environ.get('TERMINAL_ID', 'T0')
    _pid = project_id or _CALLER_PROJECT_ID
    data = {
        "agent": agent_name,
        "terminal_id": _tid,
        "task": task_summary,
        "status": status
    }
    if _pid:
        data["project_id"] = _pid

    # 1. 서버 API 호출 시도
    # [2026-03-22] print → stderr 로 옮김: Gemini CLI 가 stdout 을 JSON-RPC 로 써서
    #   여기 찍으면 function call/response 쌍이 깨진다.
    # [2026-08-19] stderr → **파일**(_diag)로 다시 옮김: Claude Code 훅에서 stderr 에 쓰면
    #   하네스가 훅 오류로 읽어 **도구 실행을 차단**했다. 양쪽 스트림이 다 막혀 파일만 남는다.
    #   자세한 근거·재현은 `_diag` docstring.
    _log = _diag
    if _call_api('/api/hive/log/pg', data):
        _log(f"[POSTGRES] Task logged via API: {task_summary[:50]}...\n")
        return

    # 2. 서버 미가동 시 psql 직접 호출 폴백 — parameterized query로 인젝션 방지.
    # [주의] _pid None일 땐 project_id 컬럼을 아예 빼서 DB 기본값에 맡긴다 — 명시적 NULL을
    #   넣으면 컬럼 DEFAULT를 덮어써버리므로(폴백 경로에서만 형식이 갈림).
    if _pid:
        _ok = _run_psql(
            "INSERT INTO pg_logs (agent, terminal_id, task, status, project_id) VALUES (%s, %s, %s, %s, %s);",
            (agent_name, _tid, task_summary, status, _pid)
        )
    else:
        _ok = _run_psql(
            "INSERT INTO pg_logs (agent, terminal_id, task, status) VALUES (%s, %s, %s, %s);",
            (agent_name, _tid, task_summary, status)
        )
    if _ok:
        _log(f"[POSTGRES] Task logged via PSQL: {task_summary[:50]}...\n")
    else:
        _log(f"[ERROR] Failed to log task to Postgres.\n")

def log_thought(agent_name: str, skill: str, thought_dict: dict,
                parent_id: int = None) -> int:
    """[2026-03-22] 지식그래프 제거됨 — 호출부 호환을 위해 no-op 스텁 유지."""
    return 0

def post_message(from_agent, to_agent, content, msg_type="info"):
    """에이전트 간 메시지를 PostgreSQL에 기록합니다."""
    # API 기반 메시지 전송 (서버 내에서 pg_messages 및 PGMQ 처리)
    _call_api('/api/message', {
        "from": from_agent,
        "to": to_agent,
        "content": content,
        "type": msg_type
    })

def reflect_to_pg(agent_name: str, task_summary: str, learned: list, failed: list,
                  files_changed: list, terminal_id: str = None):
    """[2026-03-22] 지식그래프 제거됨 — 호출부 호환을 위해 no-op 스텁 유지."""
    pass

def get_active_debate_context():
    """현재 진행 중인(open/debating) 토론이 있다면 그 내용과 메시지들을 가져옵니다."""
    sql = """
    SELECT d.id, d.topic, d.status, d.participants,
           (SELECT json_agg(m.*) FROM (
               SELECT agent, type, content, round FROM hive_debate_messages 
               WHERE debate_id = d.id ORDER BY created_at ASC
           ) m) as messages
    FROM hive_debates d
    WHERE d.status IN ('open', 'debating')
    ORDER BY d.id DESC LIMIT 1;
    """
    # psql을 사용하여 결과 가져오기 (CSV 포맷)
    if not os.path.exists(PG_BIN):
        return None
    try:
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        res = subprocess.run(
            [PG_BIN, "-p", str(PG_PORT), "-U", "postgres", "-d", "postgres", "-c", sql, "--csv"],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=_no_window
        )
        if res.returncode == 0 and res.stdout.strip():
            # CSV 첫 줄(헤더) 제외하고 데이터 파싱 (간단한 구현)
            lines = res.stdout.strip().split('\n')
            if len(lines) > 1:
                return lines[1] # JSON 결과 반환
        return None
    except Exception:
        return None

# --- LOCK / UNLOCK (Postgres 기반 확장 예정) ---
def lock_file(agent_name, file_path):
    post_message(agent_name, "all", f"[LOCK] {file_path}", "LOCK")

def unlock_file(agent_name, file_path):
    post_message(agent_name, "all", f"[UNLOCK] {file_path}", "UNLOCK")

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        log_task(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python scripts/hive_bridge.py [agent_name] [task_summary]")
