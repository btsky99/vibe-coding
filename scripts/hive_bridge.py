# -*- coding: utf-8 -*-
"""
FILE: scripts/hive_bridge.py
DESCRIPTION: PostgreSQL 18 기반 하이브 마인드 통합 로깅 및 협업 브릿지 (Postgres-First).

REVISION HISTORY:
- 2026-03-19 Claude: 표준 헤더 형식 적용 (RULES.md 섹션 2 준수)
"""
# 🕒 변경 이력 (History):
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
SERVER_URL = "http://localhost:9000"
PG_BIN = os.path.join(PROJECT_ROOT, ".ai_monitor", "bin", "pgsql", "bin", "psql.exe")
PG_PORT = os.environ.get('VIBE_PG_PORT', '5433')
PG_DB = resolve_project_db(PROJECT_ROOT)

# 에이전트별 마지막 삽입된 thought id — reflect_to_pg parent_id 체인에 사용
# (프로세스 수명 동안 인메모리 유지, 재시작 시 리셋됨)
_LAST_THOUGHT_ID: dict = {}

def _call_api(path: str, data: dict) -> bool:
    """server.py API를 호출합니다."""
    try:
        req = urllib.request.Request(
            f"{SERVER_URL}{path}",
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
        res = subprocess.run(
            [PG_BIN, "-p", str(PG_PORT), "-U", "postgres", "-d", PG_DB, "-c", sql],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=_no_window
        )
        return res.stdout or ''
    except Exception:
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
    # [2026-03-22] print → sys.stderr로 변경: Gemini CLI가 stdout을 JSON-RPC 통신에
    # 사용하므로, print가 stdout에 출력되면 function call/response 쌍이 깨져
    # "number of function response parts" 에러가 발생함.
    import sys as _sys
    _log = _sys.stderr.write
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
