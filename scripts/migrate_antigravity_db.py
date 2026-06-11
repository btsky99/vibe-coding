#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FILE: scripts/migrate_antigravity_db.py
DESCRIPTION: DB 식별자 gemini→antigravity 일회성 마이그레이션 (plan Task 9).
             pg_dump 백업 → 단일 트랜잭션 UPDATE 13컬럼 → 건수 리포트.
             완료 후 삭제 대상 (일회성 마이그레이션 보관 금지 — 4차 정리 규칙).

REVISION HISTORY:
- 2026-06-11 Claude: 최초 작성 — 값 패턴: gemini / Gemini / Gemini-1 / 'Gemini CLI' / gemini:T2 / gemini:terminal-N
"""
import gzip
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".ai_monitor"))

from src import pg_base  # noqa: E402 — PG_BIN/PG_PORT/접속 헬퍼

COLS = [
    ("active_session_context", "agent_id"), ("agent_experience", "agent_id"),
    ("agent_heartbeats", "agent_id"), ("agent_stats", "agent_id"),
    ("hive_memory", "author"), ("hive_sessions", "agent"), ("hive_skill_chains", "agent"),
    ("hive_tasks", "assigned_to"), ("pg_logs", "agent"), ("pg_messages", "from_agent"),
    ("pg_messages", "to_agent"), ("task_comments", "author"), ("zettel_notes", "author"),
]


def backup() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = ROOT / "backups" / f"pre_antigravity_migration_{ts}.sql.gz"
    out.parent.mkdir(exist_ok=True)
    # [함정] pg_base.PG_BIN은 디렉토리가 아니라 psql.exe 전체 경로 — 형제 파일로 접근
    pg_dump = Path(str(pg_base.PG_BIN)).parent / "pg_dump.exe"
    db = pg_base.PG_DB if isinstance(pg_base.PG_DB, str) else str(pg_base.PG_DB)
    proc = subprocess.run(
        [str(pg_dump), "-h", "127.0.0.1", "-p", str(pg_base.PG_PORT), "-U", pg_base.PG_USER, db],
        capture_output=True, timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pg_dump 실패: {proc.stderr[:300]}")
    with gzip.open(out, "wb") as f:
        f.write(proc.stdout)
    print(f"[백업] {out} ({out.stat().st_size // 1024} KB)")
    return out


def migrate() -> None:
    conn = pg_base._get_pg_conn()
    total = 0
    try:
        with conn, conn.cursor() as cur:  # with conn = 단일 트랜잭션 (예외 시 전체 롤백)
            for table, col in COLS:
                # 'Gemini CLI'/'gemini'/'Gemini-1'/'gemini:T2' 등 접두 패턴만 치환 — 접미사 보존
                cur.execute(
                    f"UPDATE {table} SET {col} = regexp_replace({col}, '^[Gg]emini( CLI)?', 'antigravity') "
                    f"WHERE {col} ~* '^gemini'"
                )
                if cur.rowcount:
                    print(f"  {table}.{col}: {cur.rowcount}건")
                    total += cur.rowcount
        print(f"[완료] 총 {total}건 UPDATE (커밋됨)")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # 검증: 잔존 0 확인
    remain = []
    for table, col in COLS:
        rows = pg_base.query_rows(f"SELECT count(*) AS n FROM {table} WHERE {col} ~* '^gemini'")
        if rows and rows[0]["n"]:
            remain.append(f"{table}.{col}={rows[0]['n']}")
    print("[검증] 잔존:", remain if remain else "0건 ✓")


if __name__ == "__main__":
    backup()
    migrate()
