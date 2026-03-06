# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------
# 📄 파일명: scripts/hive_bridge.py
# 📝 설명: PostgreSQL 18 기반 하이브 마인드 통합 로깅 및 협업 브릿지. (Postgres-First)
#          기존의 JSONL 및 SQLite 레거시를 대체합니다.
#
# 🕒 변경 이력 (History):
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
SERVER_URL = "http://localhost:9571"
PG_BIN = os.path.join(PROJECT_ROOT, ".ai_monitor", "bin", "pgsql", "bin", "psql.exe")

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

def _run_psql(sql: str) -> bool:
    """psql.exe를 직접 호출하여 SQL을 실행합니다 (서버 미가동 시 폴백)."""
    if not os.path.exists(PG_BIN):
        return False
    try:
        _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
        subprocess.run(
            [PG_BIN, "-p", "5433", "-U", "postgres", "-d", "postgres", "-c", sql],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=_no_window
        )
        return True
    except Exception:
        return False

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

def log_thought(agent_name, skill, thought_dict):
    """AI의 사고 과정을 PostgreSQL에 기록합니다 (JSONB)."""
    data = {
        "agent": agent_name,
        "skill": skill,
        "thought": thought_dict
    }
    
    if _call_api('/api/hive/thought/pg', data):
        return

    # 폴백
    safe_thought = json.dumps(thought_dict, ensure_ascii=False).replace("'", "''")
    sql = f"INSERT INTO pg_thoughts (agent, skill, thought) VALUES ('{agent_name}', '{skill}', '{safe_thought}'::jsonb);"
    _run_psql(sql)

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
        "task": task_summary[:100],
        "learned": learned,
        "failed": failed,
        "files": files_changed,
        "terminal": _tid
    }
    log_thought(agent_name, "self-reflect", thought_dict)

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
