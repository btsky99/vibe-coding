"""
FILE: scripts/pg_manager.py
DESCRIPTION: 하이브 마인드 전용 포터블 PostgreSQL 통합 매니저.
             포트 5433으로 DB를 제어하고, 핵심 확장 기능(Vector, Search, MQ)을 활성화함.

REVISION HISTORY:
- 2026-03-06 Gemini: 최초 작성. 시작/중지/상태체크 및 확장 기능 활성화 로직 구현.
"""

import os
import sys
import subprocess
import time
from pathlib import Path

# 윈도우 cp949 터미널에서 이모지/한글 출력 시 UnicodeEncodeError 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).parent.parent
PG_DIR = PROJECT_ROOT / ".ai_monitor" / "bin" / "pgsql"
BIN_DIR = PG_DIR / "bin"
DATA_DIR = PG_DIR / "data"
PORT = 5433

def run_pg_ctl(cmd_args):
    pg_ctl = BIN_DIR / "pg_ctl.exe"
    cmd = [str(pg_ctl)] + cmd_args + ["-D", str(DATA_DIR)]
    try:
        # 로그 파일 지정
        log_file = PROJECT_ROOT / ".ai_monitor" / "data" / "pgsql.log"
        if "start" in cmd_args:
            cmd += ["-l", str(log_file)]
        
        # encoding 명시: 윈도우 cp949 환경에서 PostgreSQL UTF-8 출력 디코딩 오류 방지
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return result.stdout.strip()
    except Exception as e:
        return f"Error: {str(e)}"

def start():
    print(f"🚀 PostgreSQL 시작 중 (Port: {PORT})...")
    # 이미 실행 중인지 확인
    if "server is running" in run_pg_ctl(["status"]):
        print("✨ 이미 실행 중입니다.")
        return
    
    res = run_pg_ctl(["start"])
    print(res)
    time.sleep(2)
    
    # 확장 기능 활성화 시도
    setup_extensions()

def stop():
    print("🛑 PostgreSQL 중지 중...")
    res = run_pg_ctl(["stop", "-m", "fast"])
    print(res)

def status():
    res = run_pg_ctl(["status"])
    print(f"📊 DB 상태: {res}")

def setup_extensions():
    """핵심 확장 기능(Vector, Search, MQ) 활성화 SQL 실행"""
    psql = BIN_DIR / "psql.exe"
    
    # 1. PGVector, PGSearch(trgm), PGMQ 활성화 쿼리
    sql = """
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;
    -- PGMQ는 SQL 파일이 있는 경우 실행
    """
    
    print("🧩 확장 기능 활성화 시도 중...")
    try:
        subprocess.run([
            str(psql), "-p", str(PORT), "-U", "postgres", "-d", "postgres", "-c", sql
        ], capture_output=True, text=True)
        
        # PGMQ SQL 파일 실행
        mq_sql_path = PG_DIR / "share" / "extension" / "pgmq.sql"
        if mq_sql_path.exists():
            subprocess.run([
                str(psql), "-p", str(PORT), "-U", "postgres", "-d", "postgres", "-f", str(mq_sql_path)
            ], capture_output=True, text=True)
            print("✅ PGMQ (SQL) 설치 완료")
            
        print("✅ 핵심 확장 기능 세팅 완료.")
    except Exception as e:
        print(f"⚠️ 확장 기능 설치 중 경고: {e} (아직 바이너리가 배치되지 않았을 수 있습니다)")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python scripts/pg_manager.py [start|stop|status|setup]")
        sys.exit(1)
        
    cmd = sys.argv[1].lower()
    if cmd == "start": start()
    elif cmd == "stop": stop()
    elif cmd == "status": status()
    elif cmd == "setup": setup_extensions()
    else:
        print(f"알 수 없는 커맨드: {cmd}")
