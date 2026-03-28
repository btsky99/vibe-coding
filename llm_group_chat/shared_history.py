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
    """새 하이브 메시지(채팅 포함) 도착 시 콜백 등록."""
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


def cleanup_old(keep_count: int = 200):
    """오래된 채팅 메시지 정리 — TTL로 자동 관리되므로 보통 불필요."""
    try:
        from src.pg_store import cleanup_expired_memory
        cleanup_expired_memory()
    except Exception:
        pass
