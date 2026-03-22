# -*- coding: utf-8 -*-
"""
FILE: scripts/generate_hivemind_doc.py
DESCRIPTION: HIVEMIND.md 자동 생성기 — 하이브 DB 신호로부터 문서를 재구성.

REVISION HISTORY:
- 2026-03-19 Claude: 표준 헤더 형식 적용 (RULES.md 섹션 2 준수)
"""
from __future__ import annotations

import csv
import io
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = PROJECT_ROOT / "HIVEMIND.md"
LOCK_FILE = PROJECT_ROOT / ".ai_monitor" / "data" / "hivemind_doc.lock"
PG_BIN = PROJECT_ROOT / ".ai_monitor" / "bin" / "pgsql" / "bin" / "psql.exe"
PG_PORT = os.environ.get("VIBE_PG_PORT", "5433")

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from drift_detector import build_report, get_open_tasks  # noqa: E402


WARNINGS: list[str] = []
_HAS_PSYCOPG2 = False

try:
    import psycopg2
    import psycopg2.extras

    _HAS_PSYCOPG2 = True
except Exception:
    _HAS_PSYCOPG2 = False


def _warn(message: str) -> None:
    if message not in WARNINGS:
        WARNINGS.append(message)


def _acquire_lock(stale_after_seconds: int = 30) -> bool:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        try:
            age = time.time() - LOCK_FILE.stat().st_mtime
            if age > stale_after_seconds:
                LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False

    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()}\n{datetime.now().isoformat()}\n")
    return True


def _release_lock() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _query_rows_psycopg2(sql: str) -> list[dict]:
    conn = None
    try:
        conn = psycopg2.connect(
            host="127.0.0.1",
            port=int(PG_PORT),
            user="postgres",
            dbname="postgres",
        )
        conn.autocommit = True
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(sql)
            return [dict(row) for row in cursor.fetchall()]
    except Exception as exc:
        _warn(f"psycopg2 query failed: {exc}")
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _query_rows_psql(sql: str) -> list[dict]:
    if not PG_BIN.exists():
        _warn(f"psql.exe not found at {PG_BIN}")
        return []

    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    env = {**os.environ, "PGCLIENTENCODING": "UTF8"}
    try:
        result = subprocess.run(
            [
                str(PG_BIN),
                "-X",
                "-q",
                "--csv",
                "-v",
                "ON_ERROR_STOP=1",
                "-p",
                str(PG_PORT),
                "-U",
                "postgres",
                "-d",
                "postgres",
            ],
            input=sql,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=no_window,
            env=env,
        )
    except Exception as exc:
        _warn(f"psql query failed: {exc}")
        return []

    if result.returncode != 0:
        _warn((result.stderr or result.stdout or "psql query failed").strip())
        return []

    output = result.stdout.strip()
    if not output:
        return []
    return list(csv.DictReader(io.StringIO(output)))


def query_rows(sql: str) -> list[dict]:
    if _HAS_PSYCOPG2:
        rows = _query_rows_psycopg2(sql)
        if rows:
            return rows
    return _query_rows_psql(sql)


def get_recent_thoughts(limit: int = 8) -> list[str]:
    """[2026-03-22] pg_thoughts 제거됨 — 빈 리스트 반환."""
    return []


def _safe_mermaid_id(label: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in label)
    if not cleaned:
        cleaned = "node"
    if cleaned[0].isdigit():
        cleaned = f"n_{cleaned}"
    return cleaned


def get_agent_flow_mermaid() -> str:
    rows = query_rows(
        """
        SELECT from_agent, to_agent, COUNT(*) AS message_count
        FROM pg_messages
        GROUP BY from_agent, to_agent
        ORDER BY COUNT(*) DESC, from_agent, to_agent
        """
    )
    if not rows:
        return "graph LR\n    gemini[\"gemini\"] -->|idle| claude[\"claude\"]"

    lines = ["graph LR"]
    seen_nodes: set[str] = set()
    for row in rows:
        source_label = str(row.get("from_agent") or "unknown")
        target_label = str(row.get("to_agent") or "unknown")
        source_id = _safe_mermaid_id(source_label)
        target_id = _safe_mermaid_id(target_label)
        if source_id not in seen_nodes:
            lines.append(f'    {source_id}["{source_label}"]')
            seen_nodes.add(source_id)
        if target_id not in seen_nodes:
            lines.append(f'    {target_id}["{target_label}"]')
            seen_nodes.add(target_id)
        count = row.get("message_count") or row.get("count") or "0"
        lines.append(f'    {source_id} -->|{count} msgs| {target_id}')
    return "\n".join(lines)


def get_recent_debates(limit: int = 5) -> list[str]:
    rows = query_rows(
        f"""
        SELECT id, topic, status, current_round, COALESCE(final_decision, '') AS final_decision
        FROM hive_debates
        ORDER BY updated_at DESC, id DESC
        LIMIT {int(limit)}
        """
    )
    items: list[str] = []
    for row in rows:
        decision = row.get("final_decision") or ""
        suffix = f" decision={decision[:80]}" if decision else ""
        items.append(
            f"- #{row.get('id')} [{row.get('status')}] round={row.get('current_round')}: "
            f"{row.get('topic')}{suffix}"
        )
    return items


def format_focus_section(report: dict) -> str:
    open_tasks = get_open_tasks()
    lines = []
    if open_tasks:
        lines.append("Open plan tasks:")
        for task in open_tasks[:5]:
            lines.append(f"- Task {task.number}: {task.title}")
            for detail in task.details[:2]:
                lines.append(f"  {detail}")
    else:
        lines.append("No open plan tasks remain.")

    lines.append("")
    lines.append(f"Alignment: {report['summary']}")

    changed_files = report.get("changed_files") or []
    if changed_files:
        lines.append("Changed files:")
        for path in changed_files[:8]:
            lines.append(f"- {path}")
        if len(changed_files) > 8:
            lines.append(f"- ... and {len(changed_files) - 8} more")

    return "\n".join(lines)


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=str(path.parent),
        prefix=path.name,
        suffix=".tmp",
    ) as handle:
        handle.write(content)
        temp_name = handle.name
    os.replace(temp_name, path)


def generate_doc() -> int:
    if not _acquire_lock():
        print(f"Skipped {OUTPUT_FILE}: another refresh is already running.")
        return 0

    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        drift_report = build_report()
        thoughts = get_recent_thoughts()
        debates = get_recent_debates()
        mermaid = get_agent_flow_mermaid()

        content_lines = [
            "# HiveMind Status",
            "",
            f"Updated: `{now}`",
            "",
            "## Current Focus",
            format_focus_section(drift_report),
            "",
            "## Agent Flow",
            "```mermaid",
            mermaid,
            "```",
            "",
            "## Recent Thought Stream",
        ]

        if thoughts:
            content_lines.extend(thoughts)
        else:
            content_lines.append("- No recent thought records found.")

        content_lines.extend(["", "## Debate Ledger"])
        if debates:
            content_lines.extend(debates)
        else:
            content_lines.append("- No debates recorded yet.")

        if WARNINGS:
            content_lines.extend(["", "## Data Warnings"])
            for warning in WARNINGS:
                content_lines.append(f"- {warning}")

        content_lines.extend(
            [
                "",
                "---",
                "> This file is generated by `scripts/generate_hivemind_doc.py`.",
                "",
            ]
        )

        write_atomic(OUTPUT_FILE, "\n".join(content_lines))
        print(f"Generated {OUTPUT_FILE}")
        return 0
    finally:
        _release_lock()


if __name__ == "__main__":
    raise SystemExit(generate_doc())
