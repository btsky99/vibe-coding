import csv
import io
import json
import os
import sqlite3
import subprocess
import threading
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / '.ai_monitor' / 'data'
PG_BIN = PROJECT_ROOT / '.ai_monitor' / 'bin' / 'pgsql' / 'bin' / 'psql.exe'
PG_PORT = '5433'
PG_USER = 'postgres'
PG_DB = 'postgres'

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False
_MIGRATION_DONE = False


def _now_iso() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def _sql_text(value) -> str:
    if value is None:
        return 'NULL'
    return "'" + str(value).replace("'", "''") + "'"


def _sql_json(value) -> str:
    return _sql_text(json.dumps(value, ensure_ascii=False)) + '::jsonb'


def _parse_json_text(value, default):
    if value in (None, ''):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _run_psql(sql: str, csv_output: bool = False, timeout: int = 15) -> tuple[bool, str]:
    if not PG_BIN.exists():
        return False, 'psql.exe not found'
    no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    env = {**os.environ, 'PGCLIENTENCODING': 'UTF8'}
    cmd = [
        str(PG_BIN), '-X', '-q', '-v', 'ON_ERROR_STOP=1',
        '-p', PG_PORT, '-U', PG_USER, '-d', PG_DB,
    ]
    if csv_output:
        cmd.append('--csv')
    try:
        result = subprocess.run(
            cmd,
            input=sql,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            creationflags=no_window,
            env=env,
        )
        if result.returncode != 0:
            return False, (result.stderr or result.stdout).strip()
        return True, result.stdout.strip()
    except Exception as exc:
        return False, str(exc)


def _ensure_pg_running() -> bool:
    ok, _ = _run_psql('SELECT 1;', timeout=2)
    if ok:
        return True
    pg_manager = PROJECT_ROOT / 'scripts' / 'pg_manager.py'
    if not pg_manager.exists():
        return False
    no_window = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    try:
        subprocess.Popen(
            ['python', str(pg_manager), 'start'],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=no_window,
        )
    except Exception:
        return False
    for _ in range(10):
        time.sleep(0.5)
        ok, _ = _run_psql('SELECT 1;', timeout=2)
        if ok:
            return True
    return False


def query_rows(sql: str, timeout: int = 15) -> list[dict]:
    if not ensure_schema():
        return []
    ok, output = _run_psql(sql, csv_output=True, timeout=timeout)
    if not ok or not output.strip():
        return []
    return list(csv.DictReader(io.StringIO(output)))


def execute(sql: str, timeout: int = 15) -> bool:
    if not ensure_schema():
        return False
    ok, _ = _run_psql(sql, csv_output=False, timeout=timeout)
    return ok


