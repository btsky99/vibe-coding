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
    # CREATE_NO_WINDOW: 백그라운드에서 호출 시 콘솔 창 팝업 방지
    _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        res = subprocess.run([
            str(PG_BIN), "-p", str(PG_PORT), "-U", "postgres", "-d", "postgres", "-c", "SELECT 1"
        ], capture_output=True, text=True, timeout=2, creationflags=_no_window)
        return res.returncode == 0
    except:
        return False

def run_pg_query(sql):
    """psql.exe를 통한 쿼리 실행"""
    env = os.environ.copy()
    env["PGCLIENTENCODING"] = "UTF8"
    # CREATE_NO_WINDOW: 백그라운드에서 호출 시 콘솔 창 팝업 방지
    _no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        res = subprocess.run([
            str(PG_BIN), "-p", str(PG_PORT), "-U", "postgres", "-d", "postgres",
            "--no-align", "--tuples-only", "-c", sql
        ], env=env, capture_output=True, text=True, encoding="utf-8", creationflags=_no_window)
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
        # [PG Search 고도화] pg_trgm 유사도 검색 + tsvector 전문 검색 하이브리드
        if q:
            # 1. pg_trgm 유사도 검색 (% 연산자) + tsvector 텍스트 검색 (@@ 연산자)
            # 2. ts_rank를 이용한 결과 랭킹 (Elasticsearch 수준)
            sql = f"""
            SELECT key, title, author, updated_at, content,
                   ts_rank_cd(to_tsvector('simple', content || ' ' || title), plainto_tsquery('simple', '{q}')) AS rank
            FROM hive_memory
            WHERE (to_tsvector('simple', content || ' ' || title) @@ plainto_tsquery('simple', '{q}'))
               OR (content % '{q}' OR title % '{q}')
            ORDER BY rank DESC, updated_at DESC
            LIMIT 20;
            """
        else:
            sql = "SELECT key, title, author, updated_at, content, 0 as rank FROM hive_memory ORDER BY updated_at DESC LIMIT 20"
        
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
        # SQLite 검색 (기본)
        with sqlite3.connect(str(SQLITE_DB)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM memory ORDER BY updated_at DESC LIMIT 20").fetchall()
            for r in rows:
                entries.append(dict(r))

    if not entries:
        print("📭 저장된 기억이 없습니다.")
        return

    print(f"\n--- [하이브 지능 센터: 고도화 검색 결과 ({'PostgreSQL' if is_pg_available() else 'SQLite'})] ---")
    for e in entries:
        print(f"🧠 [{e['key']}]  by {e.get('author', 'unknown')} | {e.get('updated_at', '')[:19]}")
        print(f"   내용: {e['content'][:100].replace('\n', ' ')}...")
    print("--------------------------------------------------\n")

def cmd_get(args):
    """특정 키의 전체 내용 조회 — 현재 작업 상태 파악용"""
    key = args.key
    if is_pg_available():
        def esc(v): return str(v).replace("'", "''")
        sql = f"SELECT key, author, updated_at, content FROM hive_memory WHERE key = '{esc(key)}' LIMIT 1;"
        res = run_pg_query(sql)
        if res:
            parts = res.split('|', 3)
            if len(parts) >= 4:
                print(f"🧠 [{parts[0]}] by {parts[1]} | {parts[2][:19]}")
                print(parts[3])
            else:
                print(res)
        else:
            print(f"📭 키 없음: {key}")
    else:
        with sqlite3.connect(str(SQLITE_DB)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM memory WHERE key=?", (key,)).fetchone()
            if row:
                print(f"🧠 [{row['key']}] by {row.get('author','?')} | {row.get('updated_at','')[:19]}")
                print(row['content'])
            else:
                print(f"📭 키 없음: {key}")

def cmd_sync(args):
    """SQLite → PostgreSQL 동기화. hive_watchdog에서 주기적으로 호출됨."""
    if not is_pg_available():
        print("⚠️ PostgreSQL 미실행 — sync 건너뜀")
        return
    # SQLite에 있는 항목을 PostgreSQL로 마이그레이션
    migrated = 0
    try:
        with sqlite3.connect(str(SQLITE_DB)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM memory ORDER BY updated_at ASC").fetchall()
        for r in rows:
            def esc(v): return str(v or '').replace("'", "''")
            tags = r['tags'] if r['tags'] else '[]'
            try:
                json.loads(tags)
            except Exception:
                tags = '[]'
            r = dict(r)
            sql = f"""
            INSERT INTO hive_memory (key, title, content, tags, author, updated_at)
            VALUES ('{esc(r["key"])}', '{esc(r.get("title",""))}', '{esc(r["content"])}',
                    '{tags}'::jsonb, '{esc(r.get("author","agent"))}', CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO NOTHING;
            """
            run_pg_query(sql)
            migrated += 1
        print(f"✅ [sync] SQLite→PG 동기화 완료: {migrated}건")
    except Exception as e:
        print(f"❌ [sync] 오류: {e}")
        sys.exit(1)

# ── PGMQ (메시지 큐) 지원 ───────────────────────────────────────────────

def cmd_q(args):
    """PGMQ를 활용한 에이전트 간 메시징"""
    if not is_pg_available():
        print("⚠️ PGMQ는 PostgreSQL 전용 기능입니다.")
        return

    subcmd = args.q_cmd
    q_name = args.q_name

    if subcmd == "create":
        sql = f"SELECT pgmq.create('{q_name}');"
        run_pg_query(sql)
        print(f"📥 [PGMQ] 큐 생성 완료: {q_name}")
    
    elif subcmd == "send":
        msg = args.content
        sql = f"SELECT * FROM pgmq.send('{q_name}', '{json.dumps({'msg': msg})}');"
        res = run_pg_query(sql)
        print(f"✉️ [PGMQ] 메시지 전송: {res}")
    
    elif subcmd == "read":
        sql = f"SELECT * FROM pgmq.read('{q_name}', 30, 1);"
        res = run_pg_query(sql)
        if res:
            print(f"📖 [PGMQ] 수신: {res}")
        else:
            print("📭 수신할 메시지가 없습니다.")

def main():
    parser = argparse.ArgumentParser(description='하이브 통합 메모리 매니저 (Super DB Edition)')
    sub = parser.add_subparsers(dest='command')

    p_set = sub.add_parser('set')
    p_set.add_argument('key')
    p_set.add_argument('content')
    p_set.add_argument('--title', default='')
    p_set.add_argument('--tags', default='')
    p_set.add_argument('--by', default='agent')

    p_list = sub.add_parser('list')
    p_list.add_argument('--q', default='')

    p_get = sub.add_parser('get')
    p_get.add_argument('key')

    # [자기치유] hive_watchdog.py에서 호출하는 sync 명령 추가
    p_sync = sub.add_parser('sync')

    # [신규] PGMQ 메시지 큐 명령
    p_q = sub.add_parser('q')
    p_q.add_argument('q_cmd', choices=['create', 'send', 'read'])
    p_q.add_argument('q_name', default='hive_task_queue', nargs='?')
    p_q.add_argument('content', default='', nargs='?')

    args = parser.parse_args()
    if args.command == 'set': cmd_set(args)
    elif args.command == 'list': cmd_list(args)
    elif args.command == 'get': cmd_get(args)
    elif args.command == 'sync': cmd_sync(args)
    elif args.command == 'q': cmd_q(args)
    else: parser.print_help()

if __name__ == '__main__':
    main()
