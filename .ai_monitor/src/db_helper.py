import sys
import time
from pathlib import Path

from src.pg_store import ensure_schema, list_session_logs, upsert_session_log, execute, query_rows

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / 'scripts'
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from itcp import send as itcp_send


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
        return itcp_send(
            from_terminal=from_agent,
            to_terminal=to_agent,
            content=content,
            channel='general',
            msg_type=msg_type,
        )
    except Exception:
        return False


def get_messages(limit=50):
    try:
        rows = query_rows(
            f"""
            SELECT
                id::text AS id,
                from_agent AS msg_from,
                to_agent AS msg_to,
                msg_type,
                content,
                is_read::text AS is_read,
                ts::text AS timestamp
            FROM pg_messages
            ORDER BY ts DESC
            LIMIT {int(limit)};
            """
        )
        messages = []
        for row in rows:
            messages.append({
                'id': row.get('id', ''),
                'from': row.get('msg_from', ''),
                'to': row.get('msg_to', ''),
                'type': row.get('msg_type', 'info'),
                'content': row.get('content', ''),
                'read': str(row.get('is_read', '')).lower() == 'true',
                'timestamp': row.get('timestamp', ''),
            })
        return messages
    except Exception:
        return []


def clear_messages():
    try:
        ensure_schema()
        return execute("DELETE FROM pg_messages;")
    except Exception:
        return False
