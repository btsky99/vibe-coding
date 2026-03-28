"""공유 대화 히스토리 — PostgreSQL 기반.

모든 그룹챗 에이전트가 같은 대화 컨텍스트를 공유합니다.
테이블: groupchat_messages
"""
import json
import os
import time

PG_PORT = int(os.environ.get('VIBE_PG_PORT', '5433'))
_initialized = False


def _get_conn():
    """PostgreSQL 연결 생성."""
    import psycopg2
    conn = psycopg2.connect(host='127.0.0.1', port=PG_PORT, user='postgres', dbname='postgres')
    conn.autocommit = True
    return conn


def _ensure_table():
    """groupchat_messages 테이블 생성 (없으면)."""
    global _initialized
    if _initialized:
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS groupchat_messages (
                id SERIAL PRIMARY KEY,
                sender TEXT NOT NULL,
                content TEXT NOT NULL,
                msg_type TEXT DEFAULT 'message',
                room TEXT DEFAULT 'default',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        # 오래된 메시지 자동 정리용 인덱스
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_groupchat_created
            ON groupchat_messages (created_at DESC)
        """)
        conn.close()
        _initialized = True
    except Exception as e:
        print(f"[공유히스토리] 테이블 생성 실패: {e}")


def save_message(sender: str, content: str, msg_type: str = "message", room: str = "default"):
    """메시지를 DB에 저장."""
    _ensure_table()
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO groupchat_messages (sender, content, msg_type, room) VALUES (%s, %s, %s, %s)",
            (sender, content[:2000], msg_type, room)
        )
        conn.close()
    except Exception as e:
        print(f"[공유히스토리] 저장 실패: {e}")


def get_recent(limit: int = 20, room: str = "default") -> list[dict]:
    """최근 메시지 N개 조회 (오래된 순).

    Returns:
        [{"sender": "T1-claude", "content": "안녕!", "ts": "11:05:03"}, ...]
    """
    _ensure_table()
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """SELECT sender, content, msg_type, created_at
               FROM groupchat_messages
               WHERE room = %s AND msg_type = 'message'
               ORDER BY id DESC LIMIT %s""",
            (room, limit)
        )
        rows = cur.fetchall()
        conn.close()

        # 오래된 순으로 뒤집기
        messages = []
        for sender, content, msg_type, ts in reversed(rows):
            messages.append({
                "sender": sender,
                "content": content,
                "ts": ts.strftime("%H:%M:%S") if ts else "",
            })
        return messages
    except Exception as e:
        print(f"[공유히스토리] 조회 실패: {e}")
        return []


def get_context_prompt(my_name: str, limit: int = 10) -> str:
    """에이전트용 컨텍스트 프롬프트 생성.

    최근 대화를 포맷해서 반환합니다.
    """
    messages = get_recent(limit)
    if not messages:
        return "(대화 시작)"

    lines = []
    for m in messages:
        lines.append(f"[{m['sender']}] {m['content']}")
    return "\n".join(lines)


def cleanup_old(keep_count: int = 200):
    """오래된 메시지 정리 (최근 N개만 유지)."""
    _ensure_table()
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """DELETE FROM groupchat_messages
               WHERE id NOT IN (
                   SELECT id FROM groupchat_messages ORDER BY id DESC LIMIT %s
               )""",
            (keep_count,)
        )
        conn.close()
    except Exception:
        pass
