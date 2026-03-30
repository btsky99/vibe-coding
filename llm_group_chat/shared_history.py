"""공유 대화 히스토리 — 하이브 마인드(hive_memory) 통합.

별도 groupchat_messages 테이블 대신 기존 hive_memory를 사용합니다.
채팅 메시지는 tag: ["chat"]로 구분됩니다.
LISTEN/NOTIFY는 hive_memory 트리거가 자동 처리합니다.
"""
import json
import os
import sys
import threading
import time
from typing import Callable
from pathlib import Path

# pg_store 경로 추가
_MONITOR_DIR = Path(__file__).resolve().parent.parent / ".ai_monitor"
if str(_MONITOR_DIR) not in sys.path:
    sys.path.insert(0, str(_MONITOR_DIR))

PG_PORT = int(os.environ.get('VIBE_PG_PORT', '5433'))

# LISTEN 콜백 관리
_listeners: list[Callable] = []
_listener_thread = None
_listener_running = False


def save_message(sender: str, content: str, **kwargs) -> int:
    """채팅 메시지 저장 — hive_memory에 INSERT (→ NOTIFY 자동)."""
    try:
        from src.pg_store import send_chat
        result = send_chat(sender, content)
        return 1 if result else -1
    except Exception as e:
        print(f"[공유히스토리] 저장 실패: {e}")
        return -1


def get_recent(limit: int = 20, **kwargs) -> list[dict]:
    """최근 채팅 메시지 조회."""
    try:
        from src.pg_store import get_chat_history
        return get_chat_history(limit)
    except Exception as e:
        print(f"[공유히스토리] 조회 실패: {e}")
        return []


def get_context_prompt(my_name: str = "", limit: int = 10) -> str:
    """에이전트용 컨텍스트 프롬프트."""
    try:
        from src.pg_store import get_chat_context
        return get_chat_context(limit)
    except Exception as e:
        return "(대화 없음)"


# ── LISTEN/NOTIFY 리스너 (hive_realtime 채널) ──

def add_listener(callback: Callable):
    """새 하이브 메시지(채팅 포함) 도착 시 콜백 등록. 중복 등록 방지."""
    if callback not in _listeners:
        _listeners.append(callback)
    _ensure_listener_running()


def _ensure_listener_running():
    global _listener_thread, _listener_running
    if _listener_running:
        return
    _listener_running = True
    _listener_thread = threading.Thread(target=_listen_loop, daemon=True, name="HiveRealtimeListen")
    _listener_thread.start()


def _get_project_db() -> str:
    """pg_store와 동일한 프로젝트 DB 이름 반환."""
    try:
        from src.pg_store import _resolve_project_db
        return _resolve_project_db()
    except Exception:
        return os.environ.get('VIBE_PG_DB', 'postgres')


def _listen_loop():
    """PostgreSQL LISTEN 루프 — hive_realtime 채널."""
    global _listener_running
    import select
    db_name = _get_project_db()

    while _listener_running:
        try:
            import psycopg2
            conn = psycopg2.connect(host='127.0.0.1', port=PG_PORT, user='postgres', dbname=db_name)
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("LISTEN hive_realtime")

            while _listener_running:
                if select.select([conn], [], [], 1.0) == ([], [], []):
                    continue
                conn.poll()
                while conn.notifies:
                    notify = conn.notifies.pop(0)
                    try:
                        payload = json.loads(notify.payload)
                        # 채팅 메시지만 콜백 (tag에 "chat" 포함)
                        tags = payload.get("tags", [])
                        if isinstance(tags, str):
                            tags = json.loads(tags)
                        if "chat" in tags:
                            for cb in _listeners:
                                try:
                                    cb(payload)
                                except Exception:
                                    pass
                    except json.JSONDecodeError:
                        pass

        except Exception as e:
            print(f"[LISTEN] 연결 오류, 3초 후 재시도: {e}")
            time.sleep(3)


def _ensure_table():
    """hive_memory 테이블 + LISTEN/NOTIFY 트리거 존재 확인.

    [2026-03-29 추가] MCP 서버 초기화 시 호출하여
    테이블과 트리거가 확실히 존재하도록 보장합니다.
    """
    try:
        from src.pg_store import ensure_schema
        ensure_schema()
    except Exception as e:
        print(f"[공유히스토리] 테이블 확인 실패: {e}")


def get_new_since(last_ts: str, exclude_sender: str = "", limit: int = 20) -> tuple[list[dict], str]:
    """last_ts(updated_at) 이후의 새 채팅 메시지를 조회합니다.

    [2026-03-29 추가] MCP 서버의 _check_new()에서 LISTEN 누락 메시지 보완용.
    hive_memory에 id 컬럼이 없으므로 updated_at(TEXT, ISO형식) 기준으로 조회합니다.

    Args:
        last_ts: 마지막으로 읽은 메시지의 updated_at 값 (빈 문자열이면 전체)
        exclude_sender: 이 sender(author)의 메시지는 제외
        limit: 최대 조회 수

    Returns:
        (messages, new_last_ts) — 새 메시지 리스트와 마지막 timestamp
    """
    try:
        from src.pg_store import query_rows
        # updated_at은 TEXT(ISO format)이므로 문자열 비교로 시간순 필터 가능
        # [2026-03-30 Claude] SQL 인젝션 방지 강화 — 타임스탬프 형식 엄격 검증
        # 기존 화이트리스트 필터 + ISO 8601 형식 정규식 검증 추가
        import re
        safe_ts = "".join(c for c in str(last_ts) if c in "0123456789-T:+. ")
        # ISO 8601 형식만 허용: YYYY-MM-DDTHH:MM:SS 또는 유사 패턴
        if safe_ts and not re.match(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}', safe_ts):
            safe_ts = ""  # 형식 불일치 시 무시 (전체 조회로 폴백)
        if safe_ts:
            # 싱글쿼트 이스케이프도 적용 (이중 방어)
            safe_ts = safe_ts.replace("'", "''")
            where_ts = f"AND updated_at > '{safe_ts}'"
        else:
            where_ts = ""
        safe_limit = max(1, min(int(limit), 200))  # limit도 범위 제한
        rows = query_rows(
            f"""
            SELECT key, content, author, updated_at
            FROM hive_memory
            WHERE tags @> '["chat"]'::jsonb
              {where_ts}
            ORDER BY updated_at ASC
            LIMIT {safe_limit};
            """
        )
        messages = []
        new_last_ts = last_ts
        for row in rows:
            author = row.get("author", "")
            if author == exclude_sender:
                continue
            ts = row.get("updated_at", "")
            messages.append({
                "id": row.get("key", ""),
                "sender": author,
                "content": row.get("content", ""),
                "ts": ts,
            })
            if ts > new_last_ts:
                new_last_ts = ts
        return messages, new_last_ts
    except Exception as e:
        print(f"[공유히스토리] get_new_since 실패: {e}")
        return [], last_ts


def cleanup_old(keep_count: int = 200):
    """오래된 채팅 메시지 정리 — TTL로 자동 관리되므로 보통 불필요."""
    try:
        from src.pg_store import cleanup_expired_memory
        cleanup_expired_memory()
    except Exception:
        pass