def ensure_schema(data_dir: Path | None = None) -> bool:
    global _SCHEMA_READY, _MIGRATION_DONE
    if _SCHEMA_READY:
        return True
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return True
        if not _ensure_pg_running():
            return False
        schema_sql = """
        CREATE EXTENSION IF NOT EXISTS pg_trgm;

        CREATE TABLE IF NOT EXISTS hive_memory (
            key TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            author TEXT NOT NULL DEFAULT 'unknown',
            project TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_hive_memory_updated ON hive_memory (updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_hive_memory_project ON hive_memory (project);

        CREATE TABLE IF NOT EXISTS hive_sessions (
            id BIGSERIAL PRIMARY KEY,
            legacy_source TEXT,
            legacy_id BIGINT,
            session_id TEXT NOT NULL,
            terminal_id TEXT DEFAULT '',
            project TEXT DEFAULT '',
            agent TEXT DEFAULT '',
            trigger_msg TEXT DEFAULT '',
            status TEXT DEFAULT '',
            commit_hash TEXT DEFAULT '',
            files_changed JSONB NOT NULL DEFAULT '[]'::jsonb,
            ts_start TEXT NOT NULL DEFAULT '',
            ts_end TEXT DEFAULT ''
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_hive_sessions_legacy
            ON hive_sessions (legacy_source, legacy_id)
            WHERE legacy_source IS NOT NULL AND legacy_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_hive_sessions_start ON hive_sessions (ts_start DESC);

        CREATE TABLE IF NOT EXISTS hive_tasks (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            assigned_to TEXT NOT NULL DEFAULT 'all',
            priority TEXT NOT NULL DEFAULT 'medium',
            created_by TEXT NOT NULL DEFAULT 'user',
            kanban_status TEXT NOT NULL DEFAULT 'todo',
            role TEXT NOT NULL DEFAULT '',
            claimed_by TEXT NOT NULL DEFAULT '',
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            extra JSONB NOT NULL DEFAULT '{}'::jsonb
        );
        CREATE INDEX IF NOT EXISTS idx_hive_tasks_updated ON hive_tasks (updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_hive_tasks_assigned ON hive_tasks (assigned_to, status);

        CREATE TABLE IF NOT EXISTS hive_state (
            state_key TEXT PRIMARY KEY,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS hive_skill_chains (
            id BIGSERIAL PRIMARY KEY,
            legacy_id BIGINT,
            session_id TEXT NOT NULL,
            terminal_id INTEGER NOT NULL DEFAULT 0,
            agent TEXT DEFAULT '',
            request TEXT DEFAULT '',
            skill_num INTEGER DEFAULT 0,
            skill_name TEXT DEFAULT '',
            step_order INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            summary TEXT DEFAULT '',
            started_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_hive_skill_chains_legacy
            ON hive_skill_chains (legacy_id)
            WHERE legacy_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_hive_skill_chains_terminal
            ON hive_skill_chains (terminal_id, session_id, step_order);
        """
        if not execute_raw(schema_sql, timeout=30):
            return False
        _SCHEMA_READY = True
        if not _MIGRATION_DONE:
            migrate_legacy_data(data_dir or DATA_DIR)
            _MIGRATION_DONE = True
        return True


def execute_raw(sql: str, timeout: int = 15) -> bool:
    ok, _ = _run_psql(sql, csv_output=False, timeout=timeout)
    return ok


def migrate_legacy_data(data_dir: Path | None = None) -> None:
    data_dir = data_dir or DATA_DIR
    _migrate_memory(data_dir / 'shared_memory.db')
    _migrate_sessions(data_dir / 'hive_mind.db')
    _migrate_tasks(data_dir / 'tasks.json')
    _migrate_state_file(data_dir / 'hive_health.json', 'health')
    _migrate_state_file(data_dir / 'skill_analysis.json', 'skill_analysis')
    _migrate_skill_chains(data_dir / 'skill_chain.db')


def _migrate_memory(path: Path) -> None:
    if not path.exists():
        return
    try:
        with sqlite3.connect(str(path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT key, title, content, tags, author, project, timestamp, updated_at FROM memory"
            ).fetchall()
    except Exception:
        return
    for row in rows:
        row = dict(row)
        set_memory(
            key=row.get('key', ''),
            content=row.get('content', ''),
            title=row.get('title', '') or row.get('key', ''),
            tags=_parse_json_text(row.get('tags'), []),
            author=row.get('author', 'unknown'),
            project=row.get('project', ''),
            created_at=row.get('timestamp') or row.get('updated_at') or '',
            updated_at=row.get('updated_at') or row.get('timestamp') or '',
        )


def _migrate_sessions(path: Path) -> None:
    if not path.exists():
        return
    try:
        with sqlite3.connect(str(path)) as conn:
            conn.row_factory = sqlite3.Row
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='session_logs'"
            ).fetchone()
            if not exists:
                return
            rows = conn.execute("SELECT * FROM session_logs ORDER BY id").fetchall()
    except Exception:
        return
    for row in rows:
        row = dict(row)
        upsert_session_log(
            session_id=row.get('session_id', ''),
            terminal_id=row.get('terminal_id', ''),
            project=row.get('project', ''),
            agent=row.get('agent', ''),
            trigger_msg=row.get('trigger_msg', ''),
            status=row.get('status', ''),
            commit_hash=row.get('commit_hash', ''),
            files_changed=_parse_json_text(row.get('files_changed'), []),
            ts_start=row.get('ts_start', ''),
            ts_end=row.get('ts_end', ''),
            legacy_source='hive_mind.db',
            legacy_id=row.get('id'),
        )


