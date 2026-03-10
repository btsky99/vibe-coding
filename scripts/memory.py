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

from src.pg_store import ensure_schema, get_memory, list_memory, migrate_legacy_data, set_memory


PG_BIN = MONITOR_DIR / "bin" / "pgsql" / "bin" / "psql.exe"
PG_PORT = 5433
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
    author = getattr(args, "by", "agent") or "agent"

    set_memory(
        key=key,
        content=content,
        title=title,
        tags=tags,
        author=author,
    )
    print(f"saved memory [{key}] by {author}")


def cmd_list(args) -> None:
    if not ensure_schema(DATA_DIR):
        print("PostgreSQL is not available.")
        sys.exit(1)

    query = getattr(args, "q", "") or ""
    entries = list_memory(q=query, top_k=20, show_all=True)
    if not entries:
        print("no memory entries found")
        return

    print("\n--- Hive Memory ---")
    for entry in entries:
        summary = str(entry.get("content", "")).replace("\n", " ")[:100]
        print(f"[{entry['key']}] by {entry.get('author', 'unknown')} | {entry.get('updated_at', '')[:19]}")
        print(f"  {summary}...")
    print("-------------------\n")


def cmd_get(args) -> None:
    if not ensure_schema(DATA_DIR):
        print("PostgreSQL is not available.")
        sys.exit(1)

    entry = get_memory(args.key)
    if not entry:
        print(f"not found: {args.key}")
        return

    print(f"[{entry['key']}] by {entry.get('author', 'unknown')} | {entry.get('updated_at', '')[:19]}")
    print(entry.get("content", ""))


def cmd_sync(args) -> None:
    if not ensure_schema(DATA_DIR):
        print("PostgreSQL is not available.")
        sys.exit(1)

    migrate_legacy_data(DATA_DIR)
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
    p_set.add_argument("--by", default="agent")

    p_list = sub.add_parser("list")
    p_list.add_argument("--q", default="")

    p_get = sub.add_parser("get")
    p_get.add_argument("key")

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
    elif args.command == "sync":
        cmd_sync(args)
    elif args.command == "q":
        cmd_q(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
