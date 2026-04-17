"""
FILE: scripts/memory.py
DESCRIPTION: Hive memory CLI backed by PostgreSQL.
"""

import argparse
import io
import json
import os
import subprocess
import sys
from pathlib import Path


if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MONITOR_DIR = PROJECT_ROOT / ".ai_monitor"
if str(MONITOR_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_DIR))

from src.pg_store import ensure_schema, get_memory, list_memory, migrate_legacy_data, set_memory, promote_to_zettel


PG_BIN = MONITOR_DIR / "bin" / "pgsql" / "bin" / "psql.exe"
PG_PORT = int(os.environ.get('VIBE_PG_PORT', '5433'))
DATA_DIR = MONITOR_DIR / "data"


def is_pg_available() -> bool:
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            [str(PG_BIN), "-p", str(PG_PORT), "-U", "postgres", "-d", "postgres", "-c", "SELECT 1"],
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=no_window,
        )
        return result.returncode == 0
    except Exception:
        return False


def run_pg_query(sql: str) -> str | None:
    env = os.environ.copy()
    env["PGCLIENTENCODING"] = "UTF8"
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            [
                str(PG_BIN),
                "-p",
                str(PG_PORT),
                "-U",
                "postgres",
                "-d",
                "postgres",
                "--no-align",
                "--tuples-only",
            ],
            input=sql,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=no_window,
        )
        return result.stdout.strip()
    except Exception as exc:
        print(f"[PG-ERR] {exc}")
        return None


def cmd_set(args) -> None:
    if not ensure_schema(DATA_DIR):
        print("PostgreSQL is not available.")
        sys.exit(1)

    key = args.key
    content = args.content
    title = getattr(args, "title", "") or key
    tags = [tag.strip() for tag in (getattr(args, "tags", "") or "").split(",") if tag.strip()]
    # author는 pg_store._resolve_author()가 처리 — 여기선 인자만 전달.
    # 미지정 시 HIVE_AGENT_ID env → 없으면 'unknown'
    author_arg = getattr(args, "by", None)

    saved = set_memory(
        key=key,
        content=content,
        title=title,
        tags=tags,
        author=author_arg,
    )
    resolved = (saved or {}).get('author', 'unknown')
    print(f"saved memory [{key}] by {resolved}")
    if resolved == 'unknown':
        print("  hint: HIVE_AGENT_ID 환경변수 설정 or --by 인자 지정 권장 (예: --by claude-t1)")


def cmd_list(args) -> None:
    if not ensure_schema(DATA_DIR):
        print("PostgreSQL is not available.")
        sys.exit(1)

    query = getattr(args, "q", "") or ""
    author_filter = getattr(args, "by", "") or ""
    entries = list_memory(q=query, top_k=20, show_all=True, author=author_filter)
    if not entries:
        msg = f"no memory entries found"
        if author_filter:
            msg += f" (author={author_filter})"
        print(msg)
        return

    header = "--- Hive Memory"
    if author_filter:
        header += f" (by {author_filter})"
    header += " ---"
    print(f"\n{header}")
    for entry in entries:
        summary = str(entry.get("content", "")).replace("\n", " ")[:100]
        updated = entry.get('updated_at', '')
        # psycopg2는 datetime 객체를 반환하므로 str()로 변환 후 슬라이싱
        updated_str = str(updated)[:19] if updated else ''
        print(f"[{entry['key']}] by {entry.get('author', 'unknown')} | {updated_str}")
        print(f"  {summary}...")
    print("-" * len(header) + "\n")


def cmd_get(args) -> None:
    if not ensure_schema(DATA_DIR):
        print("PostgreSQL is not available.")
        sys.exit(1)

    entry = get_memory(args.key)
    if not entry:
        print(f"not found: {args.key}")
        return

    updated = entry.get('updated_at', '')
    updated_str = str(updated)[:19] if updated else ''
    print(f"[{entry['key']}] by {entry.get('author', 'unknown')} | {updated_str}")
    print(entry.get("content", ""))