def _migrate_tasks(path: Path) -> None:
    if not path.exists():
        return
    try:
        tasks = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return
    if not isinstance(tasks, list):
        return
    for task in tasks:
        if isinstance(task, dict):
            save_task(task)


def _migrate_state_file(path: Path, state_key: str) -> None:
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return
    save_state(state_key, payload)


def _migrate_skill_chains(path: Path) -> None:
    if not path.exists():
        return
    try:
        with sqlite3.connect(str(path)) as conn:
            conn.row_factory = sqlite3.Row
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='skill_chains'"
            ).fetchone()
            if not exists:
                return
            rows = conn.execute("SELECT * FROM skill_chains ORDER BY id").fetchall()
    except Exception:
        return
    for row in rows:
        row = dict(row)
        upsert_skill_chain_row(row, legacy_id=row.get('id'))


def list_memory(q: str = '', top_k: int = 20, project: str = '', show_all: bool = False) -> list[dict]:
    filters = []
    if project and not show_all:
        filters.append(f"project = {_sql_text(project)}")
    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ''
    if q:
        q_sql = _sql_text(q)
        query = f"""
        SELECT key, title, content, author, project, created_at, updated_at, tags::text AS tags
        FROM hive_memory
        {where_sql} {'AND' if where_sql else 'WHERE'}
            (
                LOWER(key) LIKE LOWER('%' || {q_sql} || '%')
                OR LOWER(title) LIKE LOWER('%' || {q_sql} || '%')
                OR LOWER(content) LIKE LOWER('%' || {q_sql} || '%')
                OR tags::text LIKE '%' || {q_sql} || '%'
            )
        ORDER BY updated_at DESC
        LIMIT {int(top_k)};
        """
    else:
        query = f"""
        SELECT key, title, content, author, project, created_at, updated_at, tags::text AS tags
        FROM hive_memory
        {where_sql}
        ORDER BY updated_at DESC
        LIMIT {int(top_k)};
        """
    rows = query_rows(query)
    for row in rows:
        row['tags'] = _parse_json_text(row.get('tags'), [])
    return rows


def get_memory(key: str) -> dict | None:
    rows = query_rows(
        f"SELECT key, title, content, author, project, created_at, updated_at, tags::text AS tags "
        f"FROM hive_memory WHERE key = {_sql_text(key)} LIMIT 1;"
    )
    if not rows:
        return None
    row = rows[0]
    row['tags'] = _parse_json_text(row.get('tags'), [])
    return row


def set_memory(
    key: str,
    content: str,
    title: str = '',
    tags: list | None = None,
    author: str = 'unknown',
    project: str = '',
    created_at: str = '',
    updated_at: str = '',
) -> dict | None:
    if not key or content is None:
        return None
    existing = get_memory(key)
    created_value = existing.get('created_at', '') if existing else (created_at or updated_at or _now_iso())
    updated_value = updated_at or _now_iso()
    title_value = title or key
    execute(
        f"""
        INSERT INTO hive_memory (key, title, content, tags, author, project, created_at, updated_at)
        VALUES (
            {_sql_text(key)},
            {_sql_text(title_value)},
            {_sql_text(content)},
            {_sql_json(tags or [])},
            {_sql_text(author)},
            {_sql_text(project)},
            {_sql_text(created_value)},
            {_sql_text(updated_value)}
        )
        ON CONFLICT (key) DO UPDATE SET
            title = EXCLUDED.title,
            content = EXCLUDED.content,
            tags = EXCLUDED.tags,
            author = EXCLUDED.author,
            project = EXCLUDED.project,
            updated_at = EXCLUDED.updated_at;
        """
    )
    return get_memory(key)


