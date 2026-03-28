"""공유 대화 히스토리 — PostgreSQL LISTEN/NOTIFY 기반 실시간 통신.

모든 그룹챗 에이전트가 같은 대화 컨텍스트를 공유합니다.
새 메시지 INSERT 시 NOTIFY 발생 → 다른 에이전트의 LISTEN이 감지.

테이블: groupchat_messages
채널: groupchat_new_message
"""
import json
import os
import time
import threading
from typing import Callable

PG_PORT = int(os.environ.get('VIBE_PG_PORT', '5433'))
_initialized = False

# LISTEN 콜백 관리
_listeners: list[Callable] = []
_listener_thread = None
_listener_running = False


def _get_conn():
    """PostgreSQL 연결 생성."""
    import psycopg2
    conn = psycopg2.connect(host='127.0.0.1', port=PG_PORT, user='postgres', dbname='postgres')
    conn.autocommit = True
    return conn


def _ensure_table():
    """groupchat_messages 테이블 + NOTIFY 트리거 생성."""
    global _initialized
    if _initialized:
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()

        # 메시지 테이블
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
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_groupchat_created
            ON groupchat_messages (created_at DESC)
        """)

        # INSERT 시 자동 NOTIFY하는 트리거 함수
        cur.execute("""
            CREATE OR REPLACE FUNCTION notify_groupchat_message()
            RETURNS TRIGGER AS $$
            BEGIN
                PERFORM pg_notify('groupchat_new_message',
                    json_build_object(
                        'id', NEW.id,
                        'sender', NEW.sender,
                        'content', NEW.content,
                        'msg_type', NEW.msg_type,
                        'room', NEW.room,
                        'created_at', NEW.created_at
                    )::text
                );
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)

        # 트리거 (이미 있으면 무시)
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger WHERE tgname = 'trg_groupchat_notify'
                ) THEN
                    CREATE TRIGGER trg_groupchat_notify
                    AFTER INSERT ON groupchat_messages
                    FOR EACH ROW EXECUTE FUNCTION notify_groupchat_message();
                END IF;
            END;
            $$;
        """)

        conn.close()
        _initialized = True
    except Exception as e:
        print(f"[공유히스토리] 테이블/트리거 생성 실패: {e}")


def save_message(sender: str, content: str, msg_type: str = "message", room: str = "default") -> int:
    """메시지를 DB에 저장. INSERT → 자동 NOTIFY 발생.

    Returns:
        저장된 메시지 ID (실패 시 -1)
    """
    _ensure_table()
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO groupchat_messages (sender, content, msg_type, room) VALUES (%s, %s, %s, %s) RETURNING id",
            (sender, content[:2000], msg_type, room)
        )
        msg_id = cur.fetchone()[0]
        conn.close()
        return msg_id
    except Exception as e:
        print(f"[공유히스토리] 저장 실패: {e}")
        return -1


def get_recent(limit: int = 20, room: str = "default") -> list[dict]:
    """최근 메시지 N개 조회 (오래된 순)."""
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
    """에이전트용 컨텍스트 프롬프트 생성."""
    messages = get_recent(limit)
    if not messages:
        return "(대화 시작)"

    lines = []
    for m in messages:
        lines.append(f"[{m['sender']}] {m['content']}")
    return "\n".join(lines)


def get_new_since(since_id: int, exclude_sender: str = "", limit: int = 20) -> tuple[list[dict], int]:
    """특정 ID 이후의 새 메시지 조회.

    Args:
        since_id: 이 ID 이후 메시지만
        exclude_sender: 이 발신자의 메시지 제외 (자기 메시지 에코 방지)
        limit: 최대 개수

    Returns:
        (메시지 리스트, 최신 ID)
    """
    _ensure_table()
    try:
        conn = _get_conn()
        cur = conn.cursor()
        if exclude_sender:
            cur.execute(
                """SELECT id, sender, content, msg_type, created_at
                   FROM groupchat_messages
                   WHERE id > %s AND sender != %s AND msg_type = 'message'
                   ORDER BY id ASC LIMIT %s""",
                (since_id, exclude_sender, limit)
            )
        else:
            cur.execute(
                """SELECT id, sender, content, msg_type, created_at
                   FROM groupchat_messages
                   WHERE id > %s AND msg_type = 'message'
                   ORDER BY id ASC LIMIT %s""",
                (since_id, limit)
            )
        rows = cur.fetchall()
        conn.close()

        messages = []
        latest_id = since_id
        for msg_id, sender, content, msg_type, ts in rows:
            messages.append({
                "id": msg_id,
                "sender": sender,
                "content": content,
                "ts": ts.strftime("%H:%M:%S") if ts else "",
            })
            latest_id = max(latest_id, msg_id)

        return messages, latest_id
    except Exception as e:
        print(f"[공유히스토리] 조회 실패: {e}")
        return [], since_id


# ── LISTEN/NOTIFY 리스너 ──

def add_listener(callback: Callable):
    """새 메시지 도착 시 호출될 콜백 등록.

    callback signature: (msg: dict) -> None
    msg: {"id": int, "sender": str, "content": str, "msg_type": str, "room": str}
    """
    _listeners.append(callback)
    _ensure_listener_running()


def _ensure_listener_running():
    """LISTEN 스레드가 돌고 있는지 확인, 없으면 시작."""
    global _listener_thread, _listener_running
    if _listener_running:
        return

    _listener_running = True
    _listener_thread = threading.Thread(target=_listen_loop, daemon=True, name="PG-LISTEN-GroupChat")
    _listener_thread.start()


def _listen_loop():
    """PostgreSQL LISTEN 루프 — 새 메시지 NOTIFY 감지."""
    global _listener_running
    import select

    while _listener_running:
        try:
            conn = _get_conn()
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("LISTEN groupchat_new_message")

            while _listener_running:
                # select로 알림 대기 (1초 타임아웃)
                if select.select([conn], [], [], 1.0) == ([], [], []):
                    continue

                conn.poll()
                while conn.notifies:
                    notify = conn.notifies.pop(0)
                    try:
                        payload = json.loads(notify.payload)
                        # 등록된 모든 콜백 호출
                        for cb in _listeners:
                            try:
                                cb(payload)
                            except Exception as e:
                                print(f"[LISTEN] 콜백 오류: {e}")
                    except json.JSONDecodeError:
                        pass

        except Exception as e:
            print(f"[LISTEN] 연결 오류, 3초 후 재시도: {e}")
            time.sleep(3)


def cleanup_old(keep_count: int = 200):
    """오래된 메시지 정리."""
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