def cmd_promote(args) -> None:
    """hive_memory 항목을 zettel_notes로 승격 (C.3).

    원본은 유지하고 zettel 쪽에 source_ref=hive:<key>로 기록.
    --type fleeting|literature|permanent 지정 가능 (생략 시 태그 기반 자동 판정).
    """
    if not ensure_schema(DATA_DIR):
        print("PostgreSQL is not available.")
        sys.exit(1)

    note_type = getattr(args, 'type', '') or ''
    note = promote_to_zettel(args.key, note_type=note_type)
    if not note:
        print(f"승격 실패 — key를 찾을 수 없음: {args.key}")
        sys.exit(1)
    print(f"승격 완료 — zettel id={note.get('id')} type={note.get('note_type')}")


def cmd_sync(args) -> None:
    if not ensure_schema(DATA_DIR):
        print("PostgreSQL is not available.")
        sys.exit(1)

    # DB에 마이그레이션 완료 플래그 확인 — 이미 완료됐으면 재실행 방지
    # 매 UserPromptSubmit 훅마다 호출되는데, 매번 전체 마이그레이션을 돌리면
    # ON CONFLICT 에러 대량 발생 + 불필요한 IO 부하
    from src.pg_store import query_rows
    _mig_check = query_rows("SELECT state_key FROM hive_state WHERE state_key = 'migration_done' LIMIT 1;")
    if _mig_check:
        print("legacy SQLite data migrated to PostgreSQL")
        return

    migrate_legacy_data(DATA_DIR)
    # 완료 플래그 저장
    from src.pg_store import execute
    execute("INSERT INTO hive_state (state_key, payload, updated_at) "
            "VALUES ('migration_done', '{\"v\":1}'::jsonb, NOW()::text) "
            "ON CONFLICT (state_key) DO NOTHING;")
    print("legacy SQLite data migrated to PostgreSQL")


def cmd_q(args) -> None:
    if not is_pg_available():
        print("PGMQ commands require PostgreSQL.")
        return

    subcmd = args.q_cmd
    q_name = args.q_name

    if subcmd == "create":
        sql = f"SELECT pgmq.create('{q_name}');"
        run_pg_query(sql)
        print(f"created queue: {q_name}")
    elif subcmd == "send":
        msg = args.content
        sql = f"SELECT * FROM pgmq.send('{q_name}', '{json.dumps({'msg': msg})}');"
        result = run_pg_query(sql)
        print(f"sent: {result}")
    elif subcmd == "read":
        sql = f"SELECT * FROM pgmq.read('{q_name}', 30, 1);"
        result = run_pg_query(sql)
        if result:
            print(f"received: {result}")
        else:
            print("no messages")


def main() -> None:
    parser = argparse.ArgumentParser(description="Hive memory CLI")
    sub = parser.add_subparsers(dest="command")

    p_set = sub.add_parser("set")
    p_set.add_argument("key")
    p_set.add_argument("content")
    p_set.add_argument("--title", default="")
    p_set.add_argument("--tags", default="")
    # --by 기본값을 빈 문자열로 — pg_store._resolve_author()가 HIVE_AGENT_ID env 우선 처리
    p_set.add_argument("--by", default="")

    p_list = sub.add_parser("list")
    p_list.add_argument("--q", default="")
    p_list.add_argument("--by", default="", help="작성자 필터 (예: claude, claude-t1, gemini)")

    p_get = sub.add_parser("get")
    p_get.add_argument("key")

    # C.3 — 수동 승격: hive_memory 항목을 zettel_notes로
    p_promote = sub.add_parser("promote", help="hive_memory 항목을 zettel_notes로 승격")
    p_promote.add_argument("key")
    p_promote.add_argument("--type", default="",
                           choices=["", "fleeting", "literature", "permanent"],
                           help="zettel note_type (생략 시 태그 기반 자동)")

    sub.add_parser("sync")

    p_q = sub.add_parser("q")
    p_q.add_argument("q_cmd", choices=["create", "send", "read"])
    p_q.add_argument("q_name", default="hive_task_queue", nargs="?")
    p_q.add_argument("content", default="", nargs="?")

    args = parser.parse_args()
    if args.command == "set":
        cmd_set(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "get":
        cmd_get(args)
    elif args.command == "promote":
        cmd_promote(args)
    elif args.command == "sync":
        cmd_sync(args)
    elif args.command == "q":
        cmd_q(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
