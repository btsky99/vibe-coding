"""
FILE: scripts/pg_manager.py
DESCRIPTION: 하이브 마인드 전용 포터블 PostgreSQL 통합 매니저.
             포트 5433으로 DB를 제어하고, 핵심 확장 기능(Vector, Search, MQ)을 활성화함.

REVISION HISTORY:
- 2026-03-06 Gemini: 최초 작성. 시작/중지/상태체크 및 확장 기능 활성화 로직 구현.
- 2026-03-10 Gemini: Task 17 강화 - pg_logs/pg_thoughts 스키마 통합 및 지식 그래프 기반 마련.
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
    """핵심 확장 기능(Vector, Search, MQ) 및 로그 스키마 활성화 SQL 실행"""
    psql = BIN_DIR / "psql.exe"
    
    # 1. PGVector, PGSearch(trgm), PGMQ 활성화 쿼리
    sql = """
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;
    """
    
    print("🧩 확장 기능 활성화 시도 중...")
    try:
        subprocess.run([
            str(psql), "-p", str(PORT), "-U", "postgres", "-d", "postgres", "-c", sql
        ], capture_output=True, text=True, encoding="utf-8", errors="replace")
        
        # PGMQ SQL 파일 실행
        mq_sql_path = PG_DIR / "share" / "extension" / "pgmq.sql"
        if mq_sql_path.exists():
            subprocess.run([
                str(psql), "-p", str(PORT), "-U", "postgres", "-d", "postgres", "-f", str(mq_sql_path)
            ], capture_output=True, text=True, encoding="utf-8", errors="replace")
            print("✅ PGMQ (SQL) 설치 완료")
            
        # 2. 로그 스키마 및 트리거 초기화
        init_log_schema()
            
        print("✅ 핵심 확장 기능 및 로그 스키마 세팅 완료.")
    except Exception as e:
        print(f"⚠️ 확장 기능 설치 중 경고: {e} (아직 바이너리가 배치되지 않았을 수 있습니다)")

def init_log_schema():
    """로그 저장용 테이블 및 실시간 NOTIFY 트리거 생성"""
    psql = BIN_DIR / "psql.exe"
    
    schema_sql = """
    -- 1. Unified Log Table (pg_logs)
    CREATE TABLE IF NOT EXISTS pg_logs (
        id SERIAL PRIMARY KEY,
        ts TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        agent VARCHAR(50),
        terminal_id VARCHAR(50),
        task TEXT,
        status VARCHAR(20) DEFAULT 'success',
        metadata JSONB
    );

    -- 2. Thought Trace Table (pg_thoughts)
    CREATE TABLE IF NOT EXISTS pg_thoughts (
        id SERIAL PRIMARY KEY,
        ts TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        agent VARCHAR(50),
        skill VARCHAR(100),
        thought JSONB,
        parent_id INTEGER,
        project_id VARCHAR(100)
    );

    -- Migration: Add missing columns if they don't exist
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pg_thoughts' AND column_name='parent_id') THEN
            ALTER TABLE pg_thoughts ADD COLUMN parent_id INTEGER REFERENCES pg_thoughts(id) ON DELETE SET NULL;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pg_thoughts' AND column_name='project_id') THEN
            ALTER TABLE pg_thoughts ADD COLUMN project_id VARCHAR(100);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pg_thoughts' AND column_name='ts') THEN
            -- Renaming if someone named it timestamp
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pg_thoughts' AND column_name='timestamp') THEN
                ALTER TABLE pg_thoughts RENAME COLUMN "timestamp" TO ts;
            ELSE
                ALTER TABLE pg_thoughts ADD COLUMN ts TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;
            END IF;
        END IF;
    END $$;

    CREATE INDEX IF NOT EXISTS idx_thoughts_parent ON pg_thoughts(parent_id);

    -- 3. Agent Messaging Table (pg_messages)
    CREATE TABLE IF NOT EXISTS pg_messages (
        id SERIAL PRIMARY KEY,
        ts TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        from_agent VARCHAR(50),
        to_agent VARCHAR(50),
        msg_type VARCHAR(20) DEFAULT 'info',
        content TEXT,
        is_read BOOLEAN DEFAULT FALSE
    );

    -- 4. Hive Debates Table
    CREATE TABLE IF NOT EXISTS hive_debates (
        id SERIAL PRIMARY KEY,
        topic TEXT NOT NULL,
        status VARCHAR(20) DEFAULT 'open',
        participants JSONB,
        current_round INTEGER DEFAULT 1,
        final_decision TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 5. Hive Debate Messages Table
    CREATE TABLE IF NOT EXISTS hive_debate_messages (
        id SERIAL PRIMARY KEY,
        debate_id INTEGER REFERENCES hive_debates(id) ON DELETE CASCADE,
        round INTEGER NOT NULL,
        agent VARCHAR(50) NOT NULL,
        type VARCHAR(20),
        content TEXT NOT NULL,
        vote_value INTEGER,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 6. NOTIFY function for real-time events
    CREATE OR REPLACE FUNCTION notify_hive_event()
    RETURNS TRIGGER AS $$
    DECLARE
        payload JSON;
    BEGIN
        payload = json_build_object(
            'table', TG_TABLE_NAME,
            'action', TG_OP,
            'data', row_to_json(NEW)
        );
        PERFORM pg_notify('hive_log_channel', payload::text);
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    -- 7. Trigger Setup
    DO $$
    BEGIN
        -- pg_logs trigger
        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_pg_log_insert') THEN
            CREATE TRIGGER trg_pg_log_insert
            AFTER INSERT ON pg_logs
            FOR EACH ROW EXECUTE FUNCTION notify_hive_event(); 
        END IF;

        -- pg_thoughts trigger
        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_pg_thought_insert') THEN
            CREATE TRIGGER trg_pg_thought_insert
            AFTER INSERT ON pg_thoughts
            FOR EACH ROW EXECUTE FUNCTION notify_hive_event(); 
        END IF;

        -- hive_debates trigger
        IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_hive_debate_update') THEN
            CREATE TRIGGER trg_hive_debate_update
            AFTER INSERT OR UPDATE ON hive_debates
            FOR EACH ROW EXECUTE FUNCTION notify_hive_event(); 
        END IF;
    END $$;
    """
    
    print("📝 로그 스키마 및 실시간 트리거 초기화 중...")
    try:
        subprocess.run([
            str(psql), "-p", str(PORT), "-U", "postgres", "-d", "postgres", "-c", schema_sql
        ], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
        print("✅ 로그 스키마 세팅 성공.")
    except Exception as e:
        stderr = getattr(e, 'stderr', 'No stderr')
        print(f"❌ 로그 스키마 세팅 실패: {e}\n{stderr}")

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
