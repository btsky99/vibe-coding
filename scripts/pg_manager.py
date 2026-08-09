"""
FILE: scripts/pg_manager.py
DESCRIPTION: 하이브 마인드 전용 포터블 PostgreSQL 통합 매니저.
             포트 5433으로 DB를 제어하고, 핵심 확장 기능(Vector, Search, MQ)을 활성화함.

REVISION HISTORY:
- 2026-03-06 Gemini: 최초 작성. 시작/중지/상태체크 및 확장 기능 활성화 로직 구현.
- 2026-03-10 Gemini: Task 17 강화 - pg_logs/pg_thoughts 스키마 통합 및 지식 그래프 기반 마련.
- 2026-03-11 Claude: frozen(배포) 모드 경로 추가 — {exe dir}\\pgsql + %APPDATA%\\VibeCoding\\pgdata
"""

import os
import sys
import time
from pathlib import Path

# 윈도우 cp949 터미널에서 이모지/한글 출력 시 UnicodeEncodeError 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).parent.parent

# [🔴 2026-08-09] pg_ctl/psql 은 콘솔 앱이라 subprocess.run 직호출 시 검은 cmd 창이 뜬다.
#   이 스크립트는 사람만 부르는 게 아니다 — hook_bridge/itcp/pg_base 가 PG가 죽어 있으면
#   자동으로 `pg_manager start` 를 띄운다(훅 경로 포함). CREATE_NO_WINDOW 는 상속되지
#   않으므로 부모가 콘솔 숨김으로 띄워도 여기서 다시 주입해야 한다.
sys.path.insert(0, str(PROJECT_ROOT / '.ai_monitor'))
from infra import proc  # noqa: E402 — [표준] 콘솔 숨김 래퍼, 경로 삽입 후라야 import 가능

# frozen(배포) 모드: installer가 {app}\pgsql\ 에 설치한 바이너리 사용
# 개발 모드: 소스 트리 내 .ai_monitor/bin/pgsql/ 사용
if getattr(sys, 'frozen', False):
    PG_DIR = Path(sys.executable).resolve().parent / "pgsql"
    DATA_DIR = Path(os.getenv('APPDATA', '')) / "VibeCoding" / "pgdata"
else:
    PG_DIR = PROJECT_ROOT / ".ai_monitor" / "bin" / "pgsql"
    DATA_DIR = PG_DIR / "data"

BIN_DIR = PG_DIR / "bin"
PORT = int(os.environ.get('VIBE_PG_PORT', '5433'))

def run_pg_ctl(cmd_args):
    pg_ctl = BIN_DIR / "pg_ctl.exe"
    cmd = [str(pg_ctl)] + cmd_args + ["-D", str(DATA_DIR)]
    try:
        # 로그 파일 지정
        log_file = DATA_DIR.parent / "pgsql.log" if getattr(sys, 'frozen', False) else PROJECT_ROOT / ".ai_monitor" / "data" / "pgsql.log"
        if "start" in cmd_args:
            cmd += ["-l", str(log_file)]
        
        # encoding 명시: 윈도우 cp949 환경에서 PostgreSQL UTF-8 출력 디코딩 오류 방지
        result = proc.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return result.stdout.strip()
    except Exception as e:
        return f"Error: {str(e)}"

def _fix_lc_messages():
    """postgresql.conf의 lc_messages를 'C'로 설정한다.

    [2026-03-27] Windows 한글 환경에서 PostgreSQL이 CP949 에러 메시지를 반환하면
    psycopg2가 UTF-8 디코딩에 실패. lc_messages=C로 강제하여 영문 출력.
    """
    pg_conf = DATA_DIR / "postgresql.conf"
    if not pg_conf.exists():
        return
    try:
        import re
        text = pg_conf.read_text(encoding='utf-8')
        match = re.search(r"^lc_messages\s*=\s*'([^']*)'", text, re.MULTILINE)
        if match and match.group(1) != 'C':
            new_text = re.sub(
                r"^(lc_messages\s*=\s*)'[^']*'",
                r"\g<1>'C'\t\t\t# 영문 에러 메시지 강제 (setup_doctor 자동 적용)",
                text, count=1, flags=re.MULTILINE
            )
            pg_conf.write_text(new_text, encoding='utf-8')
            print("🔧 lc_messages=C 자동 적용 완료")
    except Exception as e:
        print(f"⚠️ lc_messages 설정 실패: {e}")


def start():
    print(f"🚀 PostgreSQL 시작 중 (Port: {PORT})...")
    # 시작 전 lc_messages=C 자동 적용
    _fix_lc_messages()

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
        proc.run([
            str(psql), "-p", str(PORT), "-U", "postgres", "-d", "postgres", "-c", sql
        ], capture_output=True, text=True, encoding="utf-8", errors="replace")

        # PGMQ SQL 파일 실행
        mq_sql_path = PG_DIR / "share" / "extension" / "pgmq.sql"
        if mq_sql_path.exists():
            proc.run([
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

    -- [2026-03-22] pg_thoughts 테이블 제거 (지식그래프 삭제)

    -- 3. Agent Messaging Table (pg_messages)
    CREATE TABLE IF NOT EXISTS pg_messages (
        id SERIAL PRIMARY KEY,
        ts TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        from_agent VARCHAR(50),
        to_agent VARCHAR(50),
        msg_type VARCHAR(20) DEFAULT 'info',
        content TEXT,
        is_read BOOLEAN DEFAULT FALSE,
        channel VARCHAR(20) DEFAULT 'general',
        metadata JSONB DEFAULT '{}'::jsonb,
        terminal_id VARCHAR(50) DEFAULT ''
    );

    -- Migration: keep pg_messages aligned with ITCP v2 schema.
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pg_messages' AND column_name='channel') THEN
            ALTER TABLE pg_messages ADD COLUMN channel VARCHAR(20) DEFAULT 'general';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pg_messages' AND column_name='metadata') THEN
            ALTER TABLE pg_messages ADD COLUMN metadata JSONB DEFAULT '{}'::jsonb;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pg_messages' AND column_name='terminal_id') THEN
            ALTER TABLE pg_messages ADD COLUMN terminal_id VARCHAR(50) DEFAULT '';
        END IF;
    END $$;

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
        proc.run([
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
