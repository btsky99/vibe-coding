import json
import sqlite3
import time

from src.db import get_connection, init_db
from src.pg_store import ensure_schema, list_session_logs, upsert_session_log


def _ensure_tables():
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='session_logs'")
        if not cursor.fetchone():
            init_db()
    except Exception:
        pass
    finally:
        conn.close()


def insert_log(session_id, terminal_id, agent, trigger_msg, project="hive", status="running"):
    try:
        ensure_schema()
        upsert_session_log(
            session_id=session_id,
            terminal_id=terminal_id,
            project=project,
            agent=agent,
            trigger_msg=trigger_msg,
            status=status,
            ts_start=time.strftime('%Y-%m-%dT%H:%M:%S'),
        )
    except Exception:
        pass


def get_recent_logs(limit=50):
    try:
        ensure_schema()
        return list_session_logs(limit)[::-1]
    except Exception:
        return []


def send_message(msg_id, from_agent, to_agent, msg_type, content):
    try:
        _ensure_tables()
        conn = get_connection()
        try:
            for attempt in range(3):
                try:
                    current_id = msg_id if attempt == 0 else f"{msg_id}_{int(time.time() % 1000)}"
                    conn.execute(
                        '''
                        INSERT INTO messages (id, msg_from, msg_to, msg_type, content)
                        VALUES (?, ?, ?, ?, ?)
                        ''',
                        (current_id, from_agent, to_agent, msg_type, content),
                    )
                    conn.commit()
                    return True
                except sqlite3.IntegrityError:
                    if attempt == 2:
                        raise
                    time.sleep(0.01)
        finally:
            conn.close()
    except Exception:
        return False


def get_messages(limit=50):
    try:
        _ensure_tables()
        conn = get_connection()
        try:
            cursor = conn.execute(
                '''
                SELECT * FROM messages
                ORDER BY timestamp DESC LIMIT ?
                ''',
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
    except Exception:
        return []


def clear_messages():
    try:
        _ensure_tables()
        conn = get_connection()
        try:
            conn.execute('DELETE FROM messages')
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception:
        return False
