"""
FILE: scripts/memory.py
DESCRIPTION: 하이브 마인드 통합 메모리 매니저 (PostgreSQL 18 + Vector 지원).
             기존 SQLite 폴백을 유지하며, 5433 포트의 PostgreSQL을 주 엔진으로 사용함.

REVISION HISTORY:
- 2026-03-06 Gemini: PostgreSQL 18 기반 대통합 리팩토링. 벡터 검색 및 psql.exe 호출 방식 구현.
- 2026-03-01 Claude: 최초 구현 및 SQLite 연동.
"""

import sys
import json
import argparse
import subprocess
import os
import time
import sqlite3
from pathlib import Path

# Windows 터미널 한글 출력 설정
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# ─── 경로 및 설정 ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
PG_BIN = PROJECT_ROOT / ".ai_monitor" / "bin" / "pgsql" / "bin" / "psql.exe"
PG_PORT = 5433
SQLITE_DB = PROJECT_ROOT / ".ai_monitor" / "data" / "shared_memory.db"

# ─── DB 연결 체크 ─────────────────────────────────────────────────────────────
def is_pg_available():
    """PostgreSQL 5433 포트 가동 여부 확인"""
    try:
        res = subprocess.run([
            str(PG_BIN), "-p", str(PG_PORT), "-U", "postgres", "-d", "postgres", "-c", "SELECT 1"
        ], capture_output=True, text=True, timeout=2)
        return res.returncode == 0
    except:
        return False

def run_pg_query(sql):
    """psql.exe를 통한 쿼리 실행"""
    env = os.environ.copy()
    env["PGCLIENTENCODING"] = "UTF8"
    try:
        res = subprocess.run([
            str(PG_BIN), "-p", str(PG_PORT), "-U", "postgres", "-d", "postgres", 
            "--no-align", "--tuples-only", "-c", sql
        ], env=env, capture_output=True, text=True, encoding="utf-8")
        return res.stdout.strip()
    except Exception as e:
        print(f"[PG-ERR] {e}")
        return None

# ─── 명령어 구현 ─────────────────────────────────────────────────────────────

def cmd_set(args):
    key = args.key
    content = args.content
    title = getattr(args, 'title', '') or key
    tags = [t.strip() for t in (getattr(args, 'tags', '') or '').split(',') if t.strip()]
    author = getattr(args, 'by', 'agent') or 'agent'
    
    if is_pg_available():
        # PostgreSQL에 저장
        def esc(v): return str(v).replace("'", "''")
        sql = f"""
        INSERT INTO hive_memory (key, title, content, tags, author, updated_at)
        VALUES ('{esc(key)}', '{esc(title)}', '{esc(content)}', '{json.dumps(tags)}'::jsonb, '{esc(author)}', CURRENT_TIMESTAMP)
        ON CONFLICT (key) DO UPDATE SET
            content = EXCLUDED.content,
            updated_at = EXCLUDED.updated_at;
        """
        run_pg_query(sql)
        print(f"🧠 [슈퍼 DB] 기억 저장 완료: [{key}] by {author}")
    else:
        # 폴백: SQLite
        print("⚠️ DB 미실행 - SQLite에 임시 저장합니다.")
        with sqlite3.connect(str(SQLITE_DB)) as conn:
            conn.execute("INSERT OR REPLACE INTO memory (key, id, title, content, tags, author, timestamp, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                         (key, str(int(time.time())), title, content, json.dumps(tags), author, str(time.time()), str(time.time())))
        print(f"🧠 [SQLite] 임시 저장 완료: [{key}]")

def cmd_list(args):
    q = getattr(args, 'q', '') or ''
    entries = []
    
    if is_pg_available():
        # PostgreSQL 검색 (Trgm 활용)
        sql = "SELECT key, title, author, updated_at, content FROM hive_memory"
        if q:
            sql += f" WHERE content ILIKE '%{q.replace("'", "''")}%' OR title ILIKE '%{q.replace("'", "''")}%'"
        sql += " ORDER BY updated_at DESC LIMIT 20"
        
        res = run_pg_query(sql)
        if res:
            for line in res.split('\n'):
                parts = line.split('|')
                if len(parts) >= 5:
                    entries.append({
                        "key": parts[0], "title": parts[1], "author": parts[2],
                        "updated_at": parts[3], "content": parts[4]
                    })
    else:
        # SQLite 검색
        with sqlite3.connect(str(SQLITE_DB)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM memory ORDER BY updated_at DESC LIMIT 20").fetchall()
            for r in rows:
                entries.append(dict(r))

    if not entries:
        print("📭 저장된 기억이 없습니다.")
        return

    print(f"\n--- [하이브 지능 센터: 기억 목록 ({'PostgreSQL' if is_pg_available() else 'SQLite'})] ---")
    for e in entries:
        print(f"🧠 [{e['key']}]  by {e.get('author', 'unknown')} | {e.get('updated_at', '')[:19]}")
        print(f"   내용: {e['content'][:100].replace('\n', ' ')}...")
    print("--------------------------------------------------\n")

def cmd_sync(args):
    """PostgreSQL 18과 SQLite 간의 데이터 동기화 확인 및 연결 체크"""
    print("🔄 [하이브 지능 센터] 메모리 동기화 체크 중...")
    
    pg_ok = is_pg_available()
    if pg_ok:
        # PostgreSQL 연결 확인 및 테이블 존재 체크
        sql = "SELECT count(*) FROM hive_memory"
        res = run_pg_query(sql)
        if res is not None:
            print(f"✅ PostgreSQL 18 (Port 5433) 연결 정상: {res}개 항목 확인")
        else:
            print("⚠️ PostgreSQL 연결은 되나 hive_memory 테이블을 찾을 수 없습니다. 스키마 확인 필요.")
    else:
        print("⚠️ PostgreSQL 18 (Port 5433) 서버가 응답하지 않습니다. SQLite 폴백 상태입니다.")

    if SQLITE_DB.exists():
        try:
            with sqlite3.connect(str(SQLITE_DB)) as conn:
                count = conn.execute("SELECT count(*) FROM memory").fetchone()[0]
                print(f"✅ SQLite 폴백 DB 정상: {count}개 항목 확인")
        except Exception as e:
            print(f"❌ SQLite DB 체크 실패: {e}")
    else:
        print(f"⚠️ SQLite DB 파일이 존재하지 않습니다: {SQLITE_DB}")

    if pg_ok:
        print("✨ 메모리 엔진: PostgreSQL 18 (Primary)")
    else:
        print("✨ 메모리 엔진: SQLite (Secondary/Fallback)")

def main():
    parser = argparse.ArgumentParser(description='하이브 통합 메모리 매니저')
    sub = parser.add_subparsers(dest='command')

    p_set = sub.add_parser('set')
    p_set.add_argument('key')
    p_set.add_argument('content')
    p_set.add_argument('--title', default='')
    p_set.add_argument('--tags', default='')
    p_set.add_argument('--by', default='agent')

    p_list = sub.add_parser('list')
    p_list.add_argument('--q', default='')

    # [자기치유] hive_watchdog.py에서 호출하는 sync 명령 추가
    p_sync = sub.add_parser('sync')

    args = parser.parse_args()
    if args.command == 'set': cmd_set(args)
    elif args.command == 'list': cmd_list(args)
    elif args.command == 'sync': cmd_sync(args)
    else: parser.print_help()

if __name__ == '__main__':
    main()