def delete_memory(key: str) -> bool:
    return execute(f"DELETE FROM hive_memory WHERE key = {_sql_text(key)};")


def upsert_session_log(
    session_id: str,
    terminal_id: str = '',
    project: str = '',
    agent: str = '',
    trigger_msg: str = '',
    status: str = '',
    commit_hash: str = '',
    files_changed: list | None = None,
    ts_start: str = '',
    ts_end: str = '',
    legacy_source: str | None = None,
    legacy_id: int | None = None,
) -> bool:
    if legacy_source and legacy_id is not None:
        return execute(
            f"""
            INSERT INTO hive_sessions
                (legacy_source, legacy_id, session_id, terminal_id, project, agent, trigger_msg,
                 status, commit_hash, files_changed, ts_start, ts_end)
            VALUES (
                {_sql_text(legacy_source)}, {legacy_id}, {_sql_text(session_id)}, {_sql_text(terminal_id)},
                {_sql_text(project)}, {_sql_text(agent)}, {_sql_text(trigger_msg)}, {_sql_text(status)},
                {_sql_text(commit_hash)}, {_sql_json(files_changed or [])}, {_sql_text(ts_start or _now_iso())},
                {_sql_text(ts_end or '')}
            )
            ON CONFLICT (legacy_source, legacy_id) DO UPDATE SET
                session_id = EXCLUDED.session_id,
                terminal_id = EXCLUDED.terminal_id,
                project = EXCLUDED.project,
                agent = EXCLUDED.agent,
                trigger_msg = EXCLUDED.trigger_msg,
                status = EXCLUDED.status,
                commit_hash = EXCLUDED.commit_hash,
                files_changed = EXCLUDED.files_changed,
                ts_start = EXCLUDED.ts_start,
                ts_end = EXCLUDED.ts_end;
            """
        )
    return execute(
        f"""
        INSERT INTO hive_sessions
            (session_id, terminal_id, project, agent, trigger_msg, status, commit_hash, files_changed, ts_start, ts_end)
        VALUES (
            {_sql_text(session_id)}, {_sql_text(terminal_id)}, {_sql_text(project)}, {_sql_text(agent)},
            {_sql_text(trigger_msg)}, {_sql_text(status)}, {_sql_text(commit_hash)},
            {_sql_json(files_changed or [])}, {_sql_text(ts_start or _now_iso())}, {_sql_text(ts_end or '')}
        );
        """
    )


def list_session_logs(limit: int = 200) -> list[dict]:
    rows = query_rows(
        f"""
        SELECT id, session_id, terminal_id, project, agent, trigger_msg, status, commit_hash,
               files_changed::text AS files_changed, ts_start, ts_end
        FROM hive_sessions
        ORDER BY ts_start DESC, id DESC
        LIMIT {int(limit)};
        """
    )
    for row in rows:
        row['files_changed'] = _parse_json_text(row.get('files_changed'), [])
    return rows


def get_agent_last_seen(agent_names: list[str] | None = None) -> dict[str, str | None]:
    agent_names = agent_names or []
    result = {name: None for name in agent_names}
    rows = query_rows(
        "SELECT LOWER(agent) AS agent_name, MAX(ts_start) AS last_seen "
        "FROM hive_sessions GROUP BY LOWER(agent) ORDER BY last_seen DESC;"
    )
    for row in rows:
        agent_name = row.get('agent_name', '')
        for wanted in agent_names:
            if wanted in agent_name and result.get(wanted) is None:
                result[wanted] = row.get('last_seen')
    return result


