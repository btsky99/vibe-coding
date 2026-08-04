# ────────────────────────────────────────────────────────────────────────────
# 📄 파일명: src/db_helper.py
# 📝 설명: 세션 로그 기록 헬퍼 — pg_store(upsert_session_log/list_session_logs)로
#          위임하는 얇은 래퍼. itcp 메시지 전송은 지연 import.
# 🕒 변경 이력:
# [2026-07-18] Claude — 헤더 누락 보강 (코드 품질 점검 규칙 5 준수)
#   - [제약] itcp는 scripts/ 에 있어 pip 설치 환경엔 없음 → ImportError 시 no-op 폴백.
# ────────────────────────────────────────────────────────────────────────────
import sys
import time
from pathlib import Path

from src.pg_store import ensure_schema, list_session_logs, upsert_session_log, execute, query_rows

# itcp 모듈은 scripts/ 디렉토리에 위치 — pip 설치 환경에서는 없을 수 있음
try:
    _SCRIPTS_DIR = Path(__file__).resolve().parents[2] / 'scripts'
    if str(_SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_DIR))
    from itcp import send as itcp_send
except ImportError:
    # pip 설치 환경: itcp 없이 동작 (메시지 전송 비활성화)
    def itcp_send(**kwargs):
        return False


def insert_log(session_id, terminal_id, agent, trigger_msg, project_id="hive", status="running"):
    try:
        ensure_schema()
        upsert_session_log(
            session_id=session_id,
            terminal_id=terminal_id,
            project_id=project_id,
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


def send_message(
    msg_id,
    from_agent,
    to_agent,
    msg_type,
    content,
    channel="general",
    terminal_id="",
    metadata=None,
):
    try:
        return itcp_send(
            from_terminal=from_agent,
            to_terminal=to_agent,
            content=content,
            channel=channel,
            msg_type=msg_type,
            terminal_id=terminal_id,
            metadata=metadata,
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
