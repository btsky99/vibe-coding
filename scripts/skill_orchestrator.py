# -*- coding: utf-8 -*-
"""
Postgres-backed skill chain tracker.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
MONITOR_DIR = ROOT_DIR / '.ai_monitor'
if str(MONITOR_DIR) not in sys.path:
    sys.path.insert(0, str(MONITOR_DIR))

from src.pg_store import ensure_schema, execute, query_rows, upsert_skill_chain_row


SKILL_REGISTRY = [
    {"num": 1, "name": "vibe-debug", "short": "debug"},
    {"num": 2, "name": "vibe-tdd", "short": "tdd"},
    {"num": 3, "name": "vibe-brainstorm", "short": "brainstorm"},
    {"num": 4, "name": "vibe-write-plan", "short": "write-plan"},
    {"num": 5, "name": "vibe-execute-plan", "short": "execute"},
    {"num": 6, "name": "vibe-code-review", "short": "review"},
    {"num": 7, "name": "vibe-release", "short": "release"},
    {"num": 8, "name": "vibe-heal", "short": "heal"},
]

_SKILL_NAME_TO_NUM = {skill["name"]: skill["num"] for skill in SKILL_REGISTRY}
DATA_DIR = MONITOR_DIR / 'data'
RESULTS_FILE = DATA_DIR / 'skill_results.jsonl'


def _sql_text(value) -> str:
    if value is None:
        return 'NULL'
    return "'" + str(value).replace("'", "''") + "'"


def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')


def _get_agent() -> str:
    return os.getenv('HIVE_AGENT', '')


def _get_terminal_id() -> int:
    raw = os.getenv('TERMINAL_ID', '').strip()
    if not raw:
        return 0
    try:
        return int(raw.lstrip('Tt'))
    except (TypeError, ValueError):
        return 0


def _skill_num(name: str) -> int:
    return _SKILL_NAME_TO_NUM.get(name, 0)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', ''))
    except Exception:
        return None


def _query(sql: str) -> list[dict]:
    ensure_schema(DATA_DIR)
    return query_rows(sql)


def _active_session(terminal_id: int) -> str | None:
    rows = _query(
        "SELECT session_id "
        "FROM hive_skill_chains "
        f"WHERE terminal_id = {int(terminal_id)} "
        "AND status IN ('running', 'pending') "
        "ORDER BY updated_at DESC, started_at DESC, id DESC "
        "LIMIT 1;"
    )
    if rows:
        return rows[0].get('session_id')

    recent_cutoff = datetime.now() - timedelta(minutes=5)
    rows = _query(
        "SELECT session_id, updated_at "
        "FROM hive_skill_chains "
        f"WHERE terminal_id = {int(terminal_id)} "
        "ORDER BY updated_at DESC, id DESC "
        "LIMIT 20;"
    )
    for row in rows:
        updated_at = _parse_dt(row.get('updated_at'))
        if updated_at and updated_at >= recent_cutoff:
            return row.get('session_id')
    return None


def _save_result_history(
    terminal_id: int,
    session_id: str,
    request: str,
    results: list[dict],
    completed_at: str,
) -> None:
    record = {
        "session_id": session_id,
        "terminal_id": terminal_id,
        "agent": _get_agent(),
        "request": request,
        "results": results,
        "completed_at": completed_at,
    }
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(RESULTS_FILE, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"[WARN] failed to save results: {exc}")


def _broadcast_status(agent: str, content: str) -> None:
    messages_file = DATA_DIR / 'messages.jsonl'
    msg = {
        "id": str(int(time.time() * 1000)),
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "from": agent or "agent",
        "to": "all",
        "type": "status",
        "content": content,
        "read": False,
    }
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(messages_file, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(msg, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"[WARN] failed to broadcast status: {exc}")


def cmd_plan(terminal_id: int, request: str, skills: list[str]) -> None:
    ensure_schema(DATA_DIR)
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    agent = _get_agent()
    now = _now()

    execute(
        "UPDATE hive_skill_chains SET status='skipped' "
        f"WHERE terminal_id={int(terminal_id)} AND status IN ('running','pending');"
    )

    for step_order, skill_name in enumerate(skills):
        upsert_skill_chain_row({
            'session_id': session_id,
            'terminal_id': terminal_id,
            'agent': agent,
            'request': request,
            'skill_num': _skill_num(skill_name),
            'skill_name': skill_name,
            'step_order': step_order,
            'status': 'pending',
            'summary': '',
            'started_at': now,
            'updated_at': now,
        })

    print(f"[OK] planned: {' -> '.join(skills)}")
    print(f"     session={session_id} terminal=T{terminal_id or '?'} agent={agent or 'unknown'}")
    _broadcast_status(
        agent=agent or 'agent',
        content=f"[skill-chain] T{terminal_id or '?'} {request[:60]} | {' -> '.join(skills)}",
    )


def cmd_update(terminal_id: int, step: int, status: str, summary: str = "") -> None:
    ensure_schema(DATA_DIR)
    session_id = _active_session(terminal_id) or _active_session(0)
    if not session_id:
        print("[WARN] no active chain")
        sys.exit(1)

    rows = _query(
        "SELECT id, skill_name "
        "FROM hive_skill_chains "
        f"WHERE session_id = {_sql_text(session_id)} "
        f"AND terminal_id = {int(terminal_id if terminal_id else 0)} "
        f"AND step_order = {int(step)} "
        "ORDER BY id DESC LIMIT 1;"
    )
    if not rows and terminal_id:
        rows = _query(
            "SELECT id, skill_name "
            "FROM hive_skill_chains "
            f"WHERE session_id = {_sql_text(session_id)} "
            "AND terminal_id = 0 "
            f"AND step_order = {int(step)} "
            "ORDER BY id DESC LIMIT 1;"
        )
    if not rows:
        print(f"[ERROR] invalid step: {step}")
        sys.exit(1)

    row = rows[0]
    execute(
        "UPDATE hive_skill_chains "
        f"SET status = {_sql_text(status)}, summary = {_sql_text(summary)}, updated_at = {_sql_text(_now())} "
        f"WHERE id = {int(row['id'])};"
    )

    skill_name = row.get('skill_name', f'step-{step}')
    print(f"[OK] {skill_name}: {status}" + (f" | {summary}" if summary else ""))

    agent = _get_agent() or 'agent'
    if status == 'running':
        message = f"{agent} running [{skill_name}]"
    elif status == 'done':
        message = f"{agent} finished [{skill_name}]"
    elif status == 'failed':
        message = f"{agent} failed [{skill_name}]"
    else:
        message = f"{agent} {status} [{skill_name}]"
    if summary:
        message = f"{message} | {summary}"
    _broadcast_status(agent=agent, content=message)


def cmd_status() -> None:
    print(json.dumps(_build_response(), ensure_ascii=False, indent=2))


def cmd_done(terminal_id: int) -> None:
    ensure_schema(DATA_DIR)
    session_id = _active_session(terminal_id) or _active_session(0)
    if not session_id:
        print("[WARN] no active chain")
        return

    now = _now()
    execute(
        "UPDATE hive_skill_chains "
        f"SET status='skipped', updated_at={_sql_text(now)} "
        f"WHERE session_id={_sql_text(session_id)} AND status='pending';"
    )
    execute(
        "UPDATE hive_skill_chains "
        f"SET status='done', updated_at={_sql_text(now)} "
        f"WHERE session_id={_sql_text(session_id)} AND status='running';"
    )

    rows = _query(
        "SELECT skill_name, status, summary, request "
        "FROM hive_skill_chains "
        f"WHERE session_id = {_sql_text(session_id)} "
        "ORDER BY step_order ASC, id ASC;"
    )
    request = rows[0].get('request', '') if rows else ''
    results = [
        {
            'skill': row.get('skill_name', ''),
            'status': row.get('status', ''),
            'summary': row.get('summary', ''),
        }
        for row in rows
    ]
    _save_result_history(terminal_id, session_id, request, results, now)

    print("[OK] chain complete")
    for result in results:
        suffix = f" | {result['summary']}" if result.get('summary') else ""
        print(f"     {result['status']}: {result['skill']}{suffix}")


def cmd_reset(terminal_id: int) -> None:
    ensure_schema(DATA_DIR)
    execute(
        "UPDATE hive_skill_chains SET status='skipped' "
        f"WHERE terminal_id={int(terminal_id)} AND status IN ('running','pending');"
    )
    print(f"[OK] reset T{terminal_id or '?'}")


def _build_response() -> dict:
    ensure_schema(DATA_DIR)
    stale_cutoff = datetime.now() - timedelta(hours=1)
    execute(
        "UPDATE hive_skill_chains SET status='skipped' "
        "WHERE status IN ('running', 'pending') "
        f"AND updated_at < {_sql_text(stale_cutoff.isoformat(timespec='seconds'))};"
    )

    rows = _query(
        "SELECT id, session_id, terminal_id, agent, request, skill_num, skill_name, "
        "step_order, status, summary, started_at, updated_at "
        "FROM hive_skill_chains "
        "ORDER BY updated_at DESC, id DESC;"
    )

    grouped: dict[tuple[int, str], list[dict]] = {}
    for row in rows:
        row['terminal_id'] = int(row.get('terminal_id') or 0)
        row['skill_num'] = int(row.get('skill_num') or 0)
        row['step_order'] = int(row.get('step_order') or 0)
        grouped.setdefault((row['terminal_id'], row.get('session_id', '')), []).append(row)

    active_sessions: dict[int, str] = {}
    one_hour_ago = datetime.now() - timedelta(hours=1)
    for (terminal_id, session_id), session_rows in grouped.items():
        if terminal_id in active_sessions:
            continue
        statuses = {row.get('status', '') for row in session_rows}
        updated_values = [_parse_dt(row.get('updated_at')) for row in session_rows]
        updated_values = [value for value in updated_values if value is not None]
        latest = max(updated_values) if updated_values else None
        if latest and latest >= one_hour_ago and statuses.intersection({'running', 'pending'}):
            active_sessions[terminal_id] = session_id

    eight_hours_ago = datetime.now() - timedelta(hours=8)
    for (terminal_id, session_id), session_rows in sorted(
        grouped.items(),
        key=lambda item: max(
            [_parse_dt(row.get('updated_at')) or datetime.min for row in item[1]],
            default=datetime.min,
        ),
        reverse=True,
    ):
        if terminal_id in active_sessions:
            continue
        updated_values = [_parse_dt(row.get('updated_at')) for row in session_rows]
        updated_values = [value for value in updated_values if value is not None]
        latest = max(updated_values) if updated_values else None
        has_real_work = any(row.get('status') in {'done', 'running', 'failed'} for row in session_rows)
        if latest and latest >= eight_hours_ago and has_real_work:
            active_sessions[terminal_id] = session_id

    terminals: dict[str, dict] = {}
    for terminal_id, session_id in active_sessions.items():
        session_rows = grouped.get((terminal_id, session_id), [])
        if not session_rows:
            continue
        session_rows = sorted(session_rows, key=lambda row: row.get('step_order', 0))
        statuses = [row.get('status', '') for row in session_rows]
        if 'running' in statuses:
            chain_status = 'running'
        elif all(status in {'done', 'skipped', 'failed'} for status in statuses):
            chain_status = 'done'
        else:
            chain_status = 'running'

        updated_values = [_parse_dt(row.get('updated_at')) for row in session_rows]
        updated_values = [value for value in updated_values if value is not None]
        latest = max(updated_values).isoformat(timespec='seconds') if updated_values else ''

        terminals[str(terminal_id)] = {
            "session_id": session_id,
            "request": session_rows[0].get('request', ''),
            "status": chain_status,
            "updated_at": latest,
            "agent": session_rows[0].get('agent', ''),
            "steps": [
                {
                    "label": f"{terminal_id}-{row.get('skill_num', 0)}",
                    "skill_num": row.get('skill_num', 0),
                    "skill_name": row.get('skill_name', ''),
                    "step_order": row.get('step_order', 0),
                    "status": row.get('status', ''),
                    "summary": row.get('summary', '') or '',
                }
                for row in session_rows
            ],
        }

    return {
        "skill_registry": SKILL_REGISTRY,
        "terminals": terminals,
    }


def main() -> None:
    if sys.platform == 'win32':
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except AttributeError:
            pass

    args = sys.argv[1:]
    if not args:
        print("usage:")
        print("  python skill_orchestrator.py plan [--terminal N] <request> <skill1> [skill2 ...]")
        print("  python skill_orchestrator.py update <step> <status> [summary]")
        print("  python skill_orchestrator.py status")
        print("  python skill_orchestrator.py done [--terminal N]")
        print("  python skill_orchestrator.py reset [--terminal N]")
        sys.exit(0)

    command = args[0].lower()
    rest = args[1:]

    terminal_id = _get_terminal_id()
    filtered: list[str] = []
    index = 0
    while index < len(rest):
        if rest[index] == '--terminal' and index + 1 < len(rest):
            try:
                terminal_id = int(rest[index + 1])
            except ValueError:
                print(f"[ERROR] invalid terminal: {rest[index + 1]}")
                sys.exit(1)
            index += 2
            continue
        filtered.append(rest[index])
        index += 1
    rest = filtered

    if command == 'plan':
        if len(rest) < 2:
            print("[ERROR] plan requires a request and at least one skill")
            sys.exit(1)
        cmd_plan(terminal_id, rest[0], rest[1:])
        return

    if command == 'update':
        if len(rest) < 2:
            print("[ERROR] update requires <step> <status> [summary]")
            sys.exit(1)
        try:
            step = int(rest[0])
        except ValueError:
            print(f"[ERROR] invalid step: {rest[0]}")
            sys.exit(1)
        cmd_update(terminal_id, step, rest[1], ' '.join(rest[2:]).strip())
        return

    if command == 'status':
        cmd_status()
        return

    if command == 'done':
        cmd_done(terminal_id)
        return

    if command == 'reset':
        cmd_reset(terminal_id)
        return

    print(f"[ERROR] unknown command: {command}")
    sys.exit(1)


if __name__ == '__main__':
    main()
