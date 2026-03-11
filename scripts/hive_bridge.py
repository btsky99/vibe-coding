# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------
# 📄 파일명: scripts/hive_bridge.py
# 📝 설명: PostgreSQL 18 기반 하이브 마인드 통합 로깅 및 협업 브릿지. (Postgres-First)
#          기존의 JSONL 및 SQLite 레거시를 대체합니다.
#
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

def _run_psql(sql: str) -> str:
    """psql.exe를 직접 호출하여 SQL을 실행하고 stdout을 반환합니다 (서버 미가동 시 폴백).

    Returns:
        str: psql stdout 출력 (RETURNING id 파싱 등에 활용), 실패 시 빈 문자열
    """
    if not os.path.exists(PG_BIN):
        return ''
    try:
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        res = subprocess.run(
            [PG_BIN, "-p", "5433", "-U", "postgres", "-d", "postgres", "-c", sql],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=_no_window
        )
        return res.stdout or ''
    except Exception:
        return ''

def log_task(agent_name, task_summary, terminal_id=None, status="success"):
    """작업 로그를 PostgreSQL에 기록합니다."""
    _tid = terminal_id or os.environ.get('TERMINAL_ID', 'T0')
    data = {
        "agent": agent_name,
        "terminal_id": _tid,
        "task": task_summary,
        "status": status
    }
    
    # 1. 서버 API 호출 시도
    if _call_api('/api/hive/log/pg', data):
        print(f"[POSTGRES] Task logged via API: {task_summary[:50]}...")
        return

    # 2. 서버 미가동 시 psql 직접 호출 폴백
    safe_task = task_summary.replace("'", "''")
    sql = f"INSERT INTO pg_logs (agent, terminal_id, task, status) VALUES ('{agent_name}', '{_tid}', '{safe_task}', '{status}');"
    if _run_psql(sql):
        print(f"[POSTGRES] Task logged via PSQL: {task_summary[:50]}...")
    else:
        print(f"[ERROR] Failed to log task to Postgres.")

def log_thought(agent_name: str, skill: str, thought_dict: dict,
                parent_id: int = None) -> int:
    """AI의 사고 과정을 PostgreSQL에 기록합니다 (JSONB).

    parent_id를 전달하면 지식 그래프에서 이전 thought와 연결선이 생성됩니다.
    삽입 완료 후 새로 생성된 thought id를 _LAST_THOUGHT_ID[agent_name]에 저장합니다.

    Returns:
        int: 삽입된 thought의 id, 실패 시 0
    """
    data = {
        "agent": agent_name,
        "skill": skill,
        "thought": thought_dict,
    }
    if parent_id:
        data["parent_id"] = int(parent_id)

    # 1. 서버 API 우선 호출 — 응답 body에서 id 파싱
    try:
        req = __import__('urllib.request', fromlist=['Request']).Request(
            f"{SERVER_URL}/api/hive/thought/pg",
            data=json.dumps(data, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        import urllib.request as _ur
        with _ur.urlopen(req, timeout=2) as res:
            if res.status == 200:
                body = json.loads(res.read().decode('utf-8'))
                new_id = int(body.get('id', 0))
                if new_id:
                    _LAST_THOUGHT_ID[agent_name] = new_id
                return new_id
    except Exception:
        pass

    # 2. 서버 미가동 시 psql 직접 호출 폴백
    safe_thought = json.dumps(thought_dict, ensure_ascii=False).replace("'", "''")
    if parent_id:
        sql = (f"INSERT INTO pg_thoughts (agent, skill, thought, parent_id) "
               f"VALUES ('{agent_name}', '{skill}', '{safe_thought}'::jsonb, {int(parent_id)}) RETURNING id;")
    else:
        sql = (f"INSERT INTO pg_thoughts (agent, skill, thought) "
               f"VALUES ('{agent_name}', '{skill}', '{safe_thought}'::jsonb) RETURNING id;")
    output = _run_psql(sql)
    # RETURNING id 파싱 (psql 기본 출력: " id\n----\n 42\n(1 row)")
    for line in output.splitlines():
        line = line.strip()
        if line.isdigit():
            new_id = int(line)
            _LAST_THOUGHT_ID[agent_name] = new_id
            return new_id
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
    """작업 완료 후 자기반성(self-reflect) 내용을 pg_thoughts에 기록합니다.

    에이전트가 매 작업 후 무엇을 배웠고 무엇이 실패했는지 구조화하여 저장합니다.
    다음 유사 작업 시 컨텍스트로 자동 주입됩니다 (UserPromptSubmit 훅 연동).

    Args:
        agent_name:    기록 주체 에이전트 이름 (예: "claude", "gemini")
        task_summary:  완료된 작업 요약 (지시 내용 앞 50자)
        learned:       잘 된 것 / 배운 점 목록 (예: ["pg_logs 쿼리 패턴 확인"])
        failed:        실패하거나 막혔던 점 목록 (예: ["psql CSV 출력 파싱 오류"])
        files_changed: 수정된 파일 경로 목록
        terminal_id:   터미널 ID (없으면 환경변수 TERMINAL_ID 사용)
    """
    _tid = terminal_id or os.environ.get('TERMINAL_ID', 'T0')
    thought_dict = {
        "type": "reflect",
        "title": task_summary[:60],   # 지식 그래프 레이블용 title 추가
        "task": task_summary[:100],
        "learned": learned,
        "failed": failed,
        "files": files_changed,
        "terminal": _tid
    }
    # 동일 에이전트의 직전 thought를 parent로 연결 → 지식 그래프에 연결선 생성
    _prev_id = _LAST_THOUGHT_ID.get(agent_name)
    log_thought(agent_name, "self-reflect", thought_dict, parent_id=_prev_id)

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
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        res = subprocess.run(
            [PG_BIN, "-p", "5433", "-U", "postgres", "-d", "postgres", "-c", sql, "--csv"],
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