def save_task(task: dict) -> dict | None:
    task_id = str(task.get('id', '')).strip()
    if not task_id:
        return None
    payload = {
        'timestamp': str(task.get('timestamp', '') or task.get('created_at', '') or _now_iso()),
        'updated_at': str(task.get('updated_at', '') or _now_iso()),
        'title': str(task.get('title', '')),
        'description': str(task.get('description', '')),
        'status': str(task.get('status', 'pending')),
        'assigned_to': str(task.get('assigned_to', 'all')),
        'priority': str(task.get('priority', 'medium')),
        'created_by': str(task.get('created_by', 'user')),
        'kanban_status': str(task.get('kanban_status', 'todo')),
        'role': str(task.get('role', '')),
        'claimed_by': str(task.get('claimed_by', '')),
        'tags': task.get('tags', []),
    }
    extra = {
        k: v for k, v in task.items()
        if k not in {'id', 'timestamp', 'updated_at', 'title', 'description', 'status', 'assigned_to',
                     'priority', 'created_by', 'kanban_status', 'role', 'claimed_by', 'tags'}
    }
    execute(
        f"""
        INSERT INTO hive_tasks
            (id, timestamp, updated_at, title, description, status, assigned_to, priority,
             created_by, kanban_status, role, claimed_by, tags, extra)
        VALUES (
            {_sql_text(task_id)}, {_sql_text(payload['timestamp'])}, {_sql_text(payload['updated_at'])},
            {_sql_text(payload['title'])}, {_sql_text(payload['description'])}, {_sql_text(payload['status'])},
            {_sql_text(payload['assigned_to'])}, {_sql_text(payload['priority'])}, {_sql_text(payload['created_by'])},
            {_sql_text(payload['kanban_status'])}, {_sql_text(payload['role'])}, {_sql_text(payload['claimed_by'])},
            {_sql_json(payload['tags'] if isinstance(payload['tags'], list) else [])}, {_sql_json(extra)}
        )
        ON CONFLICT (id) DO UPDATE SET
            timestamp = EXCLUDED.timestamp,
            updated_at = EXCLUDED.updated_at,
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            status = EXCLUDED.status,
            assigned_to = EXCLUDED.assigned_to,
            priority = EXCLUDED.priority,
            created_by = EXCLUDED.created_by,
            kanban_status = EXCLUDED.kanban_status,
            role = EXCLUDED.role,
            claimed_by = EXCLUDED.claimed_by,
            tags = EXCLUDED.tags,
            extra = EXCLUDED.extra;
        """
    )
    return get_task(task_id)


def list_tasks() -> list[dict]:
    rows = query_rows(
        """
        SELECT id, timestamp, updated_at, title, description, status, assigned_to, priority,
               created_by, kanban_status, role, claimed_by, tags::text AS tags, extra::text AS extra
        FROM hive_tasks
        ORDER BY updated_at DESC, timestamp DESC, id DESC;
        """
    )
    result = []
    for row in rows:
        task = {k: row.get(k) for k in (
            'id', 'timestamp', 'updated_at', 'title', 'description', 'status', 'assigned_to',
            'priority', 'created_by', 'kanban_status', 'role', 'claimed_by'
        )}
        task['tags'] = _parse_json_text(row.get('tags'), [])
        task.update(_parse_json_text(row.get('extra'), {}))
        result.append(task)
    return result


def get_task(task_id: str) -> dict | None:
    for task in list_tasks():
        if task.get('id') == task_id:
            return task
    return None


def update_task(task_id: str, updates: dict) -> dict | None:
    existing = get_task(task_id)
    if not existing:
        return None
    merged = {**existing, **updates}
    merged['id'] = task_id
    merged['updated_at'] = str(updates.get('updated_at', _now_iso()))
    if 'tags' in merged and isinstance(merged['tags'], str):
        merged['tags'] = [tag.strip() for tag in merged['tags'].split(',') if tag.strip()]
    return save_task(merged)


def delete_task(task_id: str) -> bool:
    return execute(f"DELETE FROM hive_tasks WHERE id = {_sql_text(task_id)};")


def bulk_update_tasks(assigned_to: str, statuses: list[str], new_status: str) -> int:
    if not statuses:
        return 0
    execute(
        f"""
        UPDATE hive_tasks
        SET status = {_sql_text(new_status)}, updated_at = {_sql_text(_now_iso())}
        WHERE assigned_to = {_sql_text(assigned_to)}
          AND status IN ({', '.join(_sql_text(status) for status in statuses)});
        """
    )
    return len([task for task in list_tasks() if task.get('assigned_to') == assigned_to and task.get('status') == new_status])


def save_state(state_key: str, payload: dict) -> bool:
    return execute(
        f"""
        INSERT INTO hive_state (state_key, payload, updated_at)
        VALUES ({_sql_text(state_key)}, {_sql_json(payload)}, {_sql_text(_now_iso())})
        ON CONFLICT (state_key) DO UPDATE SET
            payload = EXCLUDED.payload,
            updated_at = EXCLUDED.updated_at;
        """
    )


def load_state(state_key: str, default=None):
    rows = query_rows(
        f"SELECT payload::text AS payload FROM hive_state WHERE state_key = {_sql_text(state_key)} LIMIT 1;"
    )
    if not rows:
        return default
    return _parse_json_text(rows[0].get('payload'), default)


def upsert_skill_chain_row(row: dict, legacy_id: int | None = None) -> bool:
    if legacy_id is not None:
        return execute(
            f"""
            INSERT INTO hive_skill_chains
                (legacy_id, session_id, terminal_id, agent, request, skill_num, skill_name,
                 step_order, status, summary, started_at, updated_at)
            VALUES (
                {legacy_id}, {_sql_text(row.get('session_id', ''))}, {int(row.get('terminal_id', 0) or 0)},
                {_sql_text(row.get('agent', ''))}, {_sql_text(row.get('request', ''))},
                {int(row.get('skill_num', 0) or 0)}, {_sql_text(row.get('skill_name', ''))},
                {int(row.get('step_order', 0) or 0)}, {_sql_text(row.get('status', 'pending'))},
                {_sql_text(row.get('summary', ''))}, {_sql_text(row.get('started_at', ''))},
                {_sql_text(row.get('updated_at', ''))}
            )
            ON CONFLICT (legacy_id) DO UPDATE SET
                session_id = EXCLUDED.session_id,
                terminal_id = EXCLUDED.terminal_id,
                agent = EXCLUDED.agent,
                request = EXCLUDED.request,
                skill_num = EXCLUDED.skill_num,
                skill_name = EXCLUDED.skill_name,
                step_order = EXCLUDED.step_order,
                status = EXCLUDED.status,
                summary = EXCLUDED.summary,
                started_at = EXCLUDED.started_at,
                updated_at = EXCLUDED.updated_at;
            """
        )
    return execute(
        f"""
        INSERT INTO hive_skill_chains
            (session_id, terminal_id, agent, request, skill_num, skill_name, step_order, status, summary, started_at, updated_at)
        VALUES (
            {_sql_text(row.get('session_id', ''))}, {int(row.get('terminal_id', 0) or 0)},
            {_sql_text(row.get('agent', ''))}, {_sql_text(row.get('request', ''))},
            {int(row.get('skill_num', 0) or 0)}, {_sql_text(row.get('skill_name', ''))},
            {int(row.get('step_order', 0) or 0)}, {_sql_text(row.get('status', 'pending'))},
            {_sql_text(row.get('summary', ''))}, {_sql_text(row.get('started_at', ''))},
            {_sql_text(row.get('updated_at', ''))}
        );
        """
    )


def list_skill_chain_rows() -> list[dict]:
    return query_rows(
        """
        SELECT id, session_id, terminal_id, agent, request, skill_num, skill_name,
               step_order, status, summary, started_at, updated_at
        FROM hive_skill_chains
        ORDER BY updated_at DESC, id DESC;
        """
    )
